"""NYC / LA XGBoost hyperparameter sweep — the city analog of `run_xgb_hpo.py`.

`run_xgb_hpo.py` is Chicago-only (it loads `features.parquet` and the monotone
production config). NYC and LA were never swept the same way: their 2026-07-18
round tuned only `max_depth` and `min_child_weight` by hand, so knobs that
mattered elsewhere are untested here — notably `colsample_bytree`, which was the
single robust lever the Chicago sweep found (0.85 -> 0.70).

Method, mirroring the Chicago sweep's discipline:

  Stage 1  expanding-window CV over the train+val region (test held out), scored
           on the raw XGB margin — PR-AUC and precision@10% are rank metrics, so
           the Platt step is irrelevant here. One-factor-at-a-time over each knob,
           then a randomized joint search.
  Stage 2  every Stage-1 candidate that clears the both-metrics gate is re-scored
           on the held-out test across N seeds. A config is only a "win" if it
           beats the incumbent on BOTH metrics in a clear majority of seeds.

Stage 2 exists because the Chicago sweep's apparent winner turned out to be a
lucky seed (delta +0.0000 across 8 seeds). Single-split deltas at this effect
size are noise; the seed check is what separates a real lever from a draw.

**LA caveat:** LA's CV region is a single fold (short post-COVID window), so its
Stage-1 ranking is weak evidence on its own — read LA's Stage-2 seed check as the
primary signal, and treat everything as directional.

Run:
  PYTHONPATH=src FOODSAFETY_DATA_DIR=<data> python scripts/run_city_xgb_hpo.py [nyc|la|all]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score

from foodsafety.models.evaluate import precision_at_k
from foodsafety.utils.time import expanding_year_folds, temporal_split

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import build_la_scores as la  # noqa: E402
import build_nyc_scores as nyc  # noqa: E402

OUT_DIR = REPO / "reports" / "metrics"

# Seeds for the Stage-2 robustness check. 8 matches the NYC/LA feature round.
SEEDS = [42, 7, 13, 101, 202, 303, 404, 505]

# One-factor-at-a-time grid. Values bracket each city's incumbent so a null shows
# up as "the incumbent is already at the optimum" rather than an untested guess.
OFAT_GRID: dict[str, list] = {
    "max_depth": [2, 3, 4],
    "learning_rate": [0.03, 0.05, 0.08],
    "n_estimators": [200, 400, 800],
    "min_child_weight": [5, 10, 20, 40],
    "subsample": [0.7, 0.8, 0.9, 1.0],
    "colsample_bytree": [0.6, 0.7, 0.8, 1.0],
    "colsample_bylevel": [0.7, 1.0],
    "reg_lambda": [1.0, 4.0, 8.0],
    "reg_alpha": [0.0, 1.0],
    "gamma": [0.0, 1.0],
}

N_RANDOM = 60


def sample_config(rng: np.random.Generator) -> dict:
    """One draw from the joint space (same knobs as the OFAT grid)."""
    return {
        "max_depth": int(rng.choice([2, 3, 4])),
        "learning_rate": float(rng.choice([0.03, 0.05, 0.08])),
        "n_estimators": int(rng.choice([200, 400, 800])),
        "min_child_weight": float(rng.choice([5, 10, 20, 40])),
        "subsample": float(rng.choice([0.7, 0.8, 0.9])),
        "colsample_bytree": float(rng.choice([0.6, 0.7, 0.8, 1.0])),
        "reg_lambda": float(rng.choice([1.0, 4.0, 8.0])),
        "reg_alpha": float(rng.choice([0.0, 1.0])),
        "gamma": float(rng.choice([0.0, 1.0])),
    }


def load_city(city: str) -> dict:
    if city == "nyc":
        ev, PRIOR, CURRENT, _tc, _sc, _raw = nyc.build_events()
        return dict(
            ev=ev,
            feats=list(PRIOR) + list(CURRENT),
            label="y_next_bc",
            train_start=nyc.NYC_TRAIN_START,
            train_end=nyc.TRAIN_END,
            val_end=nyc.VAL_END,
            fit=nyc.fit_xgb_platt,
        )
    if city == "la":
        raw = la.build_raw()
        ev, PRIOR, CURRENT, _tc, _sc = la.build_events(raw)
        return dict(
            ev=ev,
            feats=list(PRIOR) + list(CURRENT),
            label="y_next_bad",
            train_start=la.LA_TRAIN_START,
            train_end=la.TRAIN_END,
            val_end=la.VAL_END,
            fit=la.fit_xgb_platt,
        )
    raise ValueError(city)


def cv_score(cv_df, feats, folds, label, fit_fn, params) -> dict:
    """Mean PR-AUC / precision@10% over the expanding-window folds."""
    pr, p10 = [], []
    y = cv_df[label].astype(int).to_numpy()
    for tr, va in folds:
        tr_df, va_df = cv_df.iloc[tr], cv_df.iloc[va]
        clf, _, _ = fit_fn(tr_df, va_df, feats, label=label, params=params)
        margin = clf.predict(va_df[feats], output_margin=True)
        pr.append(float(average_precision_score(y[va], margin)))
        p10.append(float(precision_at_k(y[va], margin, 0.10)))
    return {"pr": float(np.mean(pr)), "p10": float(np.mean(p10))}


def seed_score(sp, feats, label, fit_fn, params) -> dict:
    """Held-out test PR-AUC / precision@10%, averaged over SEEDS."""
    y = sp.test[label].astype(int).to_numpy()
    pr, p10 = [], []
    for s in SEEDS:
        p = dict(params or {})
        p["random_state"] = s
        clf, _, _ = fit_fn(sp.train, sp.val, feats, label=label, params=p)
        margin = clf.predict(sp.test[feats], output_margin=True)
        pr.append(float(average_precision_score(y, margin)))
        p10.append(float(precision_at_k(y, margin, 0.10)))
    return {
        "pr": float(np.mean(pr)),
        "p10": float(np.mean(p10)),
        "pr_seeds": [round(x, 5) for x in pr],
        "p10_seeds": [round(x, 5) for x in p10],
    }


def run_city(city: str) -> dict:
    c = load_city(city)
    ev, feats, label = c["ev"], c["feats"], c["label"]

    anch = ev[ev["next_score"].notna() & (ev["inspection_date"] >= c["train_start"])].copy()
    cv_df = anch[anch["inspection_date"] < c["val_end"]].reset_index(drop=True)
    folds = expanding_year_folds(cv_df)
    sp = temporal_split(
        anch, date_col="inspection_date", train_end=c["train_end"], val_end=c["val_end"]
    )
    print(
        f"\n===== {city.upper()} HPO =====  feats={len(feats)}  CV n={len(cv_df):,}  "
        f"folds={len(folds)}  test n={len(sp.test):,}"
    )
    if len(folds) < 2:
        print("  !! single CV fold — Stage 1 is weak evidence here; trust the seed check.")

    t0 = time.time()
    base_cv = cv_score(cv_df, feats, folds, label, c["fit"], None)
    print(
        f"INCUMBENT  cv pr={base_cv['pr']:.4f} p10={base_cv['p10']:.4f}  ({time.time() - t0:.0f}s)"
    )

    # ---- Stage 1: one-factor-at-a-time, then a randomized joint search
    trials: list[dict] = []
    for knob, values in OFAT_GRID.items():
        for v in values:
            params = {knob: v}
            s = cv_score(cv_df, feats, folds, label, c["fit"], params)
            trials.append(
                {
                    "kind": "ofat",
                    "params": params,
                    "cv_pr": round(s["pr"], 5),
                    "cv_p10": round(s["p10"], 5),
                    "d_pr": round(s["pr"] - base_cv["pr"], 5),
                    "d_p10": round(s["p10"] - base_cv["p10"], 5),
                }
            )
            flag = "PASS" if s["pr"] >= base_cv["pr"] and s["p10"] >= base_cv["p10"] else ""
            print(
                f"  {knob:18s}={str(v):6s} dPR={trials[-1]['d_pr']:+.4f} "
                f"dP10={trials[-1]['d_p10']:+.4f}  {flag}"
            )

    rng = np.random.default_rng(0)
    for _ in range(N_RANDOM):
        params = sample_config(rng)
        s = cv_score(cv_df, feats, folds, label, c["fit"], params)
        trials.append(
            {
                "kind": "random",
                "params": params,
                "cv_pr": round(s["pr"], 5),
                "cv_p10": round(s["p10"], 5),
                "d_pr": round(s["pr"] - base_cv["pr"], 5),
                "d_p10": round(s["p10"] - base_cv["p10"], 5),
            }
        )

    passers = [t for t in trials if t["d_pr"] >= 0 and t["d_p10"] >= 0]
    passers.sort(key=lambda t: t["d_pr"] + t["d_p10"], reverse=True)
    print(f"\n  Stage 1: {len(trials)} configs, {len(passers)} clear the CV both-metrics gate")

    # ---- Stage 2: seed-robustness on the held-out test for the top CV passers
    base_seed = seed_score(sp, feats, label, c["fit"], None)
    print(
        f"  INCUMBENT seed-mean ({len(SEEDS)} seeds): "
        f"pr={base_seed['pr']:.4f} p10={base_seed['p10']:.4f}"
    )

    confirmed = []
    for t in passers[:8]:
        s = seed_score(sp, feats, label, c["fit"], t["params"])
        wins = sum(
            1
            for a, b, a0, b0 in zip(
                s["pr_seeds"],
                s["p10_seeds"],
                base_seed["pr_seeds"],
                base_seed["p10_seeds"],
                strict=True,
            )
            if a > a0 and b > b0
        )
        rec = {
            **t,
            "seed_pr": round(s["pr"], 5),
            "seed_p10": round(s["p10"], 5),
            "d_seed_pr": round(s["pr"] - base_seed["pr"], 5),
            "d_seed_p10": round(s["p10"] - base_seed["p10"], 5),
            "both_up_seeds": f"{wins}/{len(SEEDS)}",
            "robust": bool(s["pr"] > base_seed["pr"] and s["p10"] > base_seed["p10"] and wins >= 6),
        }
        confirmed.append(rec)
        print(
            f"    {str(t['params'])[:64]:66s} dPR={rec['d_seed_pr']:+.4f} "
            f"dP10={rec['d_seed_p10']:+.4f} both-up {rec['both_up_seeds']}"
            f"{'  ROBUST' if rec['robust'] else ''}"
        )

    winners = [r for r in confirmed if r["robust"]]
    print(
        f"\n  VERDICT: {len(winners)} seed-robust improvement(s)"
        + ("" if winners else " — incumbent retained")
    )

    out = {
        "city": city,
        "n_features": len(feats),
        "seeds": SEEDS,
        "cv_folds": len(folds),
        "incumbent": {
            "cv_pr": round(base_cv["pr"], 5),
            "cv_p10": round(base_cv["p10"], 5),
            "seed_pr": round(base_seed["pr"], 5),
            "seed_p10": round(base_seed["p10"], 5),
            "pr_seeds": base_seed["pr_seeds"],
            "p10_seeds": base_seed["p10_seeds"],
        },
        "stage1_trials": trials,
        "stage2_confirmed": confirmed,
        "winners": winners,
    }
    (OUT_DIR / city).mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / city / f"{city}_xgb_hpo.json"
    p.write_text(json.dumps(out, indent=2))
    print(f"  wrote {p}")
    return out


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    for ct in ["nyc", "la"] if which == "all" else [which]:
        run_city(ct)
