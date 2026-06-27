"""Fetch Chicago Building Violations (22u3-xenr) → data/raw/building_violations.parquet.

Pulls violation_date, latitude, longitude, department_bureau — the four columns
needed by add_building_features for aggregate + bureau-specific spatial joins.

Start date aligns with the inspection dataset (earliest inspection: 2010-01-04).
Pre-2010 violations would only ever back-fill burn-in rows (pre-2019 inspections)
that never enter training, so pulling them wastes bandwidth and disk space.

The fetch uses keyset pagination on violation_date so it can resume from disk on
a crash or timeout without restarting from page 0. Shards are cleaned up on
clean exit.

Usage:
    PYTHONPATH=src uv run python scripts/fetch_building_violations.py
"""

from __future__ import annotations

from pathlib import Path

from foodsafety.config import DATASETS, RAW_DIR
from foodsafety.io.soda import fetch_soda_keyset

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = RAW_DIR / "building_violations.parquet"
SHARD_DIR = RAW_DIR / "_partial_building_violations"

# Columns required by add_building_features; everything else is dropped to
# minimise disk usage (~8 MB vs ~200 MB for the full schema).
KEEP_COLS = ["violation_date", "latitude", "longitude", "department_bureau"]


def main() -> None:
    if OUT_PATH.exists():
        import pandas as pd

        existing = pd.read_parquet(OUT_PATH)
        if "department_bureau" in existing.columns:
            print(f"Already fetched: {OUT_PATH} ({len(existing):,} rows) — skipping.")
            return
        print("Existing file missing department_bureau — re-fetching.")
        OUT_PATH.unlink()

    print("Fetching Chicago Building Violations (22u3-xenr) from 2010-01-01...")
    df = fetch_soda_keyset(
        dataset_id=DATASETS["building_violations"],
        cursor_col="violation_date",
        # Align with inspection dataset start (earliest inspection: 2010-01-04).
        cursor_start="2010-01-01T00:00:00",
        where_extra=(
            "latitude IS NOT NULL AND longitude IS NOT NULL AND violation_date IS NOT NULL"
        ),
        page_size=50_000,
        shard_dir=SHARD_DIR,
        verbose=True,
    )

    keep = [c for c in KEEP_COLS if c in df.columns]
    df = df[keep].copy()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    size_mb = OUT_PATH.stat().st_size / 1e6
    print(f"\nSaved → {OUT_PATH}")
    print(f"  {len(df):,} rows · {df.shape[1]} cols · {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
