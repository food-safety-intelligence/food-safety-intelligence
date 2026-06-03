"""Parquet-on-disk caching wrapper for the SODA fetchers.

`load_or_fetch(name, fetch_fn)` is the standard pattern in every notebook and
script: check `<RAW_DIR>/<name>.parquet`, return it if present, otherwise run
`fetch_fn()` and persist the result.

Teammates: delete the parquet under data/raw/ to force a refresh on the next
notebook run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd

from foodsafety.config import RAW_DIR


def load_or_fetch(
    name: str,
    fetch_fn: Callable[[], pd.DataFrame],
    cache_dir: Path | None = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """Load `<cache_dir>/<name>.parquet` if it exists, else fetch and persist.

    Args:
        name: dataset name without extension (e.g. "inspections"). The parquet
            file is `<cache_dir>/<name>.parquet`.
        fetch_fn: zero-arg callable that returns a DataFrame on cache miss.
        cache_dir: defaults to `RAW_DIR` from config.
        verbose: print one line on hit / miss.
    """
    cache_dir = cache_dir or RAW_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"{name}.parquet"

    if cache.exists():
        if verbose:
            print(f"✓ loading {name} from cache: {cache}")
        return pd.read_parquet(cache)

    if verbose:
        print(f"↻ fetching {name} from API...")
    df = fetch_fn()

    # Cast object cols to string so parquet doesn't trip on mixed-type cells.
    # SODA returns everything as strings on the wire, but DataFrame inference
    # can promote some to object dtype with stray ints/floats mixed in.
    df = df.astype({c: "string" for c in df.select_dtypes("object").columns})
    df.to_parquet(cache, index=False)
    if verbose:
        print(f"  saved -> {cache}  ({len(df):,} rows)")
    return df
