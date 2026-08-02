"""MLP (feed-forward neural net) hyperparameter search — notebook 07's benchmark.

Feature set is frozen at v36 ``ALL_FEATURES`` (pure HPO, no feature changes). The
goal is to beat the incumbent MLP (nb07: served test PR-AUC 0.333, precision@10%
0.402) on the **both-metrics gate**, validated with **expanding-window CV**, not
a single split — the same discipline DR 0002 mandates for XGB.

Selection discipline (identical to scripts/run_xgb_hpo.py in the XGB worktree):
  * CV folds run on the TRAIN+VAL region only (inspection_date < 2025-07-01) so
    the 2025-07-01+ held-out TEST is never seen during search.
  * PR-AUC and precision@10% are rank metrics (calibration-invariant), so during
    search we score the raw pipeline predict_proba — no isotonic fit needed. The
    final winner is isotonic-calibrated + seed-averaged and evaluated on the true
    test exactly like nb07.
  * A candidate must not regress EITHER metric vs the incumbent on the CV mean.

Run (from the fsi-mlp-hpo worktree):
    PYTHONPATH=src FOODSAFETY_DATA_DIR=<data> OMP_NUM_THREADS=2 \
        python scripts/run_mlp_hpo.py --stage all --n-random 40

Expected runtime: MLP fits are ~15-60s each; the full broad sweep (~20 OFAT +
40 random) x 6 folds is roughly 1-3h on 2-4 cores. Use --fast for a 4-fold,
lighter draw first pass (~30-60 min).
"""

from __future__ import annotations

import argparse
import inspect
import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import average_precision_score
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.utils.class_weight import compute_sample_weight

from foodsafety.config import FEATURES_PATH, RANDOM_STATE
from foodsafety.models.baseline import ALL_FEATURES, LABEL_COL
from foodsafety.models.evaluate import evaluate, precision_at_k
from foodsafety.utils.time import expanding_year_folds, temporal_split

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "reports" / "metrics" / "mlp"

TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"  # test = inspection_date >= VAL_END; CV lives strictly before it
SEED = RANDOM_STATE

# The incumbent nb07 config. Every candidate is a delta off this dict; it is also
# the CV control so per-fold deltas are paired on identical folds.
INCUMBENT: dict = {
    "hidden_layer_sizes": (128, 64, 32),
    "activation": "relu",
    "alpha": 1e-4,
    "batch_size": 256,
    "learning_rate_init": 1e-3,
    "max_iter": 100,
    "n_iter_no_change": 10,
    "class_weight_mode": "balanced",  # balanced | none | sqrt
}


def _make_onehot() -> OneHotEncoder:
    kwargs = {"handle_unknown": "ignore", "min_frequency": 25}
    if "sparse_output" in inspect.signature(OneHotEncoder).parameters:
        kwargs["sparse_output"] = False
    else:
        kwargs["sparse"] = False
    return OneHotEncoder(**kwargs)


def build_pipe(params: dict, num_feats: list[str], cat_feats: list[str]) -> Pipeline:
    p = {**INCUMBENT, **params}
    preprocess = ColumnTransformer(
        transformers=[
            (
                "num",
                Pipeline(
                    [("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]
                ),
                num_feats,
            ),
            (
                "cat",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        ("onehot", _make_onehot()),
                    ]
                ),
                cat_feats,
            ),
        ],
        remainder="drop",
    )
    mlp = MLPClassifier(
        hidden_layer_sizes=tuple(p["hidden_layer_sizes"]),
        activation=p["activation"],
        solver="adam",
        alpha=float(p["alpha"]),
        batch_size=int(p["batch_size"]),
        learning_rate_init=float(p["learning_rate_init"]),
        max_iter=int(p["max_iter"]),
        early_stopping=True,
        validation_fraction=0.15,
        n_iter_no_change=int(p["n_iter_no_change"]),
        random_state=SEED,
        verbose=False,
    )
    return Pipeline([("preprocess", preprocess), ("mlp", mlp)])


def fit_pipe(pipe: Pipeline, X, y, mode: str):
    """Fit with the requested class-weighting mode; fall back if unsupported."""
    if mode == "none":
        pipe.fit(X, y)
        return
    if mode == "balanced":
        sw = compute_sample_weight(class_weight="balanced", y=y)
    elif mode == "sqrt":
        # softer than 'balanced': down-weight the majority by sqrt of the ratio
        full = compute_sample_weight(class_weight="balanced", y=y)
        sw = np.sqrt(full)
    else:
        raise ValueError(f"bad class_weight_mode {mode!r}")
    try:
        pipe.fit(X, y, mlp__sample_weight=sw)
    except TypeError:
        pipe.fit(X, y)  # this sklearn's MLP has no sample_weight support


def load_modelable() -> pd.DataFrame:
    feat = pd.read_parquet(FEATURES_PATH)
    mask = pd.Series(True, index=feat.index)
    if "is_burnin" in feat.columns:
        mask &= ~feat["is_burnin"]
    if "right_truncated" in feat.columns:
        mask &= ~feat["right_truncated"]
    return feat[mask].reset_index(drop=True)


