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
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from foodsafety.models.baseline import ALL_FEATURES, LABEL_COL, build_baseline_pipeline
from foodsafety.models.evaluate import evaluate, operating_point_table

REPO_ROOT = Path(__file__).resolve().parents[1]
FEATURES_PATH = REPO_ROOT / "data" / "processed" / "features.parquet"
OUTPUT_PATH = REPO_ROOT / "app" / "public" / "data" / "methodology.json"

# Chronological split — must match the served model: train through 2024-07,
# the 2024-07 → 2025-07 year is the calibration/validation slice, and 2025-07
# onward is the time-held-out test. Never a random shuffle.
TRAIN_END = pd.Timestamp("2024-07-01")
TEST_START = pd.Timestamp("2025-07-01")
K_FRACS = (0.05, 0.10, 0.20, 0.30, 0.50)


def main() -> None:
    if not FEATURES_PATH.exists():
        raise SystemExit(
            f"Missing {FEATURES_PATH}. Run notebooks/03_feature_engineering.ipynb "
            "to build the feature parquet first."
        )

    df = pd.read_parquet(FEATURES_PATH)
    df["inspection_date"] = pd.to_datetime(df["inspection_date"])
    # Honest basis: drop burn-in (no label) and right-truncated rows (their
    # forward window runs past the data, so their labels are under-counted).
    df = df[(~df["is_burnin"]) & (~df["right_truncated"])].dropna(subset=[LABEL_COL])

    train = df[df["inspection_date"] < TRAIN_END]
    test = df[df["inspection_date"] >= TEST_START]

    pipe = build_baseline_pipeline()
    pipe.fit(train[ALL_FEATURES], train[LABEL_COL].astype(int))
    scores = pipe.predict_proba(test[ALL_FEATURES])[:, 1]
    y = test[LABEL_COL].astype(int).to_numpy()

    report = evaluate(y, scores)
    table = operating_point_table(y, scores, k_fracs=K_FRACS)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model_version": "baseline_logreg_sigmoid",
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
