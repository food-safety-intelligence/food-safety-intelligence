"""Incremental ingestion: watermark + lookback + upsert-on-PK.

Layered on top of the existing ``fetch_soda_keyset`` and ``storage`` modules.
Each function is pure (network access is injected) so the flow is testable
without hitting the SODA API.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pandas as pd

from foodsafety.config import (
    INGEST_SPECS,
    LOOKBACK_DAYS,
    RAW_DIR,
    DatasetSpec,
)
from foodsafety.io import storage
from foodsafety.io.soda import fetch_soda_keyset


def watermark(df: pd.DataFrame, cursor_col: str) -> str | None:
    """Extract the high-water mark (max cursor value) from existing data."""
    if df.empty or cursor_col not in df.columns:
        return None
    val = df[cursor_col].max()
    if pd.isna(val):
        return None
    return str(val)


def cursor_start(wm: str | None, lookback_days: int, spec: DatasetSpec) -> str:
    """Compute the cursor start: watermark minus lookback, or the spec's start date."""
    if wm is None:
        return spec.start
    dt = datetime.fromisoformat(wm) - timedelta(days=lookback_days)
    return dt.isoformat()


def upsert(existing: pd.DataFrame, new: pd.DataFrame, pk: str) -> pd.DataFrame:
    """Merge new rows into existing, deduplicating on the natural key.

    ``new`` rows win over ``existing`` for the same PK value (keep="last").
    """
    if existing.empty:
        return new.drop_duplicates(subset=[pk], keep="last").reset_index(drop=True)
    combined = pd.concat([existing, new], ignore_index=True)
    return combined.drop_duplicates(subset=[pk], keep="last").reset_index(drop=True)


def ingest_dataset(
    name: str,
    spec: DatasetSpec | None = None,
    lookback_days: int = LOOKBACK_DAYS,
    verbose: bool = True,
) -> pd.DataFrame:
    """Run one incremental ingest cycle for a dataset.

    1. Read existing parquet (empty if first run).
    2. Derive watermark and cursor_start with lookback.
    3. Fetch new/edited rows from SODA.
    4. Upsert into existing on the natural key.
    5. Atomic write back to the canonical path.
    """
    if spec is None:
        spec = INGEST_SPECS[name]

    canonical = storage.join(str(RAW_DIR), f"{name}.parquet")
    shard_dir = storage.join(str(RAW_DIR), "_shards", name)

    # 1. Read existing
    if storage.exists(canonical):
        existing = storage.read_parquet(canonical)
    else:
        existing = pd.DataFrame()

    # 2. Watermark + cursor
    wm = watermark(existing, spec.cursor_col)
    start = cursor_start(wm, lookback_days, spec)
    if verbose:
        print(f"  {name}: watermark={wm}, cursor_start={start[:19]}")

    # 3. Fetch incremental
    fetch_kwargs: dict = dict(
        dataset_id=spec.dataset_id,
        cursor_col=spec.cursor_col,
        cursor_start=start,
        where_extra=spec.where_extra,
        dedupe_on=spec.pk,
        shard_dir=shard_dir,
        verbose=verbose,
    )
    if spec.select:
        fetch_kwargs["select"] = spec.select
    new = fetch_soda_keyset(**fetch_kwargs)

    # Column pruning: keep only the columns needed downstream (plus pk/cursor,
    # which are always required for upsert and watermarking).
    if spec.keep_cols is not None and not new.empty:
        required = {spec.pk, spec.cursor_col, *spec.keep_cols}
        keep = [c for c in new.columns if c in required]
        new = new[keep]

    if new.empty:
        if verbose:
            print(f"  {name}: no new rows")
        return existing

    # 4. Upsert
    merged = upsert(existing, new, spec.pk)
    if verbose:
        print(f"  {name}: {len(existing):,} existing + {len(new):,} new -> {len(merged):,} merged")

    # 5. Atomic write: temp key -> canonical (safe re-runs)
    run_id = uuid.uuid4().hex[:8]
    tmp = storage.join(str(RAW_DIR), "_tmp", f"{name}.{run_id}.parquet")
    storage.write_parquet(merged, tmp, index=False)
    storage.copy(tmp, canonical)
    storage.delete(tmp)

    return merged