def split_feature_types(df: pd.DataFrame) -> tuple[list[str], list[str]]:
    cat = [
        c
        for c in ALL_FEATURES
        if df[c].dtype == "object" or str(df[c].dtype).startswith("category")
    ]
    num = [c for c in ALL_FEATURES if c not in cat]
    return num, cat


def cv_score(params: dict, cv_df, folds, num_f, cat_f) -> dict:
    pr, p10 = [], []
    y_all = cv_df[LABEL_COL].astype(int).to_numpy()
    X_all = cv_df[ALL_FEATURES]
    mode = {**INCUMBENT, **params}["class_weight_mode"]
    for tr_idx, va_idx in folds:
        Xtr, ytr = X_all.iloc[tr_idx], y_all[tr_idx]
        Xva, yva = X_all.iloc[va_idx], y_all[va_idx]
        pipe = build_pipe(params, num_f, cat_f)
        fit_pipe(pipe, Xtr, ytr, mode)
        s = pipe.predict_proba(Xva)[:, 1]
        pr.append(float(average_precision_score(yva, s)))
        p10.append(float(precision_at_k(yva, s, 0.10)))
    return {
        "pr_auc_mean": float(np.mean(pr)),
        "p10_mean": float(np.mean(p10)),
        "pr_auc_folds": [round(x, 4) for x in pr],
        "p10_folds": [round(x, 4) for x in p10],
    }


def holdout_eval(params: dict, modelable, num_f, cat_f, seeds=(SEED,)) -> dict:
    """nb07 protocol: fit on train, isotonic-calibrate on val, eval on test.

    ``seeds`` >1 seed-averages the calibrated test probabilities for stability
    (the metrics doc notes the MLP only ties LogReg when properly seed-averaged).
    """
    sp = temporal_split(modelable, train_end=TRAIN_END, val_end=VAL_END)
    ytr = sp.train[LABEL_COL].astype(int).to_numpy()
    yva = sp.val[LABEL_COL].astype(int).to_numpy()
    yte = sp.test[LABEL_COL].astype(int).to_numpy()
    Xtr, Xva, Xte = sp.train[ALL_FEATURES], sp.val[ALL_FEATURES], sp.test[ALL_FEATURES]
    mode = {**INCUMBENT, **params}["class_weight_mode"]
    from sklearn.frozen import FrozenEstimator

    probs = []
    for sd in seeds:
        params_sd = {**params}
        pipe = build_pipe(params_sd, num_f, cat_f)
        pipe.named_steps["mlp"].set_params(random_state=sd)
        fit_pipe(pipe, Xtr, ytr, mode)
        cal = CalibratedClassifierCV(FrozenEstimator(pipe), method="isotonic")
        cal.fit(Xva, yva)
        probs.append(cal.predict_proba(Xte)[:, 1])
    p_te = np.mean(probs, axis=0)
    return evaluate(yte, p_te).to_dict()


# --------------------------------------------------------------------------- #
# Search spaces
# --------------------------------------------------------------------------- #
OFAT_GRID = {
    "hidden_layer_sizes": [(64,), (128, 64), (256, 128), (256, 128, 64), (64, 32)],
    "alpha": [1e-5, 1e-3, 1e-2],
    "learning_rate_init": [1e-4, 5e-4, 3e-3],
    "batch_size": [128, 512],
    "activation": ["tanh"],
    "n_iter_no_change": [20],
    "max_iter": [200],
    "class_weight_mode": ["none", "sqrt"],
}


