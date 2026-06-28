"""Train + serve the production XGBoost model (depth-3 + monotone risk constraints).

This replaces the LogReg baseline as the served estimator (DR 0002/0009): the
shallow monotone XGB beats LogReg on both PR-AUC and precision@10% in 5/6
expanding-window CV folds. The serving contract is unchanged — same
`scores.json` schema, same per-establishment driver waterfall — only the model
and the explainer change:

  * Risk score = Platt(sigmoid) calibration fit on the XGB **raw margin** (so the
    shipped `calibration {a, b, intercept}` reconstructs the waterfall exactly,
    like the LogReg path did).
  * `top_drivers[].shap` = XGBoost **native TreeSHAP** (`pred_contribs`) in
    margin/log-odds space — no `shap` package dependency. `calibration.intercept`
    is the TreeSHAP base margin, so `intercept + Σ shap == raw margin` per row and
    the app's `computeWaterfall` reconciles to the gauge unchanged.

Run with the project's Python:
    PYTHONPATH=src uv run python scripts/retrain_xgb_sigmoid.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.linear_model import LogisticRegression

from foodsafety.config import LABEL_WINDOW_DAYS, RANDOM_STATE
from foodsafety.explain.shap_drivers import tree_contributions
from foodsafety.models.baseline import ALL_FEATURES, LABEL_COL
from foodsafety.models.evaluate import evaluate
from foodsafety.models.xgb import (
    build_production_xgb,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    prepare_xgb_features,
)
from foodsafety.serve.predict_batch import build_scores_table, write_scores_json
from foodsafety.tracking import provenance
from foodsafety.utils.time import temporal_split

REPO_ROOT = Path(__file__).resolve().parent.parent
FEATURES_PATH = REPO_ROOT / "data" / "processed" / "features.parquet"
MODELS_DIR = REPO_ROOT / "data" / "models"
PRED_DIR = REPO_ROOT / "data" / "predictions"
SCORES_JSON_PATH = REPO_ROOT / "app" / "public" / "data" / "scores.json"
REPORTS_METRICS_DIR = REPO_ROOT / "reports" / "metrics"

TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"
MODEL_VERSION = "xgb_monotone_sigmoid"


class XGBServeModel:
    """Fitted XGB + Platt-on-margin, presented as a `model` for build_scores_table.

    ``predict_proba(X)`` returns the calibrated risk; ``contributions(X)`` returns
    margin-space TreeSHAP contributions (and the base margin). Both prepare the
    raw frame to the dtypes the booster trained on.
    """

    def __init__(self, xgb_estimator, categorical_dtypes, platt_coef, platt_intercept):
        self.xgb = xgb_estimator
        self.categorical_dtypes = categorical_dtypes
        self.coef = float(platt_coef)
        self.intercept = float(platt_intercept)

    def _prep(self, X: pd.DataFrame) -> pd.DataFrame:
        return prepare_xgb_features(X, categorical_dtypes=self.categorical_dtypes)

    def margin(self, X: pd.DataFrame) -> np.ndarray:
        return self.xgb.predict(self._prep(X), output_margin=True)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        # Platt on the raw margin: logit(p) = coef * margin + intercept.
        p = expit(self.coef * self.margin(X) + self.intercept)
        return np.column_stack([1.0 - p, p])

    def contributions(self, X: pd.DataFrame) -> tuple[pd.DataFrame, float]:
        return tree_contributions(self.xgb, self._prep(X), list(ALL_FEATURES))


def main() -> None:
    print(f"Loading {FEATURES_PATH}")
    if not FEATURES_PATH.exists():
        raise SystemExit(
            "Missing data artifact: data/processed/features.parquet was not found. "
            "Run notebooks/03_feature_engineering.ipynb first."
        )
    features = pd.read_parquet(FEATURES_PATH)
    print(f"  shape: {features.shape}")

    # Drop right-truncated rows from modeling (under-counted labels); keep the
    # full set for scoring the home page — same discipline as the LogReg path.
    if "right_truncated" in features.columns:
        features_modelable = features.loc[~features["right_truncated"]].reset_index(drop=True)
    else:
        features_modelable = features
    n_dropped = len(features) - len(features_modelable)
    if n_dropped:
        print(
            f"  filtered {n_dropped:,} right-truncated rows from modeling; full set kept for scoring"
        )

    print(f"Temporal split (train_end={TRAIN_END}, val_end={VAL_END})")
    split = temporal_split(features_modelable, train_end=TRAIN_END, val_end=VAL_END)
    print(f"  train n={len(split.train):,}  val n={len(split.val):,}  test n={len(split.test):,}")

    y_train = split.train[LABEL_COL].astype(int).to_numpy()
    y_val = split.val[LABEL_COL].astype(int).to_numpy()
    y_test = split.test[LABEL_COL].astype(int).to_numpy()

    X_train = prepare_xgb_features(split.train[ALL_FEATURES])
    cat_dtypes = extract_categorical_dtypes(X_train)
    X_val = prepare_xgb_features(split.val[ALL_FEATURES], categorical_dtypes=cat_dtypes)

    print("Fitting production XGB (depth-3, monotone) on train")
    spw = compute_scale_pos_weight(y_train)
    xgb_est = build_production_xgb(scale_pos_weight=spw)
    xgb_est.fit(X_train, y_train, verbose=False)

    # Platt (sigmoid) calibration fit on the XGB RAW MARGIN of val. We fit it as
    # a 1-D logistic so the shipped {a, b} live in margin space (the contract the
    # app waterfall expects), unlike CalibratedClassifierCV which would calibrate
    # XGBClassifier's predict_proba and double-squash.
    print("Calibrating (Platt/sigmoid) on val raw margin")
    margin_val = xgb_est.predict(X_val, output_margin=True)
    platt = LogisticRegression(C=1e10, solver="lbfgs").fit(margin_val.reshape(-1, 1), y_val)
    coef, inter = float(platt.coef_[0, 0]), float(platt.intercept_[0])
    served = XGBServeModel(xgb_est, cat_dtypes, coef, inter)

    p_val = served.predict_proba(split.val[ALL_FEATURES])[:, 1]
    p_test = served.predict_proba(split.test[ALL_FEATURES])[:, 1]
    val_metrics = evaluate(y_val, p_val).to_dict()
    test_metrics = evaluate(y_test, p_test).to_dict()
    print("Val:", json.dumps({k: round(v, 4) for k, v in val_metrics.items()}))
    print("Test:", json.dumps({k: round(v, 4) for k, v in test_metrics.items()}))

    # --- Provenance + tracked metrics -------------------------------------
    prov = provenance(FEATURES_PATH, list(ALL_FEATURES), REPO_ROOT)
    run_id = prov["run_id"]
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / f"{MODEL_VERSION}_{run_id}.joblib"
    joblib.dump(served, model_path)
    print(f"Saved model → {model_path}")

    REPORTS_METRICS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "model": MODEL_VERSION,
        "run_id": run_id,
        "git_commit": prov["git_commit"],
        "git_dirty": prov["git_dirty"],
        "calibration": "platt_on_margin",
        "config": "depth-3, monotone risk constraints, n_estimators=300, lr=0.05",
        "right_truncation_filtered": int(n_dropped),
        "feature_set_version": prov["feature_set_version"],
        "features_sha256": prov["features_sha256"],
        "label_window_days": LABEL_WINDOW_DAYS,
        "random_state": RANDOM_STATE,
        "date_trained": datetime.now().strftime("%Y-%m-%d"),
        "val": val_metrics,
        "test": test_metrics,
    }
    report_path = REPORTS_METRICS_DIR / f"{MODEL_VERSION}_{run_id}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Saved metrics report → {report_path}")

    # --- Score every restaurant + export JSON -----------------------------
    print("Building scores table (latest inspection per license; TreeSHAP drivers)")
    scores = build_scores_table(
        served,
        features,
        ALL_FEATURES,
        n_drivers=5,
        contributions_fn=lambda X: served.contributions(X)[0],
    )
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    scores.to_parquet(PRED_DIR / "scores.parquet")
    print(f"Wrote scores.parquet: {len(scores):,} restaurants")
    print("Tier distribution:", scores["risk_tier"].value_counts().to_dict())

    # Calibration triple: a = -coef, b = -inter (app uses logit = -(a*margin+b)),
    # intercept = the TreeSHAP base margin (so intercept + Σshap == raw margin).
    _, base_margin = served.contributions(features[ALL_FEATURES].head(1))
    calibration = {"a": -coef, "b": -inter, "intercept": float(base_margin)}
    print(f"Calibration triple: {calibration}")

    write_scores_json(
        scores,
        SCORES_JSON_PATH,
        schema_version="0.4.0",
        model_version=MODEL_VERSION,
        calibration=calibration,
    )
    size_mb = SCORES_JSON_PATH.stat().st_size / 1024 / 1024
    print(f"Wrote {SCORES_JSON_PATH} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
