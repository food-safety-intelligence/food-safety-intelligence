"""Hyperparameter sweep for the production XGBoost model.

Searches four regularisation knobs that have never been systematically swept
(min_child_weight, reg_lambda, subsample, colsample_bytree) while holding
the DR 0009-validated fixed params constant (max_depth=3, lr=0.05,
n_estimators=300, monotone risk constraints).

Protocol (mirrors the gate in docs/model-experiments.md):
  1. Screen all combos on the single canonical train→val split (fast ranking).
  2. Validate the top-5 with 3-fold expanding-window CV on TRAIN-only.
     (Most-recent 3 folds are most representative of the test distribution.)
  3. Pick the CV winner and evaluate it on the held-out test set.
  4. Compare both metrics against the production baseline.

Run with the project Python:
    PYTHONPATH=src uv run python scripts/xgb_hyperparam_sweep.py
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from foodsafety.config import FEATURES_PATH, LABEL_WINDOW_DAYS, PROCESSED_DIR, RANDOM_STATE
from foodsafety.io import storage
from foodsafety.models.baseline import ALL_FEATURES, LABEL_COL
from foodsafety.models.evaluate import evaluate
from foodsafety.models.xgb import (
    build_xgb_estimator,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    monotone_constraints_for,
    prepare_xgb_features,
)
from foodsafety.utils.time import expanding_year_folds, temporal_split

# Resolve the features file: prefer the versioned path from config; fall back to
# the legacy flat path (data/processed/features.parquet) if not yet migrated.
_FEATURES_FALLBACK = Path(str(PROCESSED_DIR)) / "features.parquet"
_RESOLVED_FEATURES_PATH = (
    str(FEATURES_PATH) if storage.exists(FEATURES_PATH) else str(_FEATURES_FALLBACK)
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports" / "metrics" / "experiments"

TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"

# Production baseline from xgb_monotone_sigmoid_20260627_ac236faed.json
PROD_TEST_PR_AUC = 0.382016
PROD_TEST_P10 = 0.415121
PROD_TEST_ROC_AUC = 0.805789

# ---------------------------------------------------------------------------
# Hyperparameter grid
# Fixed (DR 0009-validated): max_depth=3, lr=0.05, n_estimators=300, monotone.
# These four are the regularisation knobs never systematically swept.
# ---------------------------------------------------------------------------
PARAM_GRID: dict[str, list] = {
    "min_child_weight": [5, 10, 30],  # current default: 10
    "reg_lambda": [0.5, 1.0, 5.0],  # current default: 1.0
    "subsample": [0.75, 0.85, 0.9],  # current default: 0.85
    "colsample_bytree": [0.75, 0.85, 0.9],  # current default: 0.85
}

_MONOTONE = monotone_constraints_for(list(ALL_FEATURES))


def _build(params: dict, spw: float):
    return build_xgb_estimator(
        n_estimators=300,
        max_depth=3,
        learning_rate=0.05,
        scale_pos_weight=spw,
        early_stopping_rounds=None,
        monotone_constraints=_MONOTONE,
        **params,
    )


def _single_split_pr_auc(params, X_tr, y_tr, X_vl, y_vl, spw) -> float:
    est = _build(params, spw)
    est.fit(X_tr, y_tr, verbose=False)
    p = est.predict_proba(X_vl)[:, 1]
    return float(evaluate(y_vl, p).pr_auc)


def _cv_pr_auc(
    df,
    params: dict,
    folds: list[tuple[np.ndarray, np.ndarray]],
) -> float:
    """Mean PR-AUC over expanding-window folds on a single DataFrame."""
    scores = []
    for train_idx, val_idx in folds:
        fold_tr = df.iloc[train_idx].reset_index(drop=True)
        fold_vl = df.iloc[val_idx].reset_index(drop=True)
        y_tr = fold_tr[LABEL_COL].astype(int).to_numpy()
        y_vl = fold_vl[LABEL_COL].astype(int).to_numpy()
        if y_tr.sum() == 0 or y_vl.sum() == 0:
            continue
        spw = compute_scale_pos_weight(y_tr)
        est = _build(params, spw)
        X_tr = prepare_xgb_features(fold_tr[ALL_FEATURES])
        cat_dt = extract_categorical_dtypes(X_tr)
        X_vl = prepare_xgb_features(fold_vl[ALL_FEATURES], categorical_dtypes=cat_dt)
        est.fit(X_tr, y_tr, verbose=False)
        p = est.predict_proba(X_vl)[:, 1]
        scores.append(evaluate(y_vl, p).pr_auc)
    return float(np.mean(scores)) if scores else 0.0


def main() -> None:
    print(f"Loading {_RESOLVED_FEATURES_PATH}")
    features = storage.read_parquet(_RESOLVED_FEATURES_PATH)
    print(f"  shape: {features.shape}")

    if "right_truncated" in features.columns:
        n_before = len(features)
        features = features.loc[~features["right_truncated"]].reset_index(drop=True)
        print(f"  dropped {n_before - len(features):,} right-truncated rows → {len(features):,}")

    split = temporal_split(features, train_end=TRAIN_END, val_end=VAL_END)
    print(f"  train={len(split.train):,}  val={len(split.val):,}  test={len(split.test):,}")

    y_train = split.train[LABEL_COL].astype(int).to_numpy()
    y_val = split.val[LABEL_COL].astype(int).to_numpy()
    y_test = split.test[LABEL_COL].astype(int).to_numpy()

    X_train = prepare_xgb_features(split.train[ALL_FEATURES])
    cat_dtypes = extract_categorical_dtypes(X_train)
    X_val = prepare_xgb_features(split.val[ALL_FEATURES], categorical_dtypes=cat_dtypes)
    X_test = prepare_xgb_features(split.test[ALL_FEATURES], categorical_dtypes=cat_dtypes)

    spw = compute_scale_pos_weight(y_train)

    # ------------------------------------------------------------------
    # Pass 1: screen all combos on the single train→val split
    # ------------------------------------------------------------------
    keys = list(PARAM_GRID.keys())
    combos = [dict(zip(keys, v, strict=False)) for v in itertools.product(*PARAM_GRID.values())]
    n_combos = len(combos)
    print(f"\n--- Pass 1: single-split screen ({n_combos} combos) ---")

    grid_results = []
    for i, params in enumerate(combos, 1):
        val_pr_auc = _single_split_pr_auc(params, X_train, y_train, X_val, y_val, spw)
        grid_results.append({"params": params, "val_pr_auc": val_pr_auc})
        if i % 20 == 0 or i == n_combos:
            best_so_far = max(grid_results, key=lambda r: r["val_pr_auc"])
            print(
                f"  {i:3d}/{n_combos}  "
                f"this={val_pr_auc:.4f}  "
                f"best_so_far={best_so_far['val_pr_auc']:.4f}"
            )

    grid_results.sort(key=lambda r: r["val_pr_auc"], reverse=True)
    print("\nTop-5 by val PR-AUC:")
    for r in grid_results[:5]:
        print(f"  {r['params']}  →  val PR-AUC={r['val_pr_auc']:.4f}")

    # ------------------------------------------------------------------
    # Pass 2: validate top-5 with 3-fold expanding-window CV on train-only
    # ------------------------------------------------------------------
    all_folds = expanding_year_folds(split.train.reset_index(drop=True))
    # Use the 3 most-recent folds — most representative of the test distribution.
    recent_folds = all_folds[-3:] if len(all_folds) >= 3 else all_folds
    print(f"\n--- Pass 2: {len(recent_folds)}-fold CV on train-only (top-5 candidates) ---")

    cv_results = []
    train_df = split.train.reset_index(drop=True)
    for r in grid_results[:5]:
        mean_pr = _cv_pr_auc(train_df, r["params"], recent_folds)
        cv_results.append({**r, "cv_pr_auc": mean_pr})
        print(f"  {r['params']}  →  CV PR-AUC={mean_pr:.4f}")

    cv_results.sort(key=lambda r: r["cv_pr_auc"], reverse=True)
    best = cv_results[0]
    print(f"\nCV winner: {best['params']}  (CV PR-AUC={best['cv_pr_auc']:.4f})")

    # ------------------------------------------------------------------
    # Pass 3: train winner on full train, evaluate on held-out test
    # ------------------------------------------------------------------
    print("\n--- Pass 3: train winner on full train → test ---")
    est_final = _build(best["params"], spw)
    est_final.fit(X_train, y_train, verbose=False)
    p_test = est_final.predict_proba(X_test)[:, 1]
    test_metrics = evaluate(y_test, p_test)

    # Also run production-config (current default params) for a clean same-run A/B
    prod_params = {
        "min_child_weight": 10,
        "reg_lambda": 1.0,
        "subsample": 0.85,
        "colsample_bytree": 0.85,
    }
    est_prod = _build(prod_params, spw)
    est_prod.fit(X_train, y_train, verbose=False)
    p_test_prod = est_prod.predict_proba(X_test)[:, 1]
    prod_metrics = evaluate(y_test, p_test_prod)

    print("\n=== A/B vs same-run production config ===")
    print("                  PR-AUC    P@10     ROC-AUC  Lift@10")
    print(
        f"  Prod config:   {prod_metrics.pr_auc:.4f}   "
        f"{prod_metrics.precision_at_10pct:.4f}   "
        f"{prod_metrics.roc_auc:.4f}   "
        f"{prod_metrics.top_decile_lift:.3f}"
    )
    print(
        f"  Best HP:       {test_metrics.pr_auc:.4f}   "
        f"{test_metrics.precision_at_10pct:.4f}   "
        f"{test_metrics.roc_auc:.4f}   "
        f"{test_metrics.top_decile_lift:.3f}"
    )
    delta_pr = test_metrics.pr_auc - prod_metrics.pr_auc
    delta_p10 = test_metrics.precision_at_10pct - prod_metrics.precision_at_10pct
    print(f"  Delta:         {delta_pr:+.4f}   {delta_p10:+.4f}")

    print("\n=== vs stored production baseline (xgb_20260627) ===")
    print("                  PR-AUC    P@10     ROC-AUC")
    print(
        f"  Stored prod:   {PROD_TEST_PR_AUC:.4f}   {PROD_TEST_P10:.4f}   {PROD_TEST_ROC_AUC:.4f}"
    )
    print(
        f"  Best HP:       {test_metrics.pr_auc:.4f}   "
        f"{test_metrics.precision_at_10pct:.4f}   "
        f"{test_metrics.roc_auc:.4f}"
    )
    print(
        f"  Delta:         {test_metrics.pr_auc - PROD_TEST_PR_AUC:+.4f}   "
        f"{test_metrics.precision_at_10pct - PROD_TEST_P10:+.4f}"
    )

    beats_pr = test_metrics.pr_auc > prod_metrics.pr_auc
    beats_p10 = test_metrics.precision_at_10pct > prod_metrics.precision_at_10pct
    print(
        f"\nBoth-metrics gate (vs same-run control): "
        f"{'PASS' if beats_pr and beats_p10 else 'FAIL'}  "
        f"(PR-AUC {'↑' if beats_pr else '↓'}, P@10 {'↑' if beats_p10 else '↓'})"
    )

    # ------------------------------------------------------------------
    # Save experiment report
    # ------------------------------------------------------------------
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "experiment": "xgb_hyperparam_sweep",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "label_window_days": LABEL_WINDOW_DAYS,
        "random_state": RANDOM_STATE,
        "train_end": TRAIN_END,
        "val_end": VAL_END,
        "n_combos": n_combos,
        "cv_folds_used": len(recent_folds),
        "param_grid": {k: list(v) for k, v in PARAM_GRID.items()},
        "production_baseline_stored": {
            "test_pr_auc": PROD_TEST_PR_AUC,
            "test_p10": PROD_TEST_P10,
            "test_roc_auc": PROD_TEST_ROC_AUC,
        },
        "best_params": best["params"],
        "best_val_pr_auc": round(best["val_pr_auc"], 6),
        "best_cv_pr_auc": round(best["cv_pr_auc"], 6),
        "same_run_control": prod_metrics.to_dict(),
        "test": test_metrics.to_dict(),
        "delta_vs_same_run_control": {
            "pr_auc": round(test_metrics.pr_auc - prod_metrics.pr_auc, 6),
            "precision_at_10pct": round(
                test_metrics.precision_at_10pct - prod_metrics.precision_at_10pct, 6
            ),
        },
        "top5_val_grid": [
            {"params": r["params"], "val_pr_auc": round(r["val_pr_auc"], 6)}
            for r in grid_results[:5]
        ],
        "top5_cv": [
            {
                "params": r["params"],
                "val_pr_auc": round(r["val_pr_auc"], 6),
                "cv_pr_auc": round(r["cv_pr_auc"], 6),
            }
            for r in cv_results
        ],
    }
    report_path = REPORTS_DIR / f"xgb_hyperparam_sweep_{ts}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved report → {report_path}")


if __name__ == "__main__":
    main()
