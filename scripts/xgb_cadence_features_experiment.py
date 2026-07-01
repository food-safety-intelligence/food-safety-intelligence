"""Inspection-cadence drift features — A/B experiment.

Tests two new features derived from already-computed columns (no pipeline
rebuild required):

  cadence_ratio   = days_since_last_inspection * prior_inspections / license_age_days
      Measures how "overdue" the current inspection is relative to this
      establishment's own historical rhythm. >1 = overdue; <1 = early.
      NaN when prior_inspections==0 (first inspection) or license_age_days
      is missing/zero — XGBoost handles NaN natively.

  inspection_rate = prior_inspections / license_age_days
      Inspections-per-day density over the license's lifetime. Proxies
      the inspection cadence tier: Risk-1 venues get inspected ~3×/year,
      Risk-3 ~1×/year; complaint-driven venues accumulate extra visits.
      NaN on first inspection or missing license age.

Both are leak-free: they are ratios of prior_* counts and license_age_days,
all of which are computed from information strictly before the anchor date.

Protocol (same gate as docs/model-experiments.md):
  1. Single train→val split — A/B control vs +2 cadence features.
  2. Top candidate validated on 3-fold expanding-window CV (train-only).
  3. Final evaluation on held-out test vs same-run control.
  4. Both-metrics gate: must beat control on BOTH PR-AUC AND P@10.

Run with:
    PYTHONPATH=src uv run python scripts/xgb_cadence_features_experiment.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

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

# Resolve features file — falls back to legacy flat path if versioned not present yet.
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

# New feature names
CADENCE_FEATURES = ["cadence_ratio", "inspection_rate"]
ALL_FEATURES_WITH_CADENCE = list(ALL_FEATURES) + CADENCE_FEATURES


def add_cadence_features(df: pd.DataFrame) -> pd.DataFrame:
    """Append cadence_ratio and inspection_rate to a features DataFrame.

    Both are ratios of already-computed leak-free columns. NaN when the
    denominator is zero or missing (first inspection, missing license age).
    """
    out = df.copy()
    days = pd.to_numeric(out["days_since_last_inspection"], errors="coerce")
    n_prior = pd.to_numeric(out["prior_inspections"], errors="coerce")
    age = pd.to_numeric(out["license_age_days"], errors="coerce")

    # Guard against division by zero — replace 0 with NaN so the ratio is NaN
    # ("undefined") rather than inf, which XGBoost cannot handle.
    safe_age = age.where(age > 0, np.nan)

    # cadence_ratio: how many "expected gaps" the current gap represents.
    # Expected gap = license_age_days / prior_inspections (average inter-inspection
    # interval). Ratio = days_since_last / expected_gap
    #               = days_since_last * prior_inspections / license_age_days.
    # > 1 means this inspection arrived later than the historical average.
    out["cadence_ratio"] = (days * n_prior / safe_age).astype("float32")

    # inspection_rate: prior inspections per day of license lifetime.
    # High = frequently inspected (Risk 1, complaint-driven); low = rarely inspected.
    out["inspection_rate"] = (n_prior / safe_age).astype("float32")

    return out


def _build_xgb(features: list[str], spw: float):
    """Production recipe with monotone constraints built over the given feature set."""
    return build_xgb_estimator(
        n_estimators=300,
        max_depth=3,
        learning_rate=0.05,
        scale_pos_weight=spw,
        early_stopping_rounds=None,
        monotone_constraints=monotone_constraints_for(features),
    )


def _fit_eval(features: list[str], X_tr, y_tr, X_ev, y_ev, spw: float) -> float:
    """Fit on train, return PR-AUC on eval."""
    est = _build_xgb(features, spw)
    est.fit(X_tr, y_tr, verbose=False)
    p = est.predict_proba(X_ev)[:, 1]
    return float(evaluate(y_ev, p).pr_auc), est


def _prepare(df: pd.DataFrame, features: list[str], cat_dtypes: dict | None = None):
    """Prepare XGBoost-ready matrix for the given feature list."""
    from foodsafety.models.baseline import BOOLEAN_FEATURES, CATEGORICAL_FEATURES

    # Identify which of the requested features fall into each dtype bucket.
    # New cadence features are numeric floats.
    cat_cols = [c for c in features if c in CATEGORICAL_FEATURES]
    bool_cols = [c for c in features if c in BOOLEAN_FEATURES]
    num_cols = [c for c in features if c not in cat_cols and c not in bool_cols]

    out = df[features].copy()
    for c in cat_cols:
        if cat_dtypes and c in cat_dtypes:
            out[c] = out[c].astype("category").cat.set_categories(cat_dtypes[c].categories)
        else:
            out[c] = out[c].astype("category")
    for c in bool_cols:
        out[c] = out[c].astype("int8")
    for c in num_cols:
        out[c] = out[c].astype("float32")
    return out


def _cv_pr_auc(df: pd.DataFrame, features: list[str], folds) -> list[float]:
    """Per-fold PR-AUC over expanding-window folds."""
    scores = []
    for train_idx, val_idx in folds:
        fold_tr = df.iloc[train_idx].reset_index(drop=True)
        fold_vl = df.iloc[val_idx].reset_index(drop=True)
        y_tr = fold_tr[LABEL_COL].astype(int).to_numpy()
        y_vl = fold_vl[LABEL_COL].astype(int).to_numpy()
        if y_tr.sum() == 0 or y_vl.sum() == 0:
            continue
        spw = compute_scale_pos_weight(y_tr)
        X_tr = _prepare(fold_tr, features)
        cat_dt = {c: X_tr[c].dtype for c in features if hasattr(X_tr[c], "cat")}
        X_vl = _prepare(fold_vl, features, cat_dt)
        est = _build_xgb(features, spw)
        est.fit(X_tr, y_tr, verbose=False)
        p = est.predict_proba(X_vl)[:, 1]
        scores.append(evaluate(y_vl, p).pr_auc)
    return scores


def main() -> None:
    print(f"Loading {_RESOLVED_FEATURES_PATH}")
    raw = storage.read_parquet(_RESOLVED_FEATURES_PATH)
    print(f"  shape: {raw.shape}")

    if "right_truncated" in raw.columns:
        n_before = len(raw)
        raw = raw.loc[~raw["right_truncated"]].reset_index(drop=True)
        print(f"  dropped {n_before - len(raw):,} right-truncated rows → {len(raw):,}")

    # Compute cadence features from existing columns (no pipeline rebuild).
    features_df = add_cadence_features(raw)

    split = temporal_split(features_df, train_end=TRAIN_END, val_end=VAL_END)
    print(f"  train={len(split.train):,}  val={len(split.val):,}  test={len(split.test):,}")

    # Quick univariate check — do the new features separate risk?
    print("\n--- Univariate sanity check ---")
    for feat in CADENCE_FEATURES:
        col = split.train[feat]
        label = split.train[LABEL_COL]
        pos_median = col[label == 1].median()
        neg_median = col[label == 0].median()
        pct_nan = col.isna().mean() * 100
        print(
            f"  {feat}: pos_median={pos_median:.3f}  neg_median={neg_median:.3f}"
            f"  ratio={pos_median / neg_median:.2f}x  NaN={pct_nan:.1f}%"
        )

    y_train = split.train[LABEL_COL].astype(int).to_numpy()
    y_val = split.val[LABEL_COL].astype(int).to_numpy()
    y_test = split.test[LABEL_COL].astype(int).to_numpy()
    spw = compute_scale_pos_weight(y_train)

    # ---------------------------------------------------------------
    # Pass 1: single train→val split A/B
    # ---------------------------------------------------------------
    print("\n--- Pass 1: single train→val A/B ---")

    # Control: current production features
    X_tr_ctrl = prepare_xgb_features(split.train[ALL_FEATURES])
    cat_dtypes_ctrl = extract_categorical_dtypes(X_tr_ctrl)
    X_val_ctrl = prepare_xgb_features(split.val[ALL_FEATURES], categorical_dtypes=cat_dtypes_ctrl)
    X_test_ctrl = prepare_xgb_features(split.test[ALL_FEATURES], categorical_dtypes=cat_dtypes_ctrl)

    est_ctrl = _build_xgb(list(ALL_FEATURES), spw)
    est_ctrl.fit(X_tr_ctrl, y_train, verbose=False)
    p_val_ctrl = est_ctrl.predict_proba(X_val_ctrl)[:, 1]
    val_ctrl = evaluate(y_val, p_val_ctrl)
    print(f"  Control  — val PR-AUC={val_ctrl.pr_auc:.4f}  P@10={val_ctrl.precision_at_10pct:.4f}")

    # Candidate: + cadence features
    X_tr_cand = _prepare(split.train, ALL_FEATURES_WITH_CADENCE)
    cat_dtypes_cand = {
        c: X_tr_cand[c].dtype for c in ALL_FEATURES_WITH_CADENCE if hasattr(X_tr_cand[c], "cat")
    }
    X_val_cand = _prepare(split.val, ALL_FEATURES_WITH_CADENCE, cat_dtypes_cand)
    X_test_cand = _prepare(split.test, ALL_FEATURES_WITH_CADENCE, cat_dtypes_cand)

    est_cand = _build_xgb(ALL_FEATURES_WITH_CADENCE, spw)
    est_cand.fit(X_tr_cand, y_train, verbose=False)
    p_val_cand = est_cand.predict_proba(X_val_cand)[:, 1]
    val_cand = evaluate(y_val, p_val_cand)
    print(f"  Candidate — val PR-AUC={val_cand.pr_auc:.4f}  P@10={val_cand.precision_at_10pct:.4f}")
    print(
        f"  Delta     — val ΔPR-AUC={val_cand.pr_auc - val_ctrl.pr_auc:+.4f}"
        f"  ΔP@10={val_cand.precision_at_10pct - val_ctrl.precision_at_10pct:+.4f}"
    )

    # ---------------------------------------------------------------
    # Pass 2: 3-fold CV on train-only — control vs candidate
    # ---------------------------------------------------------------
    all_folds = expanding_year_folds(split.train.reset_index(drop=True))
    recent_folds = all_folds[-3:] if len(all_folds) >= 3 else all_folds
    print(f"\n--- Pass 2: {len(recent_folds)}-fold CV on train-only ---")

    train_df = split.train.reset_index(drop=True)
    cv_ctrl = _cv_pr_auc(train_df, list(ALL_FEATURES), recent_folds)
    cv_cand = _cv_pr_auc(train_df, ALL_FEATURES_WITH_CADENCE, recent_folds)

    print(
        f"  Control   per-fold PR-AUC: {[round(s, 4) for s in cv_ctrl]}  mean={np.mean(cv_ctrl):.4f}"
    )
    print(
        f"  Candidate per-fold PR-AUC: {[round(s, 4) for s in cv_cand]}  mean={np.mean(cv_cand):.4f}"
    )
    cv_deltas = [c - b for c, b in zip(cv_cand, cv_ctrl, strict=True)]
    print(
        f"  Per-fold  Δ:               {[round(d, 4) for d in cv_deltas]}  mean={np.mean(cv_deltas):+.4f}"
    )
    cv_wins = sum(d > 0 for d in cv_deltas)
    print(f"  Candidate wins {cv_wins}/{len(recent_folds)} folds on PR-AUC")

    # ---------------------------------------------------------------
    # Pass 3: test set evaluation
    # ---------------------------------------------------------------
    print("\n--- Pass 3: test evaluation ---")
    p_test_ctrl = est_ctrl.predict_proba(X_test_ctrl)[:, 1]
    p_test_cand = est_cand.predict_proba(X_test_cand)[:, 1]
    test_ctrl = evaluate(y_test, p_test_ctrl)
    test_cand = evaluate(y_test, p_test_cand)

    print(f"\n=== A/B vs same-run control (test n={len(y_test):,}, base={y_test.mean():.3f}) ===")
    print("                  PR-AUC    P@10     ROC-AUC  Lift@10")
    print(
        f"  Control:       {test_ctrl.pr_auc:.4f}   "
        f"{test_ctrl.precision_at_10pct:.4f}   "
        f"{test_ctrl.roc_auc:.4f}   "
        f"{test_ctrl.top_decile_lift:.3f}"
    )
    print(
        f"  +cadence:      {test_cand.pr_auc:.4f}   "
        f"{test_cand.precision_at_10pct:.4f}   "
        f"{test_cand.roc_auc:.4f}   "
        f"{test_cand.top_decile_lift:.3f}"
    )
    delta_pr = test_cand.pr_auc - test_ctrl.pr_auc
    delta_p10 = test_cand.precision_at_10pct - test_ctrl.precision_at_10pct
    print(f"  Delta:         {delta_pr:+.4f}   {delta_p10:+.4f}")

    beats_pr = delta_pr > 0
    beats_p10 = delta_p10 > 0
    gate = "PASS" if beats_pr and beats_p10 else "FAIL"
    print(
        f"\nBoth-metrics gate: {gate}  "
        f"(PR-AUC {'↑' if beats_pr else '↓'}, P@10 {'↑' if beats_p10 else '↓'})"
    )

    # XGBoost feature importance for the new columns (gain-based)
    booster = est_cand.get_booster()
    gain = booster.get_score(importance_type="gain")
    print("\nFeature gain for cadence features (vs top-5 overall):")
    gain_sorted = sorted(gain.items(), key=lambda x: x[1], reverse=True)
    top5 = [k for k, _ in gain_sorted[:5]]
    for feat in CADENCE_FEATURES:
        g = gain.get(feat, 0.0)
        rank = next((i + 1 for i, (k, _) in enumerate(gain_sorted) if k == feat), "—")
        print(f"  {feat}: gain={g:.2f}  rank={rank}/{len(gain)}")
    print(f"  Top-5 features: {top5}")

    # ---------------------------------------------------------------
    # Save report
    # ---------------------------------------------------------------
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "experiment": "xgb_cadence_features",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "label_window_days": LABEL_WINDOW_DAYS,
        "random_state": RANDOM_STATE,
        "train_end": TRAIN_END,
        "val_end": VAL_END,
        "new_features": CADENCE_FEATURES,
        "n_features_control": len(ALL_FEATURES),
        "n_features_candidate": len(ALL_FEATURES_WITH_CADENCE),
        "production_baseline_stored": {
            "test_pr_auc": PROD_TEST_PR_AUC,
            "test_p10": PROD_TEST_P10,
        },
        "val": {
            "control": {
                "pr_auc": round(val_ctrl.pr_auc, 6),
                "p10": round(val_ctrl.precision_at_10pct, 6),
            },
            "candidate": {
                "pr_auc": round(val_cand.pr_auc, 6),
                "p10": round(val_cand.precision_at_10pct, 6),
            },
            "delta_pr_auc": round(val_cand.pr_auc - val_ctrl.pr_auc, 6),
            "delta_p10": round(val_cand.precision_at_10pct - val_ctrl.precision_at_10pct, 6),
        },
        "cv": {
            "n_folds": len(recent_folds),
            "control_per_fold": [round(s, 6) for s in cv_ctrl],
            "candidate_per_fold": [round(s, 6) for s in cv_cand],
            "mean_delta": round(float(np.mean(cv_deltas)), 6),
            "wins": f"{cv_wins}/{len(recent_folds)}",
        },
        "test": {
            "control": test_ctrl.to_dict(),
            "candidate": test_cand.to_dict(),
            "delta_pr_auc": round(delta_pr, 6),
            "delta_p10": round(delta_p10, 6),
        },
        "both_metrics_gate": gate,
        "cadence_feature_gain": {f: round(gain.get(f, 0.0), 4) for f in CADENCE_FEATURES},
    }
    report_path = REPORTS_DIR / f"xgb_cadence_features_{ts}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved report → {report_path}")


if __name__ == "__main__":
    main()
