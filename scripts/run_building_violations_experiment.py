"""Experiment: Chicago Building Violations as XGBoost features.

Tests whether block-face building-violation counts + recency improve food-safety
risk prediction. The existing XGBoost run (`xgb_20260621_bef769ef8.json`) is the
control; this script trains the same model with three additional features:

    prior_bldg_violations_365d   — violation count on the block-face in past 365d
    prior_bldg_violations_730d   — violation count on the block-face in past 730d
    days_since_last_bldg_violation — recency of the most recent block-face violation

The spatial join uses the existing `add_building_features` (BallTree, ~30m radius)
which is already in `src/foodsafety/features/building_features.py`. Features are
added ON TOP of the canonical `features.parquet` to avoid recomputing all 57
existing features from scratch.

Promotion gate (same as notebook 05):
    XGBoost + violations beats control on BOTH test PR-AUC AND precision@10%

Usage:
    PYTHONPATH=src uv run python scripts/run_building_violations_experiment.py

Outputs:
    data/raw/building_violations.parquet            (fetched once, cached)
    data/processed/features_bldg_violations.parquet (features + new cols)
    reports/metrics/xgb_bldg_violations_<run_id>.json
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator

from foodsafety.config import DATASETS, PROCESSED_DIR, RAW_DIR
from foodsafety.features.build import build_features
from foodsafety.features.building_features import add_building_features
from foodsafety.io.soda import fetch_soda_keyset
from foodsafety.models.baseline import ALL_FEATURES, LABEL_COL
from foodsafety.models.evaluate import evaluate
from foodsafety.models.xgb import (
    build_xgb_estimator,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
)
from foodsafety.tracking import provenance
from foodsafety.utils.time import temporal_split

REPO_ROOT = Path(__file__).resolve().parent.parent

# --- Paths ------------------------------------------------------------------
BV_RAW_PATH = RAW_DIR / "building_violations.parquet"
FEATURES_PATH = PROCESSED_DIR / "features.parquet"
EXPERIMENT_FEATURES_PATH = PROCESSED_DIR / "features_bldg_violations.parquet"
REPORTS_DIR = REPO_ROOT / "reports" / "metrics"
CONTROL_METRICS_PATH = REPORTS_DIR / "xgb_20260621_bef769ef8.json"

# --- Split cutoffs (mirror notebook 05 / retrain script) --------------------
TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"

# --- Early-stopping protocol (mirror notebook 05) ---------------------------
ES_START = pd.Timestamp("2024-01-01")
EMBARGO = pd.Timedelta(days=180)

# --- New features this experiment adds on top of ALL_FEATURES ---------------
# Two groups, both leak-free (add_building_features enforces age > 0):
#
# 1. AGGREGATE: total violation count + recency regardless of bureau type.
# 2. BUREAU-SPECIFIC: per-bureau counts for the five bureaus directly tied to
#    food-safety risk (see FOOD_SAFETY_BUREAUS in building_features.py).
#    CONSERVATION dominates (86% of all violations) but the per-bureau split
#    lets XGBoost weight REFRIGERATION / PLUMBING separately — REFRIGERATION
#    failures are a direct food-safety risk and should score differently than
#    a general structural complaint. Bureau-specific features use a single
#    365d window to keep the feature count manageable for sparse bureaus
#    (32–43k rows city-wide vs 1.3M for CONSERVATION).
BLDG_VIOLATION_FEATURES: list[str] = [
    # Aggregate (all bureaus)
    "prior_bldg_violations_365d",
    "prior_bldg_violations_730d",
    "days_since_last_bldg_violation",
    # Food-safety bureau-specific counts (365d)
    "prior_bldg_conservation_365d",
    "prior_bldg_refrigeration_365d",
    "prior_bldg_plumbing_365d",
    "prior_bldg_ventilation_365d",
    "prior_bldg_electrical_365d",
    # Combined food-safety bureau recency
    "days_since_last_food_safety_bldg_violation",
]

EXPERIMENT_FEATURES: list[str] = ALL_FEATURES + BLDG_VIOLATION_FEATURES


# ---------------------------------------------------------------------------
# Step 1: Fetch building violations (cached)
# ---------------------------------------------------------------------------


def fetch_building_violations() -> pd.DataFrame:
    """Load from cache or fetch from SODA (22u3-xenr).

    Fetches violation_date, latitude, longitude, department_bureau — the four
    columns needed for aggregate + bureau-specific spatial features.

    Start date is 2010-01-01 to align with the inspection dataset (earliest
    inspection: 2010-01-04). Pre-2010 violations would only ever back-fill
    burn-in rows (pre-2019 inspections) that never enter training, so pulling
    them wastes bandwidth and disk space.

    Cache check: if the parquet already has department_bureau we reuse it;
    if it's an old fetch without that column we re-fetch.
    """
    if BV_RAW_PATH.exists():
        cached = pd.read_parquet(BV_RAW_PATH)
        if "department_bureau" in cached.columns:
            print(f"Loading cached violations → {BV_RAW_PATH} ({len(cached):,} rows)")
            return cached
        print("Cached violations missing department_bureau — re-fetching.")

    print("Fetching Chicago Building Violations (22u3-xenr)...")
    shard_dir = RAW_DIR / "_partial_building_violations"
    df = fetch_soda_keyset(
        dataset_id=DATASETS["building_violations"],
        cursor_col="violation_date",
        # Align with the inspection dataset start (2010-01-04). Pre-2010 violations
        # would only ever be relevant to burn-in rows (pre-2019 inspections) which
        # never enter training, so pulling them wastes bandwidth and disk space.
        cursor_start="2010-01-01T00:00:00",
        where_extra="latitude IS NOT NULL AND longitude IS NOT NULL AND violation_date IS NOT NULL",
        page_size=50_000,
        shard_dir=shard_dir,
        verbose=True,
    )

    # Retain only the four columns needed; drop everything else to save disk.
    keep = ["violation_date", "latitude", "longitude", "department_bureau"]
    keep = [c for c in keep if c in df.columns]
    df = df[keep].copy()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(BV_RAW_PATH, index=False)
    print(f"  saved → {BV_RAW_PATH} ({len(df):,} rows, {BV_RAW_PATH.stat().st_size / 1e6:.1f} MB)")
    return df


# ---------------------------------------------------------------------------
# Step 2: Add building violation features to the canonical features table
# ---------------------------------------------------------------------------


def _rebuild_canonical_features() -> pd.DataFrame:
    """Rebuild features.parquet from inspections_labeled + licenses_historical.

    Called when features.parquet is stale (missing columns added to ALL_FEATURES
    since it was last built). Skips the 311 complaints join — those features were
    tested and dropped from ALL_FEATURES (see baseline.py comments), so omitting
    them here doesn't affect the experiment.
    """
    labeled_path = PROCESSED_DIR / "inspections_labeled.parquet"
    licenses_hist_path = RAW_DIR / "licenses_historical.parquet"
    for p in (labeled_path, licenses_hist_path):
        if not p.exists():
            raise SystemExit(f"Missing {p} — cannot rebuild features.parquet.")

    print("  Loading inspections_labeled + licenses_historical...")
    labeled = pd.read_parquet(labeled_path)
    licenses_historical = pd.read_parquet(licenses_hist_path)

    print("  Running build_features (complaints skipped — not in ALL_FEATURES)...")
    features = build_features(labeled, complaints=None, licenses_historical=licenses_historical)

    out = features.copy()
    obj_cols = out.select_dtypes("object").columns
    out[obj_cols] = out[obj_cols].astype("string")
    out.to_parquet(FEATURES_PATH, index=False)
    print(f"  Rebuilt features.parquet → {features.shape[0]:,} rows × {features.shape[1]} cols")
    return features


def build_experiment_features(violations: pd.DataFrame) -> pd.DataFrame:
    """Build features.parquet (rebuilding if stale) then layer building-violation
    features on top, saving the result to features_bldg_violations.parquet.

    Adds 9 new columns on top of the 36 canonical ALL_FEATURES:
      - 3 aggregate (all bureaus): 365d/730d counts + recency
      - 5 bureau-specific 365d counts (CONSERVATION / REFRIGERATION / PLUMBING /
        VENTILATION / ELECTRICAL)
      - 1 combined food-safety-bureau recency

    Stale-cache detection: if either the canonical features.parquet is missing
    columns from ALL_FEATURES, or the experiment parquet is missing the building
    violation columns, both are rebuilt from source.
    """
    # Step 1: ensure canonical features.parquet has all ALL_FEATURES columns.
    canonical_ok = False
    if FEATURES_PATH.exists():
        canonical_cols = set(pd.read_parquet(FEATURES_PATH, columns=[]).columns)
        missing_canonical = [c for c in ALL_FEATURES if c not in canonical_cols]
        if missing_canonical:
            print(
                f"features.parquet is stale — missing {len(missing_canonical)} columns "
                f"from ALL_FEATURES: {missing_canonical}"
            )
            print("Rebuilding features.parquet from source...")
            _rebuild_canonical_features()
        else:
            canonical_ok = True
    if not canonical_ok and not FEATURES_PATH.exists():
        print("features.parquet not found — building from source...")
        _rebuild_canonical_features()

    # Step 2: check experiment parquet cache.
    if EXPERIMENT_FEATURES_PATH.exists():
        exp_cols = set(pd.read_parquet(EXPERIMENT_FEATURES_PATH, columns=[]).columns)
        if all(c in exp_cols for c in BLDG_VIOLATION_FEATURES + ALL_FEATURES):
            print(f"Loading cached experiment features → {EXPERIMENT_FEATURES_PATH}")
            return pd.read_parquet(EXPERIMENT_FEATURES_PATH)
        print("Experiment features cache is stale — rebuilding.")

    # Step 3: load canonical features and add building violation features.
    print(f"Loading canonical features → {FEATURES_PATH}")
    features = pd.read_parquet(FEATURES_PATH)
    print(f"  shape: {features.shape}")

    print("Adding block-face building violation features (~30m BallTree)...")
    features = add_building_features(features, permits=None, violations=violations)

    for col in BLDG_VIOLATION_FEATURES:
        n_nn = features[col].notna().sum()
        print(f"  {col}: {n_nn:,}/{len(features):,} non-null ({100.0 * n_nn / len(features):.1f}%)")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    features.to_parquet(EXPERIMENT_FEATURES_PATH, index=False)
    print(f"  saved → {EXPERIMENT_FEATURES_PATH}")
    return features


# ---------------------------------------------------------------------------
# Step 3: Prepare experiment features for XGBoost
# ---------------------------------------------------------------------------


def prepare_experiment_features(
    df: pd.DataFrame, *, categorical_dtypes: dict | None = None
) -> pd.DataFrame:
    """Cast experiment feature columns to the dtypes XGBoost expects.

    Mirrors xgb.prepare_xgb_features but operates on EXPERIMENT_FEATURES
    (ALL_FEATURES + BLDG_VIOLATION_FEATURES) so the three new columns get
    proper float32 treatment alongside the existing numeric features.
    """
    from foodsafety.models.baseline import BOOLEAN_FEATURES, CATEGORICAL_FEATURES, NUMERIC_FEATURES

    out = df[EXPERIMENT_FEATURES].copy()

    for c in CATEGORICAL_FEATURES:
        if categorical_dtypes is not None and c in categorical_dtypes:
            out[c] = pd.Categorical(out[c], categories=categorical_dtypes[c].categories)
        else:
            out[c] = out[c].astype("category")

    for c in BOOLEAN_FEATURES:
        out[c] = out[c].astype("int8")

    # Existing numeric features + the three new ones — all get float32.
    all_numeric = NUMERIC_FEATURES + BLDG_VIOLATION_FEATURES
    for c in all_numeric:
        out[c] = out[c].astype("float32")

    return out


# ---------------------------------------------------------------------------
# Step 4: Train XGBoost (mirror notebook 05 protocol)
# ---------------------------------------------------------------------------


def train_xgb(features: pd.DataFrame) -> tuple[object, dict, dict]:
    """Train XGBoost on EXPERIMENT_FEATURES using the notebook 05 protocol.

    Protocol:
      1. Temporal split (train_end=2024-07-01, val_end=2025-07-01)
      2. Carved ES holdout from the tail of train (ES_START=2024-01-01,
         180d embargo) — val stays pure for calibration
      3. Probe with early stopping on train_es → best N_TREES
      4. Refit on full train at N_TREES (no early stopping)
      5. Sigmoid calibration on val

    Returns (calibrated_model, val_metrics_dict, test_metrics_dict).
    """
    # Drop right-truncated rows (under-counted labels) from modelling.
    if "right_truncated" in features.columns:
        modelable = features.loc[~features["right_truncated"]].reset_index(drop=True)
        n_dropped = len(features) - len(modelable)
        if n_dropped:
            print(f"  filtered {n_dropped:,} right-truncated rows from modelling")
    else:
        modelable = features

    print(f"Temporal split (train_end={TRAIN_END}, val_end={VAL_END})")
    split = temporal_split(modelable, train_end=TRAIN_END, val_end=VAL_END)
    print(f"  train n={len(split.train):,}  val n={len(split.val):,}  test n={len(split.test):,}")

    X_train_raw = split.train[EXPERIMENT_FEATURES]
    y_train = split.train[LABEL_COL].astype(int)
    X_val_raw = split.val[EXPERIMENT_FEATURES]
    y_val = split.val[LABEL_COL].astype(int)
    X_test_raw = split.test[EXPERIMENT_FEATURES]
    y_test = split.test[LABEL_COL].astype(int)

    X_train = prepare_experiment_features(X_train_raw)
    cat_dtypes = extract_categorical_dtypes(X_train)
    X_val = prepare_experiment_features(X_val_raw, categorical_dtypes=cat_dtypes)
    X_test = prepare_experiment_features(X_test_raw, categorical_dtypes=cat_dtypes)

    # Early-stopping holdout carved from the tail of train.
    train_dates = split.train["inspection_date"]
    fit_mask = (train_dates < (ES_START - EMBARGO)).to_numpy()
    es_mask = (train_dates >= ES_START).to_numpy()
    X_train_fit, y_train_fit = X_train[fit_mask], y_train[fit_mask]
    X_train_es, y_train_es = X_train[es_mask], y_train[es_mask]
    print(f"  fit set   n={fit_mask.sum():>6,}  (date < {(ES_START - EMBARGO).date()})")
    print(f"  es  set   n={es_mask.sum():>6,}  (date >= {ES_START.date()}, 180d embargo gap)")

    spw = compute_scale_pos_weight(y_train)
    print(f"  scale_pos_weight = {spw:.3f}")

    # Probe fit: find best_iteration without touching val.
    print("Probe fit (early-stopping on train_es)...")
    probe = build_xgb_estimator(scale_pos_weight=spw, early_stopping_rounds=40)
    probe.fit(X_train_fit, y_train_fit, eval_set=[(X_train_es, y_train_es)], verbose=False)
    N_TREES = int(probe.best_iteration) + 1
    print(f"  best_iteration={N_TREES - 1}  best_score={probe.best_score:.4f}")

    # Refit on full train at fixed tree count.
    print(f"Refitting on full train with N_TREES={N_TREES}...")
    xgb = build_xgb_estimator(
        scale_pos_weight=spw,
        n_estimators=N_TREES,
        early_stopping_rounds=None,
    )
    xgb.fit(X_train, y_train, verbose=False)

    # Sigmoid calibration on val (val is now untouched by early stopping).
    print("Calibrating (sigmoid) on val...")
    model = CalibratedClassifierCV(FrozenEstimator(xgb), method="sigmoid")
    model.fit(X_val, y_val)

    val_scores = model.predict_proba(X_val)[:, 1]
    test_scores = model.predict_proba(X_test)[:, 1]
    val_metrics = evaluate(y_val.to_numpy(), val_scores).to_dict()
    test_metrics = evaluate(y_test.to_numpy(), test_scores).to_dict()

    # Feature importances for the top new features.
    importances = pd.Series(xgb.feature_importances_, index=EXPERIMENT_FEATURES)
    bldg_imp = importances[BLDG_VIOLATION_FEATURES].sort_values(ascending=False)
    print("\nBuilding violation feature importances (gain):")
    for feat, imp in bldg_imp.items():
        rank = int((importances > imp).sum()) + 1
        print(f"  {feat:<40} {imp:.4f}  (rank {rank}/{len(EXPERIMENT_FEATURES)})")

    return model, val_metrics, test_metrics


# ---------------------------------------------------------------------------
# Step 5: Compare with control and save report
# ---------------------------------------------------------------------------


def print_comparison(val_metrics: dict, test_metrics: dict) -> None:
    """Print a side-by-side comparison vs the control XGBoost run."""
    control: dict | None = None
    if CONTROL_METRICS_PATH.exists():
        raw = json.loads(CONTROL_METRICS_PATH.read_text())
        control = raw.get("test", raw)
    else:
        print(f"Control metrics not found at {CONTROL_METRICS_PATH}; skipping comparison.")

    key_metrics = [
        "pr_auc",
        "roc_auc",
        "precision_at_5pct",
        "precision_at_10pct",
        "precision_at_20pct",
        "recall_at_10pct",
        "top_decile_lift",
        "brier_score",
        "log_loss",
    ]

    print("\n" + "=" * 72)
    print("EXPERIMENT RESULTS — XGBoost + Building Violations vs Control")
    print("=" * 72)
    header = f"{'Metric':<30} {'Val':>10} {'Test':>10}"
    if control:
        header += f" {'Control':>10} {'Delta':>10}"
    print(header)
    print("-" * (72 if not control else 72))

    for k in key_metrics:
        val_v = val_metrics.get(k, float("nan"))
        test_v = test_metrics.get(k, float("nan"))
        row = f"{k:<30} {val_v:>10.4f} {test_v:>10.4f}"
        if control:
            ctrl_v = control.get(k, float("nan"))
            delta = test_v - ctrl_v
            row += f" {ctrl_v:>10.4f} {delta:>+10.4f}"
        print(row)

    if control:
        pr_delta = test_metrics["pr_auc"] - control["pr_auc"]
        p10_delta = test_metrics["precision_at_10pct"] - control["precision_at_10pct"]
        print("\nPromotion gate (must beat control on BOTH pr_auc AND precision@10%):")
        pr_mark = "✓" if pr_delta > 0 else "✗"
        p10_mark = "✓" if p10_delta > 0 else "✗"
        print(f"  {pr_mark}  PR-AUC       {pr_delta:+.4f}")
        print(f"  {p10_mark}  Precision@10% {p10_delta:+.4f}")
        if pr_delta > 0 and p10_delta > 0:
            print("\n  RESULT: BOTH gates passed — candidate for promotion.")
        elif pr_delta > 0 or p10_delta > 0:
            print("\n  RESULT: ONE gate passed — investigate before promoting.")
        else:
            print("\n  RESULT: Neither gate passed — building violations not helpful here.")
    print("=" * 72)


def save_report(val_metrics: dict, test_metrics: dict, features_path: Path) -> Path:
    """Write metrics + provenance to reports/metrics/."""
    prov = provenance(features_path, EXPERIMENT_FEATURES, REPO_ROOT)
    run_id = prov["run_id"]

    control_test: dict | None = None
    if CONTROL_METRICS_PATH.exists():
        raw = json.loads(CONTROL_METRICS_PATH.read_text())
        control_test = raw.get("test", raw)

    report = {
        "model": "xgboost_bldg_violations",
        "run_id": run_id,
        "git_commit": prov["git_commit"],
        "git_dirty": prov["git_dirty"],
        "calibration": "sigmoid",
        "experiment": "building_violations_features",
        "new_features": BLDG_VIOLATION_FEATURES,
        "feature_set_version": prov["feature_set_version"],
        "features_sha256": prov["features_sha256"],
        "split": {"train_end": TRAIN_END, "val_end": VAL_END},
        "val": val_metrics,
        "test": test_metrics,
    }
    if control_test:
        report["control_test"] = control_test
        report["delta_vs_control"] = {
            k: round(test_metrics[k] - control_test[k], 4)
            for k in ["pr_auc", "roc_auc", "precision_at_10pct", "top_decile_lift", "brier_score"]
            if k in test_metrics and k in control_test
        }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"xgb_bldg_violations_{run_id}.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nSaved report → {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print(f"[{datetime.now():%H:%M:%S}] Building Violations XGBoost Experiment")
    print(f"  Control:     {CONTROL_METRICS_PATH.name}")
    print(f"  New features: {BLDG_VIOLATION_FEATURES}")
    print()

    if not FEATURES_PATH.exists():
        raise SystemExit(
            f"Missing {FEATURES_PATH}. Run notebooks/03_feature_engineering.ipynb first."
        )

    violations = fetch_building_violations()
    print(f"  violations: {len(violations):,} rows")
    print()

    features = build_experiment_features(violations)
    print()

    model, val_metrics, test_metrics = train_xgb(features)  # noqa: F841 (model not saved — experiment only)
    print()

    print_comparison(val_metrics, test_metrics)
    save_report(val_metrics, test_metrics, EXPERIMENT_FEATURES_PATH)


if __name__ == "__main__":
    main()
