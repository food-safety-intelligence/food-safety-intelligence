"""Tests for the XGBoost model helpers (``foodsafety.models.xgb``).

The module is config + dtype-prep only (the fit happens in the notebook), but two
of its functions carry correctness that silently breaks the train/val/test A-B:

  - ``prepare_xgb_features`` must reuse the TRAIN categories on val/test so the
    categorical codes line up across splits — a level seen only in val/test maps
    to NaN ("missing"), never to a colliding code. Misaligned codes would leak a
    different feature meaning into the held-out evaluation.
  - ``compute_scale_pos_weight`` is the CLAUDE.md-mandated imbalance handle and
    must refuse a label vector with no positives rather than divide by zero.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from foodsafety.models.baseline import ALL_FEATURES, BOOLEAN_FEATURES, NUMERIC_FEATURES
from foodsafety.models.xgb import (
    build_production_xgb,
    build_xgb_estimator,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    monotone_constraints_for,
    prepare_xgb_features,
)


def _frame(risk_tiers, inspection_types, n: int) -> pd.DataFrame:
    """Minimal frame with every ALL_FEATURES column at plausible values."""
    data: dict[str, list] = {}
    for feat in ALL_FEATURES:
        if feat == "static_risk_tier":
            data[feat] = list(risk_tiers)
        elif feat == "static_inspection_type":
            data[feat] = list(inspection_types)
        elif feat in BOOLEAN_FEATURES:
            data[feat] = [0, 1] * (n // 2) + [0] * (n % 2)
        else:  # numeric
            data[feat] = list(range(n))
    return pd.DataFrame(data)


def test_build_xgb_estimator_uses_mandated_defaults():
    est = build_xgb_estimator(scale_pos_weight=7.0)
    params = est.get_params()
    # scale_pos_weight (not SMOTE) is the imbalance handle; native categoricals on.
    assert params["scale_pos_weight"] == 7.0
    assert params["enable_categorical"] is True
    assert params["objective"] == "binary:logistic"
    # extra kwargs pass through.
    custom = build_xgb_estimator(max_depth=3, gamma=0.5)
    assert custom.get_params()["max_depth"] == 3
    assert custom.get_params()["gamma"] == 0.5


def test_prepare_xgb_features_casts_dtypes():
    df = _frame(["Risk 1 (High)", "Risk 2 (Medium)"], ["Canvass", "Complaint"], 2)
    out = prepare_xgb_features(df)
    assert list(out.columns) == ALL_FEATURES
    assert str(out["static_risk_tier"].dtype) == "category"
    assert all(str(out[c].dtype) == "int8" for c in BOOLEAN_FEATURES)
    assert all(str(out[c].dtype) == "float32" for c in NUMERIC_FEATURES)


def test_prepare_xgb_features_reuses_train_categories_across_splits():
    # Train sees two risk tiers; val sees a THIRD, unseen tier.
    train = _frame(["Risk 1 (High)", "Risk 2 (Medium)"], ["Canvass", "Complaint"], 2)
    val = _frame(["Risk 1 (High)", "Risk 3 (Low)"], ["Canvass", "Re-Inspection"], 2)

    train_prepared = prepare_xgb_features(train)
    cat_dtypes = extract_categorical_dtypes(train_prepared)
    val_prepared = prepare_xgb_features(val, categorical_dtypes=cat_dtypes)

    # Val reuses the train category universe exactly...
    assert list(val_prepared["static_risk_tier"].cat.categories) == list(
        train_prepared["static_risk_tier"].cat.categories
    )
    # ...so the unseen "Risk 3 (Low)" becomes missing (NaN code), not a new code
    # that would collide with a train level's meaning.
    assert val_prepared["static_risk_tier"].isna().any()


def test_compute_scale_pos_weight_ratio_and_no_positive_guard():
    # 8 negatives / 2 positives -> 4.0
    assert compute_scale_pos_weight(np.array([0, 0, 0, 0, 0, 0, 0, 0, 1, 1])) == 4.0
    # Accepts pandas Series too.
    assert compute_scale_pos_weight(pd.Series([0, 0, 1])) == 2.0
    # No positives -> undefined, must raise rather than divide by zero.
    with pytest.raises(ValueError):
        compute_scale_pos_weight(np.zeros(5))


def test_monotone_constraints_only_on_risk_increasing_features():
    constraints = monotone_constraints_for(ALL_FEATURES)

    # Risk-increasing features are pinned to +1...
    for feat in ("prior_fails", "n_priority_this_inspection", "was_fail"):
        assert constraints[feat] == 1
    for feat in BOOLEAN_FEATURES:  # the fired keyword-hazard flags
        assert constraints[feat] == 1

    # ...recency / calendar / categoricals stay unconstrained (absent from dict).
    for feat in ("days_since_last_inspection", "temporal_month", "static_risk_tier"):
        assert feat not in constraints
    # prior_* recency is explicitly excluded despite the prior_ prefix.
    assert "days_since_last_fail" not in constraints
    assert all(v == 1 for v in constraints.values())


def test_build_production_xgb_uses_promoted_hyperparameters():
    est = build_production_xgb(scale_pos_weight=6.5)
    params = est.get_params()
    # The CV-validated production config: shallow, fixed trees, no early stopping.
    assert params["max_depth"] == 3
    assert params["n_estimators"] == 300
    assert params["early_stopping_rounds"] is None
    assert params["scale_pos_weight"] == 6.5
    # Monotone constraints default to the full ALL_FEATURES set.
    assert params["monotone_constraints"] == monotone_constraints_for(ALL_FEATURES)


def test_build_production_xgb_constrains_only_the_given_features():
    # The forecast-only model (DR 0011) passes its reduced feature set, so the
    # constraints must be built over those columns, not all of ALL_FEATURES.
    reduced = ["prior_fails", "days_since_last_inspection"]
    est = build_production_xgb(scale_pos_weight=2.0, features=reduced)
    assert est.get_params()["monotone_constraints"] == {"prior_fails": 1}
