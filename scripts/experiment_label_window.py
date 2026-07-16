"""Experiment: is a SHORTER forward-label window easier to predict than the
production 180-day ("mid-term") window?

Hypothesis (from a teammate note): short-term risk should be structurally
easier to predict than mid-term, since there's less time for confounding
events (ownership change, a cleanup, a new violation unrelated to today's
visit) to intervene between the anchor inspection and the outcome.

This re-derives the label at several window sizes via
``foodsafety.data.labels.build_labels(label_window_days=W)`` — the label
build is independent of feature engineering, so the SAME features.parquet
is reused for every window; only the label (and its ``right_truncated`` /
``is_burnin`` companions, which are window-dependent) is recomputed and
swapped in. Same chronological split, same production LogReg + XGB configs,
same honest-test protocol (drop right_truncated from train/val, score the
full test) as the rest of this project's experiments
(scripts/run_violation_label_experiment.py).

**Read the comparison base-rate-normalized, not on raw PR-AUC.** A shorter
window has structurally lower prevalence (less time for a fail/priority
event to occur), and PR-AUC scales with prevalence — the same "is a crisper
target more learnable" caveat documented for the 2026-06-21 fail-only-label
experiment in docs/model-experiments.md. This script reports PR-AUC directly
plus PR-AUC/prevalence and top-decile lift (already prevalence-normalized)
as the fairer read.

Chicago only: NYC/LA's label is "next inspection graded B/C" (event-anchored,
no fixed day-window to vary), so there is no NYC/LA analog of this study.

Run:
    PYTHONPATH=src uv run python scripts/experiment_label_window.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from foodsafety.config import RAW_DIR
from foodsafety.data.labels import build_labels
from foodsafety.io import storage
from foodsafety.models.baseline import ALL_FEATURES, build_baseline_pipeline
from foodsafety.models.evaluate import evaluate
from foodsafety.models.xgb import (
    build_production_xgb,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    prepare_xgb_features,
)
from foodsafety.utils.time import temporal_split

REPO_ROOT = Path(__file__).resolve().parent.parent
FEATURES_PATH = (
    REPO_ROOT / "data" / "processed" / "features" / "features_current_inspection.parquet"
)
METRICS_DIR = REPO_ROOT / "reports" / "metrics" / "experiments"

# 30d/60d/90d = short-term candidates; 180d = the production ("mid-term") window.
WINDOWS_DAYS = [30, 60, 90, 180]
TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"


def _labels_for_window(raw_inspections: pd.DataFrame, window_days: int) -> pd.DataFrame:
    """Re-derive just the label-family columns for one window, keyed by inspection_id."""
    labeled = build_labels(raw_inspections, label_window_days=window_days)
    return labeled[["inspection_id", "right_truncated", "y_fail_or_critical_next_180d"]].rename(
        columns={"y_fail_or_critical_next_180d": "y_label"}
    )


def _fit_and_eval(train, val, test, feats) -> dict:
    y_train = train["y_label"].astype(int).to_numpy()
    y_val = val["y_label"].astype(int).to_numpy()
    y_test = test["y_label"].astype(int).to_numpy()

    # LogReg baseline.
    base = build_baseline_pipeline()
    base.fit(train[feats], y_train)
    p_test_lr = base.predict_proba(test[feats])[:, 1]

    # Production XGB (depth-3, monotone).
    x_train = prepare_xgb_features(train[feats])
    cat_dtypes = extract_categorical_dtypes(x_train)
    x_val = prepare_xgb_features(val[feats], categorical_dtypes=cat_dtypes)
    x_test = prepare_xgb_features(test[feats], categorical_dtypes=cat_dtypes)
    spw = compute_scale_pos_weight(y_train)
    xgb = build_production_xgb(scale_pos_weight=spw, features=feats)
    xgb.fit(x_train, y_train, eval_set=[(x_val, y_val)], verbose=False)
    p_test_xgb = xgb.predict_proba(x_test)[:, 1]

    m_lr = evaluate(y_test, p_test_lr).to_dict()
    m_xgb = evaluate(y_test, p_test_xgb).to_dict()
    return {
        "logreg": m_lr,
        "xgb": m_xgb,
        "n_train": len(train),
        "n_val": len(val),
        "n_test": len(test),
    }


def main() -> None:
    print(f"Loading features from {FEATURES_PATH}")
    features = storage.read_parquet(str(FEATURES_PATH))
    # Drop the 180d-window label family baked into features.parquet — every
    # window below supplies its own.
    features = features.drop(columns=["right_truncated", "y_fail_or_critical_next_180d"])
    print(f"  shape: {features.shape}")

    raw_path = storage.join(str(RAW_DIR), "inspections.parquet")
    print(f"Loading raw inspections from {raw_path}")
    raw_inspections = storage.read_parquet(raw_path)

    results = {}
    for window in WINDOWS_DAYS:
        print(f"\n=== window={window}d ===")
        labels = _labels_for_window(raw_inspections, window)
        df = features.merge(labels, on="inspection_id", how="inner")
        df = df[df["y_label"].notna()].copy()
        df["inspection_date"] = pd.to_datetime(df["inspection_date"])

        split = temporal_split(df, train_end=TRAIN_END, val_end=VAL_END)
        train = split.train[~split.train["right_truncated"]].copy()
        val = split.val[~split.val["right_truncated"]].copy()
        test = split.test.copy()  # honest test: full, unfiltered

        base_rate = float(test["y_label"].astype(int).mean())
        print(
            f"  train={len(train):,}  val={len(val):,}  test={len(test):,}  "
            f"test base rate={base_rate:.4f}"
        )

        metrics = _fit_and_eval(train, val, test, list(ALL_FEATURES))
        for model in ("logreg", "xgb"):
            m = metrics[model]
            pr_per_prev = m["pr_auc"] / base_rate if base_rate > 0 else float("nan")
            print(
                f"  [{model:6s}] PR-AUC={m['pr_auc']:.4f}  (PR-AUC/prev={pr_per_prev:.3f})  "
                f"ROC-AUC={m['roc_auc']:.4f}  P@10={m['precision_at_10pct']:.4f}  "
                f"lift@10={m['top_decile_lift']:.3f}  brier={m['brier_score']:.4f}"
            )
            metrics[model]["pr_auc_per_prevalence"] = round(pr_per_prev, 4)
        metrics["base_rate"] = round(base_rate, 4)
        results[str(window)] = metrics

    print("\n===== SUMMARY (test set, base-rate-normalized read) =====")
    print(
        f"{'window':>8} {'base_rate':>10} {'model':>7} {'pr_auc':>8} {'pr/prev':>8} {'roc_auc':>8} {'p@10':>7} {'lift@10':>8}"
    )
    for window in WINDOWS_DAYS:
        r = results[str(window)]
        for model in ("logreg", "xgb"):
            m = r[model]
            print(
                f"{window:>7}d {r['base_rate']:>10.4f} {model:>7} {m['pr_auc']:>8.4f} "
                f"{m['pr_auc_per_prevalence']:>8.3f} {m['roc_auc']:>8.4f} "
                f"{m['precision_at_10pct']:>7.4f} {m['top_decile_lift']:>8.3f}"
            )

    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = METRICS_DIR / f"label_window_study_{date.today().isoformat()}.json"
    out_path.write_text(
        json.dumps(
            {
                "experiment": "label_window_short_vs_mid_term",
                "date": date.today().isoformat(),
                "windows_days": WINDOWS_DAYS,
                "train_end": TRAIN_END,
                "val_end": VAL_END,
                "features": list(ALL_FEATURES),
                "results": results,
            },
            indent=2,
        )
    )
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
