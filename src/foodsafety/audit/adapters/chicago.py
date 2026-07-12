"""Chicago adapter — build the test-split AuditFrame from the served XGB model.

Reproduces the evaluation basis of ``scripts/retrain_xgb_sigmoid.py``: filter the
right-truncated rows, take the chronological **test** split (``inspection_date >=
VAL_END``), and score it with the production model. This is the honest audit basis
— realised 180-day labels paired with the risk the model assigns — not the
forward-looking ``scores.json`` (whose labels are not yet known).

The model is **refit** from the same recipe (depth-3 monotone XGB + Platt on the
val margin) rather than unpickled, because the served ``XGBServeModel`` is pickled
against the retrain script's ``__main__`` and won't load elsewhere. The recipe is
deterministic (``RANDOM_STATE``), so the refit reproduces the deployed model.

"Flagged" is the deployed tier rule (``assign_risk_tiers``) applied to the test
scores at the city's label prevalence: flagged = High tier. Chicago has no cuisine
field, so that column is left null (the cuisine axis simply doesn't audit here).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.linear_model import LogisticRegression

from foodsafety.audit import frame
from foodsafety.config import FEATURES_PATH
from foodsafety.features.license_features import normalize_facility_type
from foodsafety.io import storage
from foodsafety.models.baseline import ALL_FEATURES, LABEL_COL
from foodsafety.models.xgb import (
    build_production_xgb,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    prepare_xgb_features,
)
from foodsafety.serve.predict_batch import assign_risk_tiers
from foodsafety.utils.time import temporal_split

# Same chronological cutoffs the production retrain uses.
TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"


class ChicagoAdapter:
    """Builds the Chicago ``AuditFrame`` from local features + a refit of the model."""

    city = "chicago"

    def __init__(self, features_path=FEATURES_PATH):
        self.features_path = features_path

    def _score_test(self, split) -> np.ndarray:
        """Refit the production recipe on train, calibrate on val, score test."""
        y_train = split.train[LABEL_COL].astype(int).to_numpy()
        y_val = split.val[LABEL_COL].astype(int).to_numpy()

        x_train = prepare_xgb_features(split.train[ALL_FEATURES])
        cat_dtypes = extract_categorical_dtypes(x_train)
        x_val = prepare_xgb_features(split.val[ALL_FEATURES], categorical_dtypes=cat_dtypes)
        x_test = prepare_xgb_features(split.test[ALL_FEATURES], categorical_dtypes=cat_dtypes)

        xgb_est = build_production_xgb(scale_pos_weight=compute_scale_pos_weight(y_train))
        xgb_est.fit(x_train, y_train, verbose=False)
        # Platt (sigmoid) on the raw val margin — the shipped calibration contract.
        margin_val = xgb_est.predict(x_val, output_margin=True)
        platt = LogisticRegression(C=1e10, solver="lbfgs").fit(margin_val.reshape(-1, 1), y_val)
        coef, inter = float(platt.coef_[0, 0]), float(platt.intercept_[0])
        margin_test = xgb_est.predict(x_test, output_margin=True)
        return expit(coef * margin_test + inter)

    def build_audit_frame(self) -> pd.DataFrame:
        features = storage.read_parquet(self.features_path)
        # Right-truncated rows have under-counted labels — excluded from modeling
        # and evaluation, same as the retrain path.
        if "right_truncated" in features.columns:
            features = features.loc[~features["right_truncated"]].reset_index(drop=True)

        split = temporal_split(features, train_end=TRAIN_END, val_end=VAL_END)
        test = split.test.reset_index(drop=True)
        p_test = self._score_test(split)

        # Deployed tier rule at the city's label prevalence; flagged = High.
        base_rate = float(features[LABEL_COL].mean())
        tiers, _ = assign_risk_tiers(pd.Series(p_test, index=test.index), base_rate)

        out = pd.DataFrame(
            {
                "city": "chicago",
                "license_id": test["license_id"].astype("string"),
                "as_of_date": pd.to_datetime(test["as_of_date"]),
                "y_true": test[LABEL_COL].astype("int8"),
                "y_score": p_test.astype("float64"),
                "risk_tier": tiers.astype("string"),
                "lat": test["latitude"].astype("float64"),
                "lon": test["longitude"].astype("float64"),
                "facility_type_norm": test["facility_type"]
                .map(normalize_facility_type)
                .astype("string"),
                "license_age_days": test["license_age_days"].astype("float64"),
                # Neighborhood = 5-digit ZIP (the geographic unit the existing
                # group audit uses); community-area boundaries are a later refinement.
                "neighborhood": test["static_zip"].astype("string"),
                "cuisine": pd.Series(pd.NA, index=test.index, dtype="string"),
                "forecast_score": np.nan,  # Model 2 wired in a follow-up step
            }
        )
        out = frame.add_tenure_bucket(out)
        frame.validate(out)
        return out
