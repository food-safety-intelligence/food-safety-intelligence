"""Build data/processed/features.parquet from labeled inspections + raw datasets.

This is the scripted equivalent of notebooks/03_feature_engineering.ipynb for
use in automated runs (make features). The notebook remains the canonical
exploration artifact; this script is the automation entry point.

Inputs (all must exist under data/):
    processed/inspections_labeled.parquet   built by notebook 02
    raw/licenses_historical.parquet         fetched by notebook 00 / 01
    raw/building_violations.parquet         fetched by scripts/fetch_building_violations.py

Output:
    processed/features.parquet             model-ready feature table

The 311 complaints join is intentionally skipped: those features were tested
and dropped from ALL_FEATURES (see baseline.py comments and docs/experiments.md).
Including them would add ~5 min of BallTree runtime for zero model gain.

Usage:
    PYTHONPATH=src uv run python scripts/build_features.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from foodsafety.config import PROCESSED_DIR, RAW_DIR
from foodsafety.features.build import build_features
from foodsafety.models.baseline import ALL_FEATURES

REPO_ROOT = Path(__file__).resolve().parent.parent

LABELED_PATH = PROCESSED_DIR / "inspections_labeled.parquet"
LICENSES_HIST_PATH = RAW_DIR / "licenses_historical.parquet"
BV_PATH = RAW_DIR / "building_violations.parquet"
OUT_PATH = PROCESSED_DIR / "features.parquet"


def main() -> None:
    # --- Input validation ---------------------------------------------------
    missing = [p for p in (LABELED_PATH, LICENSES_HIST_PATH) if not p.exists()]
    if missing:
        for p in missing:
            print(f"ERROR: missing required input: {p}", file=sys.stderr)
        raise SystemExit(1)

    if not BV_PATH.exists():
        print(
            f"WARNING: {BV_PATH} not found.\n"
            "  Run `make fetch_bldg_violations` first to include building violation features.\n"
            "  Continuing without them — the output will be missing 9 features from ALL_FEATURES.",
            file=sys.stderr,
        )

    # --- Load inputs --------------------------------------------------------
    print(f"Loading {LABELED_PATH.name} ...", end=" ", flush=True)
    labeled = pd.read_parquet(LABELED_PATH)
    print(f"{len(labeled):,} rows")

    print(f"Loading {LICENSES_HIST_PATH.name} ...", end=" ", flush=True)
    licenses_historical = pd.read_parquet(LICENSES_HIST_PATH)
    print(f"{len(licenses_historical):,} rows")

    building_violations: pd.DataFrame | None = None
    if BV_PATH.exists():
        print(f"Loading {BV_PATH.name} ...", end=" ", flush=True)
        building_violations = pd.read_parquet(BV_PATH)
        print(f"{len(building_violations):,} rows")

    # --- Build features -----------------------------------------------------
    print("\nBuilding features (this takes a few minutes)...")
    features = build_features(
        labeled,
        complaints=None,
        licenses_historical=licenses_historical,
        building_violations=building_violations,
    )
    print(f"  → {features.shape[0]:,} rows × {features.shape[1]} cols")

    # --- Validate ALL_FEATURES coverage -------------------------------------
    missing_cols = [c for c in ALL_FEATURES if c not in features.columns]
    if missing_cols:
        print(
            f"\nWARNING: {len(missing_cols)} ALL_FEATURES columns missing from output:\n"
            f"  {missing_cols}",
            file=sys.stderr,
        )
    else:
        print(f"  All {len(ALL_FEATURES)} ALL_FEATURES columns present.")

    # --- Write output -------------------------------------------------------
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = features.copy()
    obj_cols = out.select_dtypes("object").columns
    out[obj_cols] = out[obj_cols].astype("string")
    out.to_parquet(OUT_PATH, index=False)

    size_mb = OUT_PATH.stat().st_size / 1e6
    print(f"\nWrote → {OUT_PATH}")
    print(f"  {len(out):,} rows · {out.shape[1]} cols · {size_mb:.1f} MB")

    label_col = "y_fail_or_critical_next_180d"
    if label_col in out.columns:
        trainable = out[out[label_col].notna() & ~out.get("is_burnin", pd.Series(False))]
        print(f"  Trainable rows (non-NA label, non-burnin): {len(trainable):,}")
        print(f"  Positive rate: {trainable[label_col].mean():.2%}")


if __name__ == "__main__":
    main()
