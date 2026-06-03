"""Baseline logistic-regression pipeline.

This is the FIRST model we train against ``features.parquet``. It exists for
three reasons:

  1. **Defensibility.** A calibrated logreg with leak-free features is a
     defensible model on its own — every coefficient is interpretable, every
     prediction is reproducible. If XGBoost only barely beats this, we ship
     this. If XGBoost meaningfully beats it, we ship XGBoost but report
     baseline as the comparator in the model card.

  2. **Pipeline contract.** This module pins down the canonical feature lists
     (numeric, categorical, boolean). All downstream models — including
     XGBoost in Phase 5 — consume the same feature contract from here so a
     change in feature naming/grouping flows through one file.

  3. **Sanity check for the data layer.** If this pipeline can't fit, that's a
     signal something in feature engineering is broken (rare value in a
     categorical, all-NaN column, etc.). A baseline that crashes is more
     informative than a fancy model that crashes.

Per CLAUDE.md:
  - ``class_weight='balanced'`` — NOT SMOTE. SMOTE on time-split data
    inflates apparent PR-AUC and invalidates calibration.
  - All ``prior_*`` features were built leak-free in feature engineering;
    we trust that contract here.
  - This pipeline is uncalibrated; the notebook fits an isotonic calibrator
    against the val set as a separate step.
"""

from __future__ import annotations

from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from foodsafety.config import RANDOM_STATE

# ---------------------------------------------------------------------------
# Feature contract — single source of truth across all baseline / XGBoost work
# ---------------------------------------------------------------------------

NUMERIC_FEATURES: list[str] = [
    # Prior facility history (leak-free per feature_engineering).
    # Note: `prior_fail_rate` and `prior_event_rate` (ratios) are deliberately
    # dropped — tree models can reconstruct ratios from numerator + denominator
    # and the ratios add noise without orthogonal signal.
    "prior_inspections",
    "prior_fails",
    "prior_priority_violations",
    "prior_core_violations",
    "prior_fail_or_priority_events",
    # Recency
    "days_since_last_inspection",
    "days_since_last_fail",
    # Calendar. Deliberate omissions:
    #   - `temporal_year`: time-anchored, doesn't generalise across the
    #     chronological split (every test row has year > all train years).
    #   - `temporal_dow`: bottom of XGBoost gain in Phase 5 ablation — noise.
    "temporal_month",
    "temporal_quarter",
    # License-history features (joined from licenses_historical.parquet)
    "license_age_days",
    "license_n_history_rows",
    # 311 spatial counts are deliberately omitted. They sat at the bottom of
    # XGBoost gain in the Phase-5 ablation, and the violation-text flags
    # (`flag_kw_rodent`, `flag_kw_pest`, `flag_kw_sewage`) already capture
    # the same signal directly. Carnegie Mellon's 2019 hindsight critique of
    # Chicago's heat-map features reached the same conclusion.
]

CATEGORICAL_FEATURES: list[str] = [
    "static_facility_type",
    "static_risk_tier",
    "static_zip",
    # `static_zip3` dropped — strict subset of `static_zip`, no orthogonal info.
    # `temporal_season` dropped — categorical bucket of `temporal_month`.
]

BOOLEAN_FEATURES: list[str] = [
    "flag_kw_temperature",
    "flag_kw_cooling",
    "flag_kw_raw_food",
    "flag_kw_cross_contamination",
    "flag_kw_expired",
    "flag_kw_rodent",
    "flag_kw_pest",
    "flag_kw_no_soap",
    "flag_kw_no_paper_towels",
    "flag_kw_handwash_sink",
    "flag_kw_sewage",
    "flag_kw_certified_manager",
]

ALL_FEATURES: list[str] = NUMERIC_FEATURES + CATEGORICAL_FEATURES + BOOLEAN_FEATURES

LABEL_COL: str = "y_fail_or_critical_next_180d"


def build_baseline_pipeline(
    *,
    random_state: int = RANDOM_STATE,
    onehot_min_frequency: int = 30,
    max_iter: int = 3000,
) -> Pipeline:
    """Construct the baseline classification pipeline.

    Preprocessing:
      - **Numeric**: median imputation (some `days_since_*` columns are NaN
        on first-inspection rows) → standard scaling. Scaling matters for
        LogReg's L2 regularisation.
      - **Categorical**: one-hot encoding with ``min_frequency=30`` so rare
        ZIPs / facility types collapse into an "infrequent" bucket. Without
        this, the LogReg fits noise on ZIPs that appear < 5 times.
      - **Boolean**: pass-through. Bool columns are already 0/1; scaling
        them changes magnitudes uselessly. LogReg handles 0/1 natively.

    Estimator: LogisticRegression with ``class_weight='balanced'`` to handle
    the ~13% positive rate. We use ``liblinear`` solver since the design
    matrix is medium-sized and L2 is fine; ``saga`` would be appropriate if
    we add L1 / elastic net later.
    """
    numeric_pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ]
    )

    categorical_pipeline = OneHotEncoder(
        handle_unknown="infrequent_if_exist",
        min_frequency=onehot_min_frequency,
        sparse_output=True,
    )

    preprocess = ColumnTransformer(
        transformers=[
            ("num", numeric_pipeline, NUMERIC_FEATURES),
            ("cat", categorical_pipeline, CATEGORICAL_FEATURES),
            ("bool", "passthrough", BOOLEAN_FEATURES),
        ],
        sparse_threshold=0.5,
        verbose_feature_names_out=True,
    )

    # class_weight='balanced' is the CLAUDE.md-mandated alternative to SMOTE.
    # It re-weights the loss inversely proportional to class frequency.
    model = LogisticRegression(
        class_weight="balanced",
        solver="liblinear",
        max_iter=max_iter,
        random_state=random_state,
    )

    return Pipeline([("preprocess", preprocess), ("model", model)])
