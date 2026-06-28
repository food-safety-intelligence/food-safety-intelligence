"""XGBoost gradient boosting model.

This module inherits the canonical feature contract from
``foodsafety.models.baseline`` so the XGBoost work is a clean A/B against the
logistic-regression baseline — same feature set, same split cutoffs, same
eval suite. Different estimator, that's it.

Per CLAUDE.md:
  - ``scale_pos_weight`` (not SMOTE) for class imbalance.
  - ``enable_categorical=True`` so XGBoost partitions categorical levels
    directly — no one-hot blowup, no over-collapsing of rare ZIPs.
  - Same temporal split as the baseline notebook; never random shuffle.
  - To be considered the production estimator, the trained model must clear
    the baseline on **both** PR-AUC and precision@10% on the held-out test.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from foodsafety.config import RANDOM_STATE
from foodsafety.models.baseline import (
    ALL_FEATURES,
    BOOLEAN_FEATURES,
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
)


def build_xgb_estimator(
    *,
    n_estimators: int = 800,
    max_depth: int = 6,
    learning_rate: float = 0.05,
    subsample: float = 0.85,
    colsample_bytree: float = 0.85,
    min_child_weight: float = 10.0,
    reg_lambda: float = 1.0,
    scale_pos_weight: float | None = None,
    early_stopping_rounds: int | None = 40,
    random_state: int = RANDOM_STATE,
    **extra,
) -> XGBClassifier:
    """Construct an ``XGBClassifier`` with project defaults.

    The defaults are tuned to be reasonable starting points for this dataset
    (~80 k train rows, ~30 features):

    - ``max_depth=6`` — moderate depth; deeper trees risk memorising
      rare-ZIP one-hots even with partition-based categorical splits.
    - ``subsample`` / ``colsample_bytree`` = 0.85 — light row + feature
      bagging regularisation.
    - ``min_child_weight=10`` — prevents tiny leaf nodes that fit noise.
    - ``learning_rate=0.05`` with ``n_estimators=800`` and
      ``early_stopping_rounds=40`` — the model finds its own optimal tree
      count given the validation curve.

    Pass ``scale_pos_weight`` to handle class imbalance. The recommended
    value is ``n_negative / n_positive`` computed from the train labels (see
    :func:`compute_scale_pos_weight`). This is the CLAUDE.md-mandated
    alternative to SMOTE — it re-weights the loss without resampling.

    For early stopping, pass ``eval_set=[(X_val, y_val)]`` to ``.fit()``.
    Set ``early_stopping_rounds=None`` to disable early stopping (useful for
    later fitting on train+val combined for the final scoring run).
    """
    return XGBClassifier(
        objective="binary:logistic",
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=learning_rate,
        subsample=subsample,
        colsample_bytree=colsample_bytree,
        min_child_weight=min_child_weight,
        reg_lambda=reg_lambda,
        scale_pos_weight=scale_pos_weight,
        tree_method="hist",
        enable_categorical=True,  # native categorical partition splits
        random_state=random_state,
        n_jobs=-1,
        eval_metric="aucpr",
        early_stopping_rounds=early_stopping_rounds,
        verbosity=0,
        **extra,
    )


def prepare_xgb_features(
    df: pd.DataFrame,
    *,
    categorical_dtypes: dict | None = None,
) -> pd.DataFrame:
    """Cast columns to the dtypes XGBoost expects.

    Categorical handling matters for split alignment across train/val/test:

    - When ``categorical_dtypes is None`` we infer from ``df`` (use this on
      the train slice; train defines the canonical categories).
    - When provided, we reuse those exact categories so codes line up across
      splits. Categories present in val/test but absent from train become
      ``NaN`` in the codes — XGBoost handles that natively as "missing".

    Args:
        df: source frame; must contain every column in ``ALL_FEATURES``.
        categorical_dtypes: optional dict ``{col_name: pd.CategoricalDtype}``
            from a previously-prepared frame. Use the train-prepared dtypes
            on val/test.

    Returns:
        New DataFrame with ``ALL_FEATURES`` columns at appropriate dtypes.
    """
    out = df[ALL_FEATURES].copy()

    for c in CATEGORICAL_FEATURES:
        if categorical_dtypes is not None and c in categorical_dtypes:
            # Reuse train's categories so codes align across splits.
            # set_categories restricts to the train universe — levels absent from
            # train become NaN ("missing" to XGBoost), never a colliding code.
            out[c] = out[c].astype("category").cat.set_categories(categorical_dtypes[c].categories)
        else:
            out[c] = out[c].astype("category")

    for c in BOOLEAN_FEATURES:
        out[c] = out[c].astype("int8")

    for c in NUMERIC_FEATURES:
        out[c] = out[c].astype("float32")

    return out


def extract_categorical_dtypes(df: pd.DataFrame) -> dict:
    """Pull the categorical dtypes off a prepared frame so val/test can reuse them."""
    return {c: df[c].dtype for c in CATEGORICAL_FEATURES if c in df.columns}


# Features whose risk reading is monotone non-decreasing in their value: counts
# of prior bad events, the current inspection's own outcome/violation counts, and
# the fired keyword-hazard flags. Recency (``days_since_*``), calendar, license
# age, and categoricals are left unconstrained (0).
def monotone_constraints_for(features: list[str]) -> dict[str, int]:
    """Map risk-increasing features to a ``+1`` monotone constraint.

    On a forward-time split the ``prior_*`` counts grow over calendar time, so
    test rows carry values above the training range; unconstrained axis-aligned
    trees saturate at the top training threshold and lose rank resolution at the
    top of the list (where precision@10% lives). Forcing monotonicity in the
    risk counts preserves that top-decile ordering and yields a cleaner SHAP
    story. Empirically this is what lifts XGB past the LogReg baseline (DR 0002).
    """
    return {
        f: 1
        for f in features
        if (f.startswith("prior_") and "days_since" not in f)
        or f.startswith("flag_kw_")
        or f in {"was_fail", "n_priority_this_inspection", "n_core_this_inspection"}
    }


def build_production_xgb(
    *, scale_pos_weight: float, features: list[str] | None = None
) -> XGBClassifier:
    """The promoted production XGB: shallow (depth-3) + monotone risk constraints.

    The CV-validated winner over the LogReg baseline (beats it on both PR-AUC and
    precision@10% in 5/6 expanding-window folds — see DR 0002/0009 and
    docs/model-experiments.md). Fixed ``n_estimators`` with early stopping off so the
    served run is deterministic. ``max_depth=3`` (vs the experiment default 6):
    the signal is low-order, so deep trees over-fragment it and lose the forward-
    time top decile.

    ``features`` defaults to the full ``ALL_FEATURES``. The forecast-only model
    (DR 0011) passes its reduced set (``FORECAST_FEATURES``) so the monotone
    constraints are built over the columns it actually trains on — the dropped
    current-outcome features simply fall out of the constraint map.
    """
    feats = list(features) if features is not None else list(ALL_FEATURES)
    return build_xgb_estimator(
        n_estimators=300,
        max_depth=3,
        learning_rate=0.05,
        scale_pos_weight=scale_pos_weight,
        early_stopping_rounds=None,
        monotone_constraints=monotone_constraints_for(feats),
    )


def compute_scale_pos_weight(y) -> float:
    """``n_negative / n_positive`` — the CLAUDE.md-mandated imbalance handle.

    Use on the train labels only; never on test (that would leak the test
    positive rate into the model).
    """
    y_arr = np.asarray(y)
    n_pos = int((y_arr == 1).sum())
    n_neg = int((y_arr == 0).sum())
    if n_pos == 0:
        raise ValueError("y has no positive labels; scale_pos_weight is undefined.")
    return n_neg / n_pos
