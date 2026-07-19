"""XGBoost hyperparameter search for the production risk model.

Feature set is frozen at v36 ``ALL_FEATURES`` — this is pure HPO, no feature
changes (the feature well is at the documented information ceiling). The goal is
to beat the incumbent production XGB (depth-3 monotone: served test PR-AUC 0.382,
precision@10% 0.415) on the **both-metrics gate**, validated the way DR 0002
mandates: **expanding-window cross-validation**, not a single split.

Selection discipline:
  * The CV folds run on the TRAIN+VAL region only (inspection_date < 2025-07-01),
    so the 2025-07-01+ held-out TEST is never seen during search.
  * PR-AUC and precision@10% are rank metrics (calibration-invariant), so during
    search we score the raw XGB margin — no Platt fit needed. The final winner is
    calibrated + evaluated on the true test exactly like scripts/retrain_xgb_sigmoid.py.
  * A candidate must not regress EITHER metric vs the incumbent on the CV mean.

Run:
    PYTHONPATH=src FOODSAFETY_DATA_DIR=<data> \
        python scripts/run_xgb_hpo.py --stage all --n-random 80
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score

from foodsafety.config import FEATURES_PATH
from foodsafety.models.baseline import ALL_FEATURES, LABEL_COL
from foodsafety.models.evaluate import evaluate, precision_at_k
from foodsafety.models.xgb import (
    build_xgb_estimator,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    monotone_constraints_for,
    prepare_xgb_features,
)
from foodsafety.utils.time import expanding_year_folds, temporal_split

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "reports" / "metrics" / "xgb"
N_JOBS = int(os.environ.get("XGB_HPO_NJOBS", "4"))

TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"  # test = inspection_date >= VAL_END; CV lives strictly before it
SEED = 42

# The incumbent production config (build_production_xgb + build_xgb_estimator
# defaults). Every candidate is a delta off this dict; this dict is also the CV
# control so per-fold deltas are paired on identical folds.
INCUMBENT: dict = {
    "n_estimators": 300,
    "max_depth": 3,
    "learning_rate": 0.05,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "min_child_weight": 10.0,
    "reg_lambda": 1.0,
    "reg_alpha": 0.0,
    "gamma": 0.0,
    "max_delta_step": 0.0,
    "monotone": True,
    "spw_mode": "full",  # full = n_neg/n_pos; half = 0.5x; sqrt = sqrt(n_neg/n_pos)
}


# --------------------------------------------------------------------------- #
# Estimator construction
# --------------------------------------------------------------------------- #
def _spw(y: np.ndarray, mode: str) -> float:
    base = compute_scale_pos_weight(y)
    if mode == "full":
        return base
    if mode == "half":
        return 0.5 * base
    if mode == "sqrt":
        return float(np.sqrt(base))
    raise ValueError(f"bad spw_mode {mode!r}")


def build_est(params: dict, y_train: np.ndarray, feats: list[str]):
    p = {**INCUMBENT, **params}
    mono = monotone_constraints_for(feats) if p["monotone"] else None
    est = build_xgb_estimator(
        n_estimators=int(p["n_estimators"]),
        max_depth=int(p["max_depth"]),
        learning_rate=float(p["learning_rate"]),
        subsample=float(p["subsample"]),
        colsample_bytree=float(p["colsample_bytree"]),
        min_child_weight=float(p["min_child_weight"]),
        reg_lambda=float(p["reg_lambda"]),
        reg_alpha=float(p["reg_alpha"]),
        gamma=float(p["gamma"]),
        max_delta_step=float(p["max_delta_step"]),
        scale_pos_weight=_spw(y_train, p["spw_mode"]),
        early_stopping_rounds=None,
        random_state=SEED,
        monotone_constraints=mono,
    )
    est.set_params(n_jobs=N_JOBS)  # cap threads so a concurrent MLP session isn't starved
    return est


# --------------------------------------------------------------------------- #
# Data + folds
# --------------------------------------------------------------------------- #
def load_modelable() -> pd.DataFrame:
    feat = pd.read_parquet(FEATURES_PATH)
    if "right_truncated" in feat.columns:
        feat = feat.loc[~feat["right_truncated"]].reset_index(drop=True)
    return feat


def cv_score(params: dict, cv_df: pd.DataFrame, folds, feats: list[str]) -> dict:
    """Mean PR-AUC / P@10 over expanding-window folds, scoring the raw margin."""
    pr, p10 = [], []
    y_all = cv_df[LABEL_COL].astype(int).to_numpy()
    X_all = cv_df[feats]
    for tr_idx, va_idx in folds:
        Xtr = prepare_xgb_features(X_all.iloc[tr_idx])
        cat = extract_categorical_dtypes(Xtr)
        Xva = prepare_xgb_features(X_all.iloc[va_idx], categorical_dtypes=cat)
        ytr, yva = y_all[tr_idx], y_all[va_idx]
        est = build_est(params, ytr, feats)
        est.fit(Xtr, ytr, verbose=False)
        m = est.predict(Xva, output_margin=True)
        pr.append(float(average_precision_score(yva, m)))
        p10.append(float(precision_at_k(yva, m, 0.10)))
    return {
        "pr_auc_mean": float(np.mean(pr)),
        "p10_mean": float(np.mean(p10)),
        "pr_auc_folds": [round(x, 4) for x in pr],
        "p10_folds": [round(x, 4) for x in p10],
    }


def holdout_eval(params: dict, modelable: pd.DataFrame, feats: list[str]) -> dict:
    """Production protocol: fit on train, Platt-on-margin from val, eval on test."""
    sp = temporal_split(modelable, train_end=TRAIN_END, val_end=VAL_END)
    y_tr = sp.train[LABEL_COL].astype(int).to_numpy()
    y_va = sp.val[LABEL_COL].astype(int).to_numpy()
    y_te = sp.test[LABEL_COL].astype(int).to_numpy()
    Xtr = prepare_xgb_features(sp.train[feats])
    cat = extract_categorical_dtypes(Xtr)
    Xva = prepare_xgb_features(sp.val[feats], categorical_dtypes=cat)
    Xte = prepare_xgb_features(sp.test[feats], categorical_dtypes=cat)
    est = build_est(params, y_tr, feats)
    est.fit(Xtr, y_tr, verbose=False)
    m_va = est.predict(Xva, output_margin=True)
    platt = LogisticRegression(C=1e10, solver="lbfgs").fit(m_va.reshape(-1, 1), y_va)
    c, b = float(platt.coef_[0, 0]), float(platt.intercept_[0])
    p_te = expit(c * est.predict(Xte, output_margin=True) + b)
    return evaluate(y_te, p_te).to_dict()


# --------------------------------------------------------------------------- #
# Search spaces
# --------------------------------------------------------------------------- #
OFAT_GRID = {
    "max_depth": [2, 4, 5, 6],
    "learning_rate": [0.02, 0.03, 0.08, 0.1],
    "n_estimators": [150, 200, 500, 800],
    "min_child_weight": [1, 5, 20, 50],
    "reg_lambda": [0.5, 3.0, 10.0],
    "reg_alpha": [0.5, 2.0],
    "gamma": [0.5, 2.0],
    "subsample": [0.7, 1.0],
    "colsample_bytree": [0.7, 1.0],
    "max_delta_step": [1.0, 5.0],
    "spw_mode": ["half", "sqrt"],
    "monotone": [False],
}


def sample_random(rng: np.random.Generator) -> dict:
    return {
        "max_depth": int(rng.choice([2, 3, 3, 4, 4, 5])),
        "learning_rate": float(rng.choice([0.02, 0.03, 0.05, 0.05, 0.08, 0.1])),
        "n_estimators": int(rng.choice([150, 200, 300, 300, 500, 800])),
        "min_child_weight": float(rng.choice([1, 5, 10, 20, 50])),
        "reg_lambda": float(rng.choice([0.5, 1.0, 3.0, 10.0])),
        "reg_alpha": float(rng.choice([0.0, 0.0, 0.5, 2.0])),
        "gamma": float(rng.choice([0.0, 0.0, 0.5, 2.0])),
        "subsample": float(rng.choice([0.7, 0.85, 1.0])),
        "colsample_bytree": float(rng.choice([0.7, 0.85, 1.0])),
        "max_delta_step": float(rng.choice([0.0, 0.0, 1.0, 5.0])),
        "spw_mode": str(rng.choice(["full", "full", "half", "sqrt"])),
        "monotone": bool(rng.choice([True, True, False])),
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["reproduce", "ofat", "random", "all"])
    ap.add_argument("--n-random", type=int, default=80)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()

    feats = list(ALL_FEATURES)
    modelable = load_modelable()
    cv_df = modelable.loc[modelable["inspection_date"] < VAL_END].reset_index(drop=True)
    folds = expanding_year_folds(cv_df)
    fold_desc = [
        (
            pd.to_datetime(cv_df["inspection_date"].iloc[va]).dt.year.mode().iloc[0],
            len(tr),
            len(va),
        )
        for tr, va in folds
    ]
    print(f"CV region n={len(cv_df):,}  |  {len(folds)} folds (val_year, n_train, n_val):")
    for y, ntr, nva in fold_desc:
        print(f"    {int(y)}: train={ntr:,} val={nva:,}")

    t0 = time.time()
    inc_cv = cv_score(INCUMBENT, cv_df, folds, feats)
    inc_test = holdout_eval(INCUMBENT, modelable, feats)
    print(
        f"\nINCUMBENT  CV pr_auc={inc_cv['pr_auc_mean']:.4f} p10={inc_cv['p10_mean']:.4f}  "
        f"| TEST pr_auc={inc_test['pr_auc']:.4f} p10={inc_test['precision_at_10pct']:.4f}  "
        f"({time.time() - t0:.0f}s)"
    )
    print(f"    CV pr folds: {inc_cv['pr_auc_folds']}")
    print(f"    CV p10 folds: {inc_cv['p10_folds']}")

    results: list[dict] = []

    def run(tag: str, params: dict) -> dict:
        ts = time.time()
        cv = cv_score(params, cv_df, folds, feats)
        d_pr = cv["pr_auc_mean"] - inc_cv["pr_auc_mean"]
        d_p10 = cv["p10_mean"] - inc_cv["p10_mean"]
        pr_wins = sum(
            a > b for a, b in zip(cv["pr_auc_folds"], inc_cv["pr_auc_folds"], strict=True)
        )
        p10_wins = sum(a > b for a, b in zip(cv["p10_folds"], inc_cv["p10_folds"], strict=True))
        rec = {
            "tag": tag,
            "params": params,
            "cv_pr_auc": round(cv["pr_auc_mean"], 5),
            "cv_p10": round(cv["p10_mean"], 5),
            "d_pr": round(d_pr, 5),
            "d_p10": round(d_p10, 5),
            "pr_wins": f"{pr_wins}/{len(folds)}",
            "p10_wins": f"{p10_wins}/{len(folds)}",
            "both_gate": bool(d_pr >= 0 and d_p10 >= 0),
            "pr_folds": cv["pr_auc_folds"],
            "p10_folds": cv["p10_folds"],
        }
        results.append(rec)
        flag = "  <-- BOTH-GATE PASS" if rec["both_gate"] else ""
        print(
            f"  {tag:<28} dPR={d_pr:+.4f} dP10={d_p10:+.4f} "
            f"(pr {pr_wins}/{len(folds)}, p10 {p10_wins}/{len(folds)}) {time.time() - ts:.0f}s{flag}"
        )
        return rec

    if args.stage in ("ofat", "all"):
        print("\n=== Stage A: one-factor-at-a-time (CV) ===")
        for knob, vals in OFAT_GRID.items():
            for v in vals:
                run(f"{knob}={v}", {knob: v})

    if args.stage in ("random", "all"):
        print(f"\n=== Stage B: randomized search x{args.n_random} (CV) ===")
        rng = np.random.default_rng(args.seed)
        for i in range(args.n_random):
            run(f"rand{i:03d}", sample_random(rng))

    # rank the both-gate passers by CV PR-AUC, then confirm top-K on the true test
    passers = sorted(
        [r for r in results if r["both_gate"]], key=lambda r: r["cv_pr_auc"], reverse=True
    )
    print(f"\n=== both-gate passers: {len(passers)}/{len(results)} ; confirming top-6 on TEST ===")
    confirmed: list[dict] = []
    for r in passers[:6]:
        te = holdout_eval(r["params"], modelable, feats)
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
            f"  {r['tag']:<28} CV_PR={r['cv_pr_auc']:.4f}  "
            f"TEST pr_auc={r['test_pr_auc']:.4f} p10={r['test_p10']:.4f} roc={r['test_roc_auc']:.4f}{beat}"
        )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = OUT_DIR / f"xgb_hpo_sweep_{stamp}.json"
    payload = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "n_features": len(feats),
        "cv_region": f"inspection_date < {VAL_END}",
        "folds": [{"val_year": int(y), "n_train": ntr, "n_val": nva} for y, ntr, nva in fold_desc],
        "incumbent": {"params": INCUMBENT, "cv": inc_cv, "test": inc_test},
        "n_candidates": len(results),
        "n_both_gate": len(passers),
        "confirmed_on_test": confirmed,
        "all_results": sorted(results, key=lambda r: r["cv_pr_auc"], reverse=True),
    }
    out.write_text(json.dumps(payload, indent=2))
    print(f"\nWrote sweep log -> {out}")
    winners = [r for r in confirmed if r.get("beats_incumbent_test")]
    print(f"Winners that beat the incumbent on BOTH test metrics: {len(winners)}")
    for w in winners:
        print(f"  {w['tag']}: {w['params']}")


if __name__ == "__main__":
    main()
