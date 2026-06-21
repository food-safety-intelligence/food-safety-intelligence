"""Generate ``app/public/data/methodology.json`` for the "How this works" page.

Computes the operating-point table + headline metrics for the served baseline
on the time-held-out test split and writes them as JSON for the Next.js
methodology page to read. This is the batch-to-JSON contract — the web app
never runs the model; it renders precomputed numbers from this file.

Operating points are rank-based (precision / recall / lift at top-k), so they
are identical for the uncalibrated baseline and its sigmoid-calibrated served
form. We fit the baseline here for a fast, self-contained run.

Run: ``PYTHONPATH=src uv run python scripts/build_methodology_json.py``
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.frozen import FrozenEstimator

from foodsafety.explain.feature_labels import display_name
from foodsafety.explain.shap_drivers import (
    linear_contributions,
    top_drivers_for_row,
)
from foodsafety.models.baseline import ALL_FEATURES, LABEL_COL, build_baseline_pipeline
from foodsafety.models.evaluate import evaluate, operating_point_table
from foodsafety.tracking import provenance

REPO_ROOT = Path(__file__).resolve().parents[1]
FEATURES_PATH = REPO_ROOT / "data" / "processed" / "features.parquet"
OUTPUT_PATH = REPO_ROOT / "app" / "public" / "data" / "methodology.json"

# Chronological split — must match the served model: train through 2024-07,
# the 2024-07 → 2025-07 year is the calibration/validation slice, and 2025-07
# onward is the time-held-out test. Never a random shuffle.
TRAIN_END = pd.Timestamp("2024-07-01")
TEST_START = pd.Timestamp("2025-07-01")
K_FRACS = (0.05, 0.10, 0.20, 0.30, 0.50)

# How many features to show in the global-impact bar chart, and how many
# drivers to itemise in the worked waterfall (rest roll into "other").
N_GLOBAL_FEATURES = 12
N_WATERFALL_DRIVERS = 4


def _sigmoid(x: float) -> float:
    return float(1.0 / (1.0 + np.exp(-x)))


def global_feature_impact(pipe, test: pd.DataFrame) -> list[dict]:
    """Mean |log-odds contribution| per feature on the test set — the model's
    global feature impact (notebook 06 §4). Ranked, top N, with plain names."""
    contrib = linear_contributions(pipe, test[ALL_FEATURES], original_features=list(ALL_FEATURES))
    mean_abs = contrib.abs().mean().sort_values(ascending=False)
    return [
        {
            "feature": feat,
            "label": display_name(feat),
            "mean_abs_logodds": round(float(mean_abs[feat]), 4),
        }
        for feat in mean_abs.head(N_GLOBAL_FEATURES).index
    ]


def worked_waterfall(pipe, calibrated, test: pd.DataFrame) -> dict:
    """One worked example: how an establishment's drivers add up — in CALIBRATED
    log-odds — to the published probability.

    The Platt calibration is a monotone linear map of the raw logit L:
        calibrated_logit = -(a*L + b),  p = sigmoid(calibrated_logit).
    Since L = intercept + Σ contributions, scaling every contribution by -a and
    folding -b into the base term makes the CALIBRATED contributions additive and
    sum exactly to calibrated_logit — so sigmoid(base + Σdrivers + other) lands
    exactly on the establishment's probability (no reconciliation gap with the
    gauge). The example is anonymised — it teaches the math, not a named place.
    """
    sig = calibrated.calibrated_classifiers_[0].calibrators[0]
    a, b = float(sig.a_), float(sig.b_)
    slope = -a  # calibrated contribution = slope * raw contribution

    intercept = float(pipe.named_steps["model"].intercept_[0])
    p_test = calibrated.predict_proba(test[ALL_FEATURES])[:, 1]
    contrib = linear_contributions(pipe, test[ALL_FEATURES], original_features=list(ALL_FEATURES))

    # Pick a pedagogically clear, deterministic example: scanning from the
    # highest-probability rows, take the first whose top drivers include BOTH a
    # risk-raising and a risk-lowering factor (so the waterfall shows both
    # directions). Fall back to the single highest-probability row.
    order = np.argsort(-p_test)
    chosen = int(order[0])
    for idx in order[:300]:
        row_contrib = contrib.iloc[int(idx)]
        drivers = top_drivers_for_row(
            test.iloc[int(idx)][ALL_FEATURES], row_contrib, k=N_WATERFALL_DRIVERS
        )
        if any(d.shap > 0 for d in drivers) and any(d.shap < 0 for d in drivers):
            chosen = int(idx)
            break

    row_values = test.iloc[chosen][ALL_FEATURES]
    raw_contrib = contrib.iloc[chosen]
    drivers = top_drivers_for_row(row_values, raw_contrib, k=N_WATERFALL_DRIVERS)
    top_feats = {d.feature for d in drivers}

    base_cal = slope * intercept - b
    driver_out = [
        {"feature": d.feature, "label": d.label, "contribution": round(slope * d.shap, 4)}
        for d in drivers
    ]
    other_cal = slope * float(
        raw_contrib[[f for f in raw_contrib.index if f not in top_feats]].sum()
    )
    total_cal = base_cal + slope * float(raw_contrib.sum())
    p = _sigmoid(total_cal)

    # Sanity: the additive calibrated logit must reproduce the model's own
    # probability for this row (else the page would show a fictitious total).
    assert abs(p - float(p_test[chosen])) < 1e-6, (p, float(p_test[chosen]))

    return {
        "base": round(base_cal, 4),
        "drivers": driver_out,
        "other": round(other_cal, 4),
        "total_logit": round(total_cal, 4),
        "probability": round(p, 4),
    }


def main() -> None:
    if not FEATURES_PATH.exists():
        raise SystemExit(
            f"Missing {FEATURES_PATH}. Run notebooks/03_feature_engineering.ipynb "
            "to build the feature parquet first."
        )

    df = pd.read_parquet(FEATURES_PATH)
    df["inspection_date"] = pd.to_datetime(df["inspection_date"])
    # Served basis: drop burn-in (no label) and right-truncated rows (their
    # forward window runs past the data, so their labels are under-counted).
    # This is the review-time-filtered "served" test in docs/experiments.md
    # (n≈7,008), not the unfiltered "honest test" (n≈13,812) — they are not
    # directly comparable, so we report one basis and name it.
    df = df[(~df["is_burnin"]) & (~df["right_truncated"])].dropna(subset=[LABEL_COL])

    train = df[df["inspection_date"] < TRAIN_END]
    val = df[(df["inspection_date"] >= TRAIN_END) & (df["inspection_date"] < TEST_START)]
    test = df[df["inspection_date"] >= TEST_START]

    pipe = build_baseline_pipeline()
    pipe.fit(train[ALL_FEATURES], train[LABEL_COL].astype(int))
    scores = pipe.predict_proba(test[ALL_FEATURES])[:, 1]
    y = test[LABEL_COL].astype(int).to_numpy()

    report = evaluate(y, scores)
    table = operating_point_table(y, scores, k_fracs=K_FRACS)

    # Sigmoid (Platt) calibration on the val slice, mirroring the served model
    # (retrain_baseline_sigmoid.py). Used only for the worked waterfall, so its
    # additive log-odds land exactly on a calibrated probability. FrozenEstimator
    # marks `pipe` as pre-fit so calibration doesn't refit the base estimator.
    calibrated = CalibratedClassifierCV(FrozenEstimator(pipe), method="sigmoid")
    calibrated.fit(val[ALL_FEATURES], val[LABEL_COL].astype(int))

    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        # Uncalibrated baseline: operating points + PR/ROC-AUC are rank-based, so
        # they're identical to the sigmoid-calibrated served form (see docstring).
        # The string names the estimator family, not a calibration step we ran.
        "model_version": "baseline_logreg",
        # Provenance — ties these numbers to the exact code + dataset that
        # produced them, so the page can't silently drift from the served model.
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
        # Global feature impact (mean |log-odds| on test) for the importance bar.
        "global_importance": global_feature_impact(pipe, test),
        # One anonymised worked example whose calibrated drivers sum to its score.
        "waterfall": worked_waterfall(pipe, calibrated, test),
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"wrote {OUTPUT_PATH.relative_to(REPO_ROOT)}: "
        f"{len(payload['operating_points'])} operating points, "
        f"PR-AUC {payload['headline']['pr_auc']}, test n={payload['test']['n']}"
    )


if __name__ == "__main__":
    main()
