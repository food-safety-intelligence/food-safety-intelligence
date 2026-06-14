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

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator

from foodsafety.config import LABEL_WINDOW_DAYS, RANDOM_STATE
from foodsafety.models.baseline import (
    ALL_FEATURES,
    LABEL_COL,
    build_baseline_pipeline,
)
from foodsafety.models.evaluate import evaluate
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
REPORTS_METRICS_DIR = REPO_ROOT / "reports" / "metrics"

# Mirror the original training run's cutoffs so the comparison is apples-to-
# apples. If those change, update both this constant AND the metadata audit.
TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"

MODEL_VERSION = "baseline_logreg_sigmoid"


def _git_info() -> dict:
    """Best-effort current commit + dirty flag, for run provenance."""
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True
            ).strip()
        )
        return {"commit": sha, "short": sha[:9], "dirty": dirty}
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"commit": None, "short": "nogit", "dirty": None}


def _sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    """Content hash of a file — a stable identity for the dataset version
    (mtime changes on every rebuild even when content is identical)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _feature_set_version(features: list[str]) -> str:
    """Short hash of the ordered feature contract — changes iff features do."""
    return hashlib.sha256("\n".join(features).encode()).hexdigest()[:12]


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
        n_dropped = 0

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

    # Sigmoid (Platt) calibration of the already-fit pipeline on val. Wrapping
    # in FrozenEstimator marks `base` as pre-fit, so only the calibration
    # mapping is learned — the base estimator is not refit.
    print("Calibrating (sigmoid) on val without refitting the base estimator")
    calibrated = CalibratedClassifierCV(FrozenEstimator(base), method="sigmoid")
    calibrated.fit(X_val, y_val)

    # Evaluate
    p_val = calibrated.predict_proba(X_val)[:, 1]
    p_test = calibrated.predict_proba(X_test)[:, 1]
    val_metrics = evaluate(y_val, p_val).to_dict()
    test_metrics = evaluate(y_test, p_test).to_dict()
    print("Val:", json.dumps(val_metrics, indent=2))
    print("Test:", json.dumps(test_metrics, indent=2))

    # --- Provenance / experiment-tracking fields (Tier-0) ------------------
    # Tie this run to exact code (git SHA), exact data (content hash of the
    # features parquet — NOT its mtime, which changes on every rebuild), and
    # the feature-contract version, so a metrics record fully identifies what
    # produced it and same-day reruns don't collide.
    today = datetime.now().strftime("%Y%m%d")
    git = _git_info()
    run_id = f"{today}_{git['short']}"
    features_sha = _sha256_file(FEATURES_PATH)
    fs_version = _feature_set_version(list(ALL_FEATURES))

    metadata = {
        "model": MODEL_VERSION,
        "run_id": run_id,
        "git_commit": git["commit"],
        "git_dirty": git["dirty"],
        "random_state": RANDOM_STATE,
        "date_trained": datetime.now().strftime("%Y-%m-%d"),
        "calibration": "sigmoid (Platt) on val set, cv='prefit'",
        "label_window_days": LABEL_WINDOW_DAYS,
        "right_truncation": {
            "filtered_from_modeling": int(n_dropped),
            "kept_for_scoring": True,
        },
        "split": {
            "train_end": TRAIN_END,
            "val_end": VAL_END,
            "train_n": len(split.train),
            "val_n": len(split.val),
            "test_n": len(split.test),
        },
        "features": {
            "all": list(ALL_FEATURES),
            "label_col": LABEL_COL,
            "n_features": len(ALL_FEATURES),
            "feature_set_version": fs_version,
        },
        "dataset": {
            "features_parquet": str(FEATURES_PATH.relative_to(REPO_ROOT)),
            "features_sha256": features_sha,
            "rows_total": int(len(features)),
            "rows_modelable": int(len(features_modelable)),
        },
        "metrics": {"val": val_metrics, "test": test_metrics},
    }

    # Persist model + metadata (NEVER overwrite per CLAUDE.md — run-id stamps it).
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / f"baseline_sigmoid_{run_id}.joblib"
    meta_path = MODELS_DIR / f"baseline_sigmoid_{run_id}_metadata.json"
    joblib.dump(calibrated, model_path)
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"Saved model → {model_path}")
    print(f"Saved metadata → {meta_path}")

    # RECONCILE: write the SERVED model's metrics to the git-tracked ledger
    # (reports/metrics/), alongside baseline_*/xgb_* — so the numbers we cite
    # describe the model that actually feeds scores.json. data/models/ is
    # gitignored, so without this the served (sigmoid, RT-filtered) model had
    # no tracked metrics, while the committed reports described a different
    # (isotonic, unfiltered) model.
    REPORTS_METRICS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_METRICS_DIR / f"baseline_sigmoid_{run_id}.json"
    report = {
        "model": MODEL_VERSION,
        "run_id": run_id,
        "git_commit": git["commit"],
        "git_dirty": git["dirty"],
        "calibration": "sigmoid",
        "right_truncation_filtered": int(n_dropped),
        "feature_set_version": fs_version,
        "features_sha256": features_sha,
        "val": val_metrics,
        "test": test_metrics,
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Saved metrics report → {report_path}")

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
