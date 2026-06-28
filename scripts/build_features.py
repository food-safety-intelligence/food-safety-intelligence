"""Build the modeling feature set from raw + labeled inputs (Stage 2).

Reads the labeled inspections (``processed/inspections_labeled.parquet``) and the raw
side inputs (historical licenses) from the configured data dir — local or S3 — runs
``foodsafety.features.build.build_features``, and writes the result to ``FEATURES_PATH``
(``processed/features/<name>.parquet``). This is the build notebook 03 does, lifted into a
script so it runs against S3 and so several experiments can share one raw pull. The leakage
discipline lives inside the feature modules; this orchestrator doesn't touch it.

The 311 complaints and block-face building-violation joins are intentionally skipped: both
families were tested and dropped from ALL_FEATURES (see baseline.py + docs/model-experiments.md).
Their feature code is kept in-tree but unwired (complaint_features.py / building_features.py);
building violations can still be fetched via scripts/fetch_building_violations.py if the
experiment is ever revisited. Wiring either back in adds BallTree runtime for no model gain.

Run:
    PYTHONPATH=src uv run python scripts/build_features.py
    FOODSAFETY_DATA_DIR=s3://food-safety-intelligence-data \\
        PYTHONPATH=src uv run python scripts/build_features.py
"""

from __future__ import annotations

import argparse

from foodsafety.config import FEATURES_PATH, PROCESSED_DIR, RAW_DIR
from foodsafety.features.build import build_features
from foodsafety.io import storage
from foodsafety.models.baseline import ALL_FEATURES


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        default=str(FEATURES_PATH),
        help="feature-set target (default: config.FEATURES_PATH)",
    )
    args = ap.parse_args()

    labeled_path = storage.join(str(PROCESSED_DIR), "inspections_labeled.parquet")
    licenses_hist_path = storage.join(str(RAW_DIR), "licenses_historical.parquet")

    # Labeled inspections + historical licenses are the required inputs.
    for p in (labeled_path, licenses_hist_path):
        if not storage.exists(p):
            raise SystemExit(
                f"Missing required input: {p}. Run scripts/ingest_raw.py for the raw "
                f"datasets and the label build (notebook 02) first."
            )

    print("Reading inputs:")
    print(f"  {labeled_path}")
    labeled = storage.read_parquet(labeled_path)
    print(f"  {licenses_hist_path}")
    licenses_historical = storage.read_parquet(licenses_hist_path)

    # 311 complaints and building violations are intentionally left unwired (None) — both
    # feature families were dropped from ALL_FEATURES (see the module docstring).
    features = build_features(
        labeled,
        complaints=None,
        licenses_historical=licenses_historical,
    )

    missing_cols = [c for c in ALL_FEATURES if c not in features.columns]
    if missing_cols:
        print(f"  WARNING: {len(missing_cols)} ALL_FEATURES columns missing: {missing_cols}")
    else:
        print(f"  all {len(ALL_FEATURES)} ALL_FEATURES columns present")

    # Cast object cols to pandas string for a consistent parquet round-trip
    # (matches notebook 03's write).
    obj_cols = features.select_dtypes("object").columns
    features[obj_cols] = features[obj_cols].astype("string")

    storage.write_parquet(features, args.out, index=False)
    print(f"Wrote {args.out}: {len(features):,} rows × {features.shape[1]} cols")


if __name__ == "__main__":
    main()
