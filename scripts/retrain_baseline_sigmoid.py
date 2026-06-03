"""Retrain the baseline pipeline with **sigmoid** (Platt) calibration.

The currently-shipped model uses isotonic calibration. Isotonic is a step
function whose output is constrained to the set of unique probabilities seen
during calibration fitting — on this dataset that produced ONLY 60 distinct
values across 23,513 restaurants. The UI showed many restaurants with
identical scores (e.g. `0.48` for multiple top-200 entries), which looked
broken to users.

Sigmoid calibration fits a single 2-parameter logistic onto the validation
set and produces continuous probabilities (no ties unless the underlying
decision function ties). Tier counts stay roughly the same; the within-tier
ranking becomes strictly ordered.

Run with the project's Python:
    PYTHONPATH=src /Users/jun/anaconda3/bin/python scripts/retrain_baseline_sigmoid.py

This script:
  1. Loads features.parquet + chronologically splits on the cutoffs in
     `data/models/baseline_<date>_metadata.json` (2024-07-01 / 2025-07-01).
  2. Fits the baseline pipeline on train, then wraps in
     CalibratedClassifierCV(cv='prefit', method='sigmoid') on val.
  3. Persists model + metadata under `data/models/baseline_<today>.joblib`.
  4. Scores every restaurant, writes:
       - data/predictions/scores.parquet
       - app/public/data/scores.json
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)

from foodsafety.config import RANDOM_STATE
from foodsafety.models.baseline import (
    ALL_FEATURES,
    LABEL_COL,
    build_baseline_pipeline,
)
from foodsafety.serve.predict_batch import (
    RISK_TIER_THRESHOLDS,
    build_scores_table,
    score_to_tier,
    write_scores_json,
)
from foodsafety.utils.time import temporal_split

REPO_ROOT = Path(__file__).resolve().parent.parent
FEATURES_PATH = REPO_ROOT / "data" / "processed" / "features.parquet"
MODELS_DIR = REPO_ROOT / "data" / "models"
PRED_DIR = REPO_ROOT / "data" / "predictions"
SCORES_JSON_PATH = REPO_ROOT / "app" / "public" / "data" / "scores.json"

# Mirror the original training run's cutoffs so the comparison is apples-to-
# apples. If those change, update both this constant AND the metadata audit.
TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"

MODEL_VERSION = "baseline_logreg_sigmoid"


def _precision_at_k(y_true: np.ndarray, y_score: np.ndarray, frac: float) -> float:
    k = max(1, int(round(frac * len(y_true))))
    top_idx = np.argsort(-y_score)[:k]
    return float(y_true[top_idx].mean())


def _evaluate(y_true: np.ndarray, y_proba: np.ndarray, label: str) -> dict:
    return {
        "n": int(len(y_true)),
        "positive_rate": float(y_true.mean()),
        "pr_auc": float(average_precision_score(y_true, y_proba)),
        "roc_auc": float(roc_auc_score(y_true, y_proba)),
        "precision_at_5pct": _precision_at_k(y_true, y_proba, 0.05),
        "precision_at_10pct": _precision_at_k(y_true, y_proba, 0.10),
        "precision_at_20pct": _precision_at_k(y_true, y_proba, 0.20),
        "brier_score": float(brier_score_loss(y_true, y_proba)),
        "log_loss": float(log_loss(y_true, y_proba, labels=[0, 1])),
        "split": label,
    }


def main() -> None:
    print(f"Loading {FEATURES_PATH}")
    features = pd.read_parquet(FEATURES_PATH)
    print(f"  shape: {features.shape}, dtypes verified for {len(ALL_FEATURES)} feature cols")

    if "inspection_date" not in features.columns:
        raise SystemExit("features.parquet missing inspection_date column")
    if LABEL_COL not in features.columns:
        raise SystemExit(f"features.parquet missing {LABEL_COL} column")

    # We split features into two views:
    #   • `features_modelable` — used for train/val/test. Drops rows whose
    #     180-day forward window extends past the dataset max date: their
    #     labels are under-counted (any unseen future Fail becomes y=0) so
    #     they'd bias eval metrics. The test split is the worst affected
    #     since it's the most recent slice.
    #   • `features` (unchanged) — used for SCORING the home page. The
    #     features themselves are valid even when the label is unreliable,
    #     and we don't want to drop ~3% of restaurants whose most-recent
    #     inspection happens to fall in the trailing 180 days.
    if "right_truncated" in features.columns:
        features_modelable = features.loc[~features["right_truncated"]].reset_index(
            drop=True
        )
        n_dropped = len(features) - len(features_modelable)
        if n_dropped:
            print(
                f"  filtered {n_dropped:,} right-truncated rows from modeling "
                f"({n_dropped / len(features):.1%} of input); full set retained "
                f"for scoring"
            )
    else:
        features_modelable = features

    print(f"Temporal split (train_end={TRAIN_END}, val_end={VAL_END})")
    split = temporal_split(features_modelable, train_end=TRAIN_END, val_end=VAL_END)
    print(
        f"  train n={len(split.train):,}  val n={len(split.val):,}  test n={len(split.test):,}"
    )

    X_train = split.train[ALL_FEATURES]
    y_train = split.train[LABEL_COL].astype(int).to_numpy()
    X_val = split.val[ALL_FEATURES]
    y_val = split.val[LABEL_COL].astype(int).to_numpy()
    X_test = split.test[ALL_FEATURES]
    y_test = split.test[LABEL_COL].astype(int).to_numpy()

    print("Fitting baseline pipeline on train")
    base = build_baseline_pipeline()
    base.fit(X_train, y_train)

    # Sigmoid (Platt) calibration fitted on val. cv='prefit' tells
    # CalibratedClassifierCV to use the provided already-fit estimator.
    print("Wrapping with CalibratedClassifierCV(method='sigmoid', cv='prefit')")
    calibrated = CalibratedClassifierCV(base, method="sigmoid", cv="prefit")
    calibrated.fit(X_val, y_val)

    # Evaluate
    p_val = calibrated.predict_proba(X_val)[:, 1]
    p_test = calibrated.predict_proba(X_test)[:, 1]
    val_metrics = _evaluate(y_val, p_val, "val")
    test_metrics = _evaluate(y_test, p_test, "test")
    print("Val:", json.dumps(val_metrics, indent=2))
    print("Test:", json.dumps(test_metrics, indent=2))

    # Persist model + metadata (NEVER overwrite per CLAUDE.md — date-stamp it).
    today = datetime.now().strftime("%Y%m%d")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / f"baseline_sigmoid_{today}.joblib"
    meta_path = MODELS_DIR / f"baseline_sigmoid_{today}_metadata.json"
    joblib.dump(calibrated, model_path)
    metadata = {
        "model": MODEL_VERSION,
        "random_state": RANDOM_STATE,
        "date_trained": datetime.now().strftime("%Y-%m-%d"),
        "split": {
            "train_end": TRAIN_END,
            "val_end": VAL_END,
            "train_n": len(split.train),
            "val_n": len(split.val),
            "test_n": len(split.test),
        },
        "features": {"all": list(ALL_FEATURES), "label_col": LABEL_COL},
        "metrics": {"val": val_metrics, "test": test_metrics},
        "calibration": "sigmoid (Platt) on val set, cv='prefit'",
        "features_parquet_mtime": (
            datetime.fromtimestamp(FEATURES_PATH.stat().st_mtime).isoformat()
        ),
    }
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved model → {model_path}")
    print(f"Saved metadata → {meta_path}")

    # Sanity: confirm we got continuous probabilities this time.
    full_p = calibrated.predict_proba(features[ALL_FEATURES])[:, 1]
    print(
        f"Unique probability values across {len(full_p):,} rows: {len(np.unique(full_p)):,}"
    )

    # Score every restaurant + export JSON for the web app.
    print("Building scores table (per-license_id, anchored on latest inspection)")
    scores = build_scores_table(calibrated, features, ALL_FEATURES, n_drivers=4)

    PRED_DIR.mkdir(parents=True, exist_ok=True)
    scores_parquet_path = PRED_DIR / "scores.parquet"
    scores.to_parquet(scores_parquet_path)
    print(f"Wrote {scores_parquet_path}: {len(scores):,} restaurants")

    # Display fields — copy across from the licenses table if available, else
    # default to empty strings. The existing scores.json already had these
    # populated from a join in notebook 06; here we leave neighborhood/zip/
    # facility_type empty if not joined in features.
    extras = ["neighborhood", "zip", "facility_type"]
    for col in extras:
        if col not in scores.columns and col in features.columns:
            scores[col] = (
                features.drop_duplicates("license_id").set_index("license_id")[col]
                .reindex(scores["license_id"].astype(str))
                .to_numpy()
            )

    # Re-tier with the calibrated thresholds (predict_batch.score_to_tier
    # uses the existing thresholds; sigmoid output is on the same probability
    # scale so tier semantics remain valid).
    print("Tier distribution (sigmoid):")
    tier_counts = scores["risk_tier"].value_counts().to_dict()
    print("  ", tier_counts)

    write_scores_json(
        scores,
        SCORES_JSON_PATH,
        schema_version="0.3.0",
        model_version=MODEL_VERSION,
    )
    print(f"Wrote {SCORES_JSON_PATH}")
    size_mb = SCORES_JSON_PATH.stat().st_size / 1024 / 1024
    print(f"  {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