def sample_random(rng) -> dict:
    # Pick an architecture by index — rng.choice can't sample directly from a list of
    # variable-length tuples (numpy tries to build a rectangular array and raises).
    archs = [(64,), (128, 64), (256, 128), (128, 64, 32), (256, 128, 64), (64, 32)]
    return {
        "hidden_layer_sizes": archs[int(rng.integers(len(archs)))],
        "alpha": float(rng.choice([1e-5, 1e-4, 1e-3, 1e-2])),
        "learning_rate_init": float(rng.choice([1e-4, 5e-4, 1e-3, 3e-3])),
        "batch_size": int(rng.choice([128, 256, 512])),
        "activation": str(rng.choice(["relu", "relu", "tanh"])),
        "n_iter_no_change": int(rng.choice([10, 20])),
        "max_iter": int(rng.choice([100, 200])),
        "class_weight_mode": str(rng.choice(["balanced", "balanced", "none", "sqrt"])),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["reproduce", "ofat", "random", "all"])
    ap.add_argument("--n-random", type=int, default=40)
    ap.add_argument("--fast", action="store_true", help="4 folds + fewer draws for a quick pass")
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    modelable = load_modelable()
    num_f, cat_f = split_feature_types(modelable)
    cv_df = modelable.loc[modelable["inspection_date"] < VAL_END].reset_index(drop=True)
    folds = expanding_year_folds(cv_df)
    if args.fast:
        folds = folds[-4:]
    fold_years = [
        int(pd.to_datetime(cv_df["inspection_date"].iloc[va]).dt.year.mode().iloc[0])
        for _, va in folds
    ]
    print(f"features: {len(ALL_FEATURES)} ({len(num_f)} num / {len(cat_f)} cat)")
    print(f"CV region n={len(cv_df):,} | {len(folds)} folds val_years={fold_years}")

    t0 = time.time()
    inc_cv = cv_score(INCUMBENT, cv_df, folds, num_f, cat_f)
    inc_test = holdout_eval(INCUMBENT, modelable, num_f, cat_f)
    print(
        f"\nINCUMBENT  CV pr_auc={inc_cv['pr_auc_mean']:.4f} p10={inc_cv['p10_mean']:.4f} "
        f"| TEST pr_auc={inc_test['pr_auc']:.4f} p10={inc_test['precision_at_10pct']:.4f} "
        f"({time.time() - t0:.0f}s)"
    )

    results: list[dict] = []

    def run(tag: str, params: dict) -> None:
        ts = time.time()
        cv = cv_score(params, cv_df, folds, num_f, cat_f)
        d_pr = cv["pr_auc_mean"] - inc_cv["pr_auc_mean"]
        d_p10 = cv["p10_mean"] - inc_cv["p10_mean"]
        rec = {
            "tag": tag,
            "params": {k: (list(v) if isinstance(v, tuple) else v) for k, v in params.items()},
            "cv_pr_auc": round(cv["pr_auc_mean"], 5),
            "cv_p10": round(cv["p10_mean"], 5),
            "d_pr": round(d_pr, 5),
            "d_p10": round(d_p10, 5),
            "both_gate": bool(d_pr >= 0 and d_p10 >= 0),
            "pr_folds": cv["pr_auc_folds"],
            "p10_folds": cv["p10_folds"],
        }
        results.append(rec)
        flag = "  <-- BOTH-GATE PASS" if rec["both_gate"] else ""
        print(f"  {tag:<30} dPR={d_pr:+.4f} dP10={d_p10:+.4f} {time.time() - ts:.0f}s{flag}")

    if args.stage in ("ofat", "all"):
        print("\n=== Stage A: one-factor-at-a-time (CV) ===")
        for knob, vals in OFAT_GRID.items():
            for v in vals:
                run(f"{knob}={v}", {knob: v})

    if args.stage in ("random", "all"):
        n = 20 if args.fast else args.n_random
        print(f"\n=== Stage B: randomized search x{n} (CV) ===")
        rng = np.random.default_rng(args.seed)
        for i in range(n):
            run(f"rand{i:03d}", sample_random(rng))

    passers = sorted(
        [r for r in results if r["both_gate"]], key=lambda r: r["cv_pr_auc"], reverse=True
    )
    print(
        f"\n=== both-gate passers: {len(passers)}/{len(results)} ; confirming top-5 on TEST (seed-avg x3) ==="
    )
    confirmed = []
    for r in passers[:5]:
        params = {k: (tuple(v) if k == "hidden_layer_sizes" else v) for k, v in r["params"].items()}
        te = holdout_eval(params, modelable, num_f, cat_f, seeds=(42, 7, 123))
        r["test_pr_auc"] = round(te["pr_auc"], 5)
        r["test_p10"] = round(te["precision_at_10pct"], 5)
        r["test_roc_auc"] = round(te["roc_auc"], 5)
        r["beats_incumbent_test"] = bool(
            te["pr_auc"] >= inc_test["pr_auc"]
            and te["precision_at_10pct"] >= inc_test["precision_at_10pct"]
        )
        confirmed.append(r)
        beat = "  <-- BEATS INCUMBENT ON TEST" if r["beats_incumbent_test"] else ""
        print(
            f"  {r['tag']:<30} CV_PR={r['cv_pr_auc']:.4f} "
            f"TEST pr_auc={r['test_pr_auc']:.4f} p10={r['test_p10']:.4f}{beat}"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUT_DIR / f"mlp_hpo_sweep_{stamp}.json"
    out.write_text(
        json.dumps(
            {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "cv_region": f"inspection_date < {VAL_END}",
                "fold_val_years": fold_years,
                "incumbent": {
                    "params": {
                        k: (list(v) if isinstance(v, tuple) else v) for k, v in INCUMBENT.items()
                    },
                    "cv": inc_cv,
                    "test": inc_test,
                },
                "n_candidates": len(results),
                "n_both_gate": len(passers),
                "confirmed_on_test": confirmed,
                "all_results": sorted(results, key=lambda r: r["cv_pr_auc"], reverse=True),
            },
            indent=2,
        )
    )
    print(f"\nWrote sweep log -> {out}")
    winners = [r for r in confirmed if r.get("beats_incumbent_test")]
    print(f"Winners that beat the incumbent on BOTH test metrics: {len(winners)}")
    for w in winners:
        print(f"  {w['tag']}: {w['params']}")


if __name__ == "__main__":
    main()
