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

import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.linear_model import LogisticRegression

from foodsafety.config import (
    FEATURES_PATH,
    INSPECTIONS_LABELED_PATH,
    LABEL_WINDOW_DAYS,
    MODELS_DIR,
    PREDICTIONS_DIR,
    RANDOM_STATE,
    WEB_APP_DATA_DIR,
)
from foodsafety.explain.shap_drivers import tree_contributions
from foodsafety.io import storage
from foodsafety.models.baseline import (
    ALL_FEATURES,
    CURRENT_OUTCOME_FEATURES,
    FORECAST_FEATURES,
    LABEL_COL,
)
from foodsafety.models.evaluate import evaluate
from foodsafety.models.xgb import (
    build_production_xgb,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    prepare_xgb_features,
)
from foodsafety.serve.predict_batch import (
    build_scores_table,
    out_of_business_status,
    write_scores_json,
)
from foodsafety.tracking import provenance
from foodsafety.utils.time import temporal_split

REPO_ROOT = Path(__file__).resolve().parent.parent
# FEATURES_PATH / MODELS_DIR / PREDICTIONS_DIR / WEB_APP_DATA_DIR come from config and
# may be local or s3://. Metrics reports stay repo-local (small, git-committed/diffable).
SCORES_JSON_PATH = storage.join(str(WEB_APP_DATA_DIR), "scores.json")
SCORES_PARQUET_PATH = storage.join(str(PREDICTIONS_DIR), "scores.parquet")
REPORTS_METRICS_DIR = REPO_ROOT / "reports" / "metrics"

TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"
MODEL_VERSION = "xgb_monotone_sigmoid"
# Forecast-only model (Model 2) — same config, drops the current-outcome
# features; used ONLY to compute the forward-looking trend slope (DR 0011).
FORECAST_MODEL_VERSION = "xgb_forecast_sigmoid"


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
    if not storage.exists(FEATURES_PATH):
        raise SystemExit(
            f"Missing data artifact: {FEATURES_PATH} was not found. "
            "Run `make features` (scripts/build_features.py) first."
        )
    features = storage.read_parquet(FEATURES_PATH)
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
    # Target may be local or s3:// — storage creates local parents / puts S3 objects.
    model_path = storage.join(str(MODELS_DIR), f"{MODEL_VERSION}_{run_id}.joblib")
    storage.dump_joblib(served, model_path)
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

    # --- Forecast-only model (Model 2) — the forward-looking trend basis ----
    # Same production recipe (depth-3, monotone, Platt-on-margin) but trained
    # WITHOUT the current inspection's own outcome, so its per-inspection score
    # does not encode today's verdict / the mandated fail->re-inspection swing.
    # Used ONLY to compute trend_slope (DR 0011); risk_score stays Model 1.
    print("Fitting forecast-only model (Model 2) for the trend basis")
    Xtr_f = X_train.drop(columns=CURRENT_OUTCOME_FEATURES)
    Xval_f = X_val.drop(columns=CURRENT_OUTCOME_FEATURES)
    xgb_fore = build_production_xgb(scale_pos_weight=spw, features=FORECAST_FEATURES)
    xgb_fore.fit(Xtr_f, y_train, verbose=False)
    margin_val_f = xgb_fore.predict(Xval_f, output_margin=True)
    platt_f = LogisticRegression(C=1e10, solver="lbfgs").fit(margin_val_f.reshape(-1, 1), y_val)
    coef_f, inter_f = float(platt_f.coef_[0, 0]), float(platt_f.intercept_[0])
    forecast = XGBServeModel(xgb_fore, cat_dtypes, coef_f, inter_f)
    forecast_model_path = storage.join(str(MODELS_DIR), f"{FORECAST_MODEL_VERSION}_{run_id}.joblib")
    storage.dump_joblib(forecast, forecast_model_path)
    print(f"Saved forecast model → {forecast_model_path}")

    # Score EVERY inspection with Model 2 — these are the trend trajectory points
    # (history is scored, not just the latest anchor). Calibrated to a probability.
    X_full_f = prepare_xgb_features(features[ALL_FEATURES], categorical_dtypes=cat_dtypes).drop(
        columns=CURRENT_OUTCOME_FEATURES
    )
    forecast_scores = expit(coef_f * xgb_fore.predict(X_full_f, output_margin=True) + inter_f)

    # Persist the per-inspection forecast scores so export_inspection_history can
    # attach them to each event for the detail-page trend chart (DR 0011, PR-C).
    forecast_history = features[["license_id", "inspection_date"]].copy()
    forecast_history["forecast_score"] = forecast_scores.round(4)
    forecast_history_path = storage.join(str(PREDICTIONS_DIR), "forecast_history.parquet")
    storage.write_parquet(forecast_history, forecast_history_path)
    print(
        f"Wrote {forecast_history_path}: {len(forecast_history):,} per-inspection forecast scores"
    )

    # --- Score every restaurant + export JSON -----------------------------
    # Closure status comes from the labeled all-events parquet — the features
    # frame has no Out of Business rows (they aren't scoreable inspections).
    print(f"Deriving out-of-business status from {INSPECTIONS_LABELED_PATH}")
    closure = out_of_business_status(storage.read_parquet(INSPECTIONS_LABELED_PATH))
    print(f"  {int(closure['is_out_of_business'].sum()):,} licenses closed at latest event")

    print("Building scores table (latest inspection per license; TreeSHAP drivers)")
    scores = build_scores_table(
        served,
        features,
        ALL_FEATURES,
        n_drivers=5,
        contributions_fn=lambda X: served.contributions(X)[0],
        trend_scores=forecast_scores,
        closure_status=closure,
    )
    storage.write_parquet(scores, SCORES_PARQUET_PATH)
    print(f"Wrote {SCORES_PARQUET_PATH}: {len(scores):,} restaurants")
    print("Tier distribution:", scores["risk_tier"].value_counts().to_dict())

    # Calibration triple: a = -coef, b = -inter (app uses logit = -(a*margin+b)),
    # intercept = the TreeSHAP base margin (so intercept + Σshap == raw margin).
    _, base_margin = served.contributions(features[ALL_FEATURES].head(1))
    calibration = {"a": -coef, "b": -inter, "intercept": float(base_margin)}
    print(f"Calibration triple: {calibration}")

    write_scores_json(
        scores,
        SCORES_JSON_PATH,
        # 0.6.0 adds is_out_of_business / closed_since (DR 0014).
        schema_version="0.6.0",
        model_version=MODEL_VERSION,
        calibration=calibration,
    )
    print(f"Wrote {SCORES_JSON_PATH}")


if __name__ == "__main__":
    main()
