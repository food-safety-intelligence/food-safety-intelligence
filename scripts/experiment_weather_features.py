"""A/B experiment: citywide NOAA weather features.

Trains two XGBoost models on the same temporal split:
  A (control):   ALL_FEATURES (current production set)
  B (treatment): ALL_FEATURES + WEATHER_FEATURES

Reports val/test metrics side-by-side (PR-AUC, precision@10%, ROC-AUC) and the
delta, plus expanding-window CV — same protocol as
``experiment_building_features.py``, the precedent this mirrors. Tests whether
actual daily weather carries incremental signal over the existing
``temporal_month`` / ``temporal_quarter`` seasonality proxies (see
``docs/data_dictionary.md`` § NOAA weather).

Prerequisites:
  - raw weather pulled:      scripts/ingest_raw.py weather
  - features parquet built WITH --with-weather:
      PYTHONPATH=src uv run python scripts/build_features.py --with-weather \\
          --out data/processed/features/features_with_weather.parquet

Run:
    PYTHONPATH=src uv run python scripts/experiment_weather_features.py \\
        --features data/processed/features/features_with_weather.parquet
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from foodsafety.config import FEATURES_PATH
from foodsafety.io import storage
from foodsafety.models.baseline import (
    ALL_FEATURES,
    LABEL_COL,
    WEATHER_FEATURES,
)
from foodsafety.models.evaluate import evaluate
from foodsafety.models.xgb import (
    build_production_xgb,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    prepare_xgb_features,
)
from foodsafety.utils.time import expanding_year_folds, temporal_split

TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _train_and_eval(
    features_list: list[str],
    split,
    label: str,
) -> dict:
    """Train XGB on the given feature set and return val+test metrics."""
    y_train = split.train[LABEL_COL].astype(int).to_numpy()
    y_val = split.val[LABEL_COL].astype(int).to_numpy()
    y_test = split.test[LABEL_COL].astype(int).to_numpy()

    X_train = prepare_xgb_features(split.train[features_list])
    cat_dtypes = extract_categorical_dtypes(X_train)
    X_val = prepare_xgb_features(split.val[features_list], categorical_dtypes=cat_dtypes)
    X_test = prepare_xgb_features(split.test[features_list], categorical_dtypes=cat_dtypes)

    spw = compute_scale_pos_weight(y_train)
    xgb = build_production_xgb(scale_pos_weight=spw, features=features_list)
    xgb.fit(X_train, y_train, verbose=False)

    p_val = xgb.predict_proba(X_val)[:, 1]
    p_test = xgb.predict_proba(X_test)[:, 1]

    val_m = evaluate(y_val, p_val).to_dict()
    test_m = evaluate(y_test, p_test).to_dict()
    print(
        f"\n  [{label}] Val:  PR-AUC={val_m['pr_auc']:.4f}  P@10={val_m['precision_at_10pct']:.4f}  ROC-AUC={val_m['roc_auc']:.4f}"
    )
    print(
        f"  [{label}] Test: PR-AUC={test_m['pr_auc']:.4f}  P@10={test_m['precision_at_10pct']:.4f}  ROC-AUC={test_m['roc_auc']:.4f}"
    )
    return {"val": val_m, "test": test_m}


def _cv_prauc(features_list: list[str], train_df: pd.DataFrame, label: str) -> list[float]:
    """Run expanding-window CV on train and return per-fold PR-AUC."""
    folds = expanding_year_folds(train_df)
    praucs = []
    for i, (tr_idx, va_idx) in enumerate(folds):
        y_tr = train_df.iloc[tr_idx][LABEL_COL].astype(int).to_numpy()
        y_va = train_df.iloc[va_idx][LABEL_COL].astype(int).to_numpy()
        X_tr = prepare_xgb_features(train_df.iloc[tr_idx][features_list])
        cat_dtypes = extract_categorical_dtypes(X_tr)
        X_va = prepare_xgb_features(
            train_df.iloc[va_idx][features_list], categorical_dtypes=cat_dtypes
        )
        spw = compute_scale_pos_weight(y_tr)
        xgb = build_production_xgb(scale_pos_weight=spw, features=features_list)
        xgb.fit(X_tr, y_tr, verbose=False)
        p_va = xgb.predict_proba(X_va)[:, 1]
        prauc = (
            float(np.mean(y_va > 0)) if len(np.unique(y_va)) < 2 else evaluate(y_va, p_va).pr_auc
        )
        praucs.append(prauc)
        print(
            f"    [{label}] fold {i + 1}/{len(folds)}: PR-AUC={prauc:.4f} (train={len(tr_idx):,}, val={len(va_idx):,})"
        )
    return praucs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--features",
        default=str(FEATURES_PATH),
        help="path to features parquet (must include weather columns for treatment arm)",
    )
    ap.add_argument("--skip-cv", action="store_true", help="skip expanding-window CV (faster)")
    args = ap.parse_args()

    print(f"Loading features from {args.features}")
    features = storage.read_parquet(args.features)
    print(f"  shape: {features.shape}")

    missing_weather = [c for c in WEATHER_FEATURES if c not in features.columns]
    if missing_weather:
        raise SystemExit(
            f"Missing {len(missing_weather)} weather columns: {missing_weather}. "
            "Rebuild with: scripts/build_features.py --with-weather"
        )

    if "right_truncated" in features.columns:
        features = features.loc[~features["right_truncated"]].reset_index(drop=True)

    split = temporal_split(features, train_end=TRAIN_END, val_end=VAL_END)
    print(f"  train={len(split.train):,}  val={len(split.val):,}  test={len(split.test):,}")

    # --- A/B on held-out split ---
    features_a = ALL_FEATURES
    features_b = ALL_FEATURES + WEATHER_FEATURES

    print("\n=== A (control): ALL_FEATURES ===")
    metrics_a = _train_and_eval(features_a, split, "A")

    print("\n=== B (treatment): ALL_FEATURES + WEATHER_FEATURES ===")
    metrics_b = _train_and_eval(features_b, split, "B")

    # --- Delta ---
    print("\n=== DELTA (B - A) ===")
    for subset in ("val", "test"):
        for metric in ("pr_auc", "precision_at_10pct", "roc_auc"):
            delta = metrics_b[subset][metric] - metrics_a[subset][metric]
            print(f"  {subset} {metric}: {delta:+.4f}")

    # --- Expanding-window CV ---
    if not args.skip_cv:
        print("\n=== Expanding-window CV (train only) ===")
        cv_a = _cv_prauc(features_a, split.train, "A")
        cv_b = _cv_prauc(features_b, split.train, "B")
        print(
            f"\n  CV PR-AUC mean: A={np.mean(cv_a):.4f}  B={np.mean(cv_b):.4f}  delta={np.mean(cv_b) - np.mean(cv_a):+.4f}"
        )
        print(f"  CV PR-AUC std:  A={np.std(cv_a):.4f}  B={np.std(cv_b):.4f}")
        wins = sum(1 for a, b in zip(cv_a, cv_b, strict=True) if b > a)
        print(f"  Folds where B > A: {wins}/{len(cv_a)}")

    # --- Save report ---
    report = {
        "experiment": "weather_features",
        "features_a": "ALL_FEATURES",
        "features_b": "ALL_FEATURES + WEATHER_FEATURES",
        "n_weather_features": len(WEATHER_FEATURES),
        "weather_features": WEATHER_FEATURES,
        "metrics_a": metrics_a,
        "metrics_b": metrics_b,
    }
    report_dir = REPO_ROOT / "reports" / "metrics"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "experiment_weather_features.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved report -> {report_path}")


if __name__ == "__main__":
    main()
