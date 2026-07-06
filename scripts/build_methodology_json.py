"""Generate ``app/public/data/methodology.json`` for the "How this works" page.

Computes the operating-point table + headline metrics for the served model
(production XGBoost, depth-3 + monotone constraints) on the time-held-out test
split and writes them as JSON for the Next.js methodology page to read. This is
the batch-to-JSON contract — the web app never runs the model; it renders
precomputed numbers from this file.

Operating points are rank-based (precision / recall / lift at top-k), so they
are identical for the uncalibrated model and its Platt-calibrated served form.
We fit the model here for a fast, self-contained run, mirroring
``retrain_xgb_sigmoid.py`` (same split, same config, same Platt-on-margin).

Run: ``PYTHONPATH=src uv run python scripts/build_methodology_json.py``
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.linear_model import LogisticRegression

from foodsafety.config import FEATURES_PATH, WEB_APP_DATA_DIR
from foodsafety.explain.feature_labels import display_name
from foodsafety.explain.shap_drivers import top_drivers_for_row, tree_contributions
from foodsafety.io import storage
from foodsafety.models.baseline import ALL_FEATURES, LABEL_COL
from foodsafety.models.evaluate import evaluate, operating_point_table
from foodsafety.models.xgb import (
    build_production_xgb,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    prepare_xgb_features,
)
from foodsafety.serve.predict_batch import RISK_TIER_THRESHOLDS
from foodsafety.tracking import provenance

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = storage.join(str(WEB_APP_DATA_DIR), "methodology.json")

# Chronological split — must match the served model: train through 2024-07,
# the 2024-07 → 2025-07 year is the calibration/validation slice, and 2025-07
# onward is the time-held-out test. Never a random shuffle.
TRAIN_END = pd.Timestamp("2024-07-01")
TEST_START = pd.Timestamp("2025-07-01")
K_FRACS = (0.05, 0.10, 0.20, 0.30, 0.50)

N_GLOBAL_FEATURES = 12
N_WATERFALL_DRIVERS = 4


class _ServedXGB:
    """The served XGB + Platt-on-margin, fit here for a self-contained run.

    Mirrors ``retrain_xgb_sigmoid.XGBServeModel`` (same config + calibration) so
    the methodology numbers describe the model that feeds ``scores.json``.
    """

    def __init__(self, train: pd.DataFrame, val: pd.DataFrame):
        y_train = train[LABEL_COL].astype(int).to_numpy()
        X_train = prepare_xgb_features(train[ALL_FEATURES])
        self.cat_dtypes = extract_categorical_dtypes(X_train)
        self.est = build_production_xgb(scale_pos_weight=compute_scale_pos_weight(y_train))
        self.est.fit(X_train, y_train, verbose=False)
        X_val = prepare_xgb_features(val[ALL_FEATURES], categorical_dtypes=self.cat_dtypes)
        margin_val = self.est.predict(X_val, output_margin=True)
        platt = LogisticRegression(C=1e10, solver="lbfgs").fit(
            margin_val.reshape(-1, 1), val[LABEL_COL].astype(int)
        )
        self.coef, self.inter = float(platt.coef_[0, 0]), float(platt.intercept_[0])

    def _prep(self, X: pd.DataFrame) -> pd.DataFrame:
        return prepare_xgb_features(X, categorical_dtypes=self.cat_dtypes)

    def risk(self, X: pd.DataFrame) -> np.ndarray:
        margin = self.est.predict(self._prep(X), output_margin=True)
        return expit(self.coef * margin + self.inter)

    def contributions(self, X: pd.DataFrame) -> tuple[pd.DataFrame, float]:
        return tree_contributions(self.est, self._prep(X), list(ALL_FEATURES))


def global_feature_impact(model: _ServedXGB, test: pd.DataFrame) -> list[dict]:
    """Mean |margin (log-odds) contribution| per feature on the test set — the
    model's global feature impact (TreeSHAP). Ranked, top N, with plain names."""
    contrib, _ = model.contributions(test[ALL_FEATURES])
    mean_abs = contrib.abs().mean().sort_values(ascending=False)
    return [
        {
            "feature": feat,
            "label": display_name(feat),
            "mean_abs_logodds": round(float(mean_abs[feat]), 4),
        }
        for feat in mean_abs.head(N_GLOBAL_FEATURES).index
    ]


def worked_waterfall(model: _ServedXGB, test: pd.DataFrame) -> dict:
    """One worked example: how an establishment's TreeSHAP drivers add up — in
    CALIBRATED log-odds — to the published probability.

    The Platt map is linear in the raw margin M: ``calibrated_logit = coef*M +
    inter``, and ``M = base_margin + Σ contributions`` (TreeSHAP additivity).
    Scaling each contribution by ``coef`` and folding ``inter`` into the base
    term makes the calibrated contributions additive and sum exactly to the
    calibrated logit — so ``sigmoid(base + Σdrivers + other)`` lands exactly on
    the establishment's probability (no reconciliation gap with the gauge).
    """
    risk = model.risk(test[ALL_FEATURES])
    contrib, base_margin = model.contributions(test[ALL_FEATURES])
    slope = model.coef  # calibrated contribution = coef * raw contribution

    # Deterministic, pedagogically clear example: highest-probability row whose
    # top drivers include BOTH a risk-raising and a risk-lowering factor.
    order = np.argsort(-risk)
    chosen = int(order[0])
    for idx in order[:300]:
        drivers = top_drivers_for_row(
            test.iloc[int(idx)][ALL_FEATURES], contrib.iloc[int(idx)], k=N_WATERFALL_DRIVERS
        )
        if any(d.shap > 0 for d in drivers) and any(d.shap < 0 for d in drivers):
            chosen = int(idx)
            break

    row_values = test.iloc[chosen][ALL_FEATURES]
    raw_contrib = contrib.iloc[chosen]
    drivers = top_drivers_for_row(row_values, raw_contrib, k=N_WATERFALL_DRIVERS)
    top_feats = {d.feature for d in drivers}

    base_cal = slope * base_margin + model.inter
    driver_out = [
        {"feature": d.feature, "label": d.label, "contribution": round(slope * d.shap, 4)}
        for d in drivers
    ]
    other_cal = slope * float(
        raw_contrib[[f for f in raw_contrib.index if f not in top_feats]].sum()
    )
    total_cal = base_cal + slope * float(raw_contrib.sum())
    p = float(expit(total_cal))

    # Sanity: the additive calibrated logit must reproduce the model's own
    # probability for this row (else the page would show a fictitious total).
    assert abs(p - float(risk[chosen])) < 1e-6, (p, float(risk[chosen]))

    return {
        "base": round(base_cal, 4),
        "drivers": driver_out,
        "other": round(other_cal, 4),
        "total_logit": round(total_cal, 4),
        "probability": round(p, 4),
    }


def served_tier_shares() -> dict[str, float] | None:
    """Share of *scored establishments* in each tier, from the served
    ``scores.json`` totals — the population the app actually displays. Lets the
    methodology page show shares without itself loading the 18 MB scores file.

    Returns ``None`` if ``scores.json`` isn't built yet (fresh clone before the
    serving script runs); the page then just omits the Share column.
    """
    scores_path = storage.join(str(WEB_APP_DATA_DIR), "scores.json")
    if not storage.exists(scores_path):
        return None
    try:
        counts = json.loads(storage.read_text(scores_path))["totals"]["tier_counts"]
    except (KeyError, json.JSONDecodeError):
        return None
    total = sum(counts.values())
    return {label: count / total for label, count in counts.items()} if total else None


def risk_tier_bands(shares: dict[str, float] | None = None) -> list[dict]:
    """Score→tier bands for the page, derived from the served
    ``RISK_TIER_THRESHOLDS`` so the page can't drift from ``score_to_tier``."""
    bands: list[dict] = []
    lo = 0.0
    for threshold, tier in RISK_TIER_THRESHOLDS:
        hi = None if threshold > 1.0 else round(threshold, 4)
        band: dict = {"label": tier, "min": round(lo, 4), "max": hi}
        if shares is not None and tier in shares:
            band["share"] = round(shares[tier], 4)
        bands.append(band)
        lo = threshold
    return bands


def main() -> None:
    if not storage.exists(FEATURES_PATH):
        raise SystemExit(
            f"Missing {FEATURES_PATH}. Run `make features` (scripts/build_features.py) "
            "to build the feature parquet first."
        )

    df = storage.read_parquet(FEATURES_PATH)
    df["inspection_date"] = pd.to_datetime(df["inspection_date"])
    # Served basis: drop burn-in (no label) and right-truncated rows (their
    # forward window runs past the data, so their labels are under-counted).
    df = df[(~df["is_burnin"]) & (~df["right_truncated"])].dropna(subset=[LABEL_COL])

    train = df[df["inspection_date"] < TRAIN_END]
    val = df[(df["inspection_date"] >= TRAIN_END) & (df["inspection_date"] < TEST_START)]
    test = df[df["inspection_date"] >= TEST_START]

    model = _ServedXGB(train, val)
    scores = model.risk(test[ALL_FEATURES])
    y = test[LABEL_COL].astype(int).to_numpy()

    report = evaluate(y, scores)
    table = operating_point_table(y, scores, k_fracs=K_FRACS)

    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        # Production XGBoost (depth-3 + monotone). Operating points + PR/ROC-AUC
        # are rank-based, identical to the Platt-calibrated served form.
        "model_version": "xgb_monotone",
        "provenance": provenance(FEATURES_PATH, ALL_FEATURES, REPO_ROOT),
        "test": {
            "n": int(len(test)),
            "prevalence": round(float(report.positive_rate), 4),
            "events": int(y.sum()),
            "split_from": TEST_START.date().isoformat(),
        },
        "headline": {
            "pr_auc": round(float(report.pr_auc), 4),
            "roc_auc": round(float(report.roc_auc), 4),
            "top_decile_lift": round(float(report.top_decile_lift), 2),
        },
        "risk_tiers": risk_tier_bands(served_tier_shares()),
        "operating_points": [
            {
                "frac": float(row.inspect_top_frac),
                "n_flagged": int(row.n_flagged),
                "precision": float(row.precision),
                "recall": float(row.recall),
                "lift": float(row.lift),
                "events_caught": int(row.events_caught),
            }
            for row in table.itertuples()
        ],
        # Global feature impact (mean |log-odds| TreeSHAP on test) for the bar.
        "global_importance": global_feature_impact(model, test),
        # One anonymised worked example whose calibrated drivers sum to its score.
        "waterfall": worked_waterfall(model, test),
    }

    # OUTPUT_PATH may be local or s3:// — route through storage (creates local parents).
    storage.write_text(json.dumps(payload, indent=2) + "\n", OUTPUT_PATH)
    print(
        f"wrote {OUTPUT_PATH}: "
        f"{len(payload['operating_points'])} operating points, "
        f"PR-AUC {payload['headline']['pr_auc']}, test n={payload['test']['n']}"
    )


if __name__ == "__main__":
    main()
