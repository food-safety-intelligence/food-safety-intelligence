"""Chicago SODA (Socrata) API loaders.

Two paginating fetchers — pick by dataset size:

- `fetch_soda` — offset-pagination ($offset). Fine up to ~500k rows. Past that,
  Socrata's $offset is O(offset) and starts timing out.
- `fetch_soda_keyset` — keyset pagination on a cursor column (e.g. `created_date`).
  Every page stays fast regardless of depth; mandatory for the full 311 pull
  (~1.1M rows) and the right design for a future periodic-ingestion DAG that
  resumes from a stored watermark.

Both functions include retry-with-exponential-backoff for transient timeouts.
`fetch_soda_keyset` also supports a `shard_dir` so each page is persisted to
disk as it arrives — a crash mid-pull doesn't lose minutes of work.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

from foodsafety.config import SODA_BASE
from foodsafety.io import storage

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_soda(
    dataset_id: str,
    where: str | None = None,
    select: str | None = None,
    order: str | None = None,
    page_size: int = 50_000,
    max_pages: int = 200,
    timeout: int = 180,
    max_retries: int = 4,
    verbose: bool = True,
) -> pd.DataFrame:
    """Paginate a SODA endpoint via $offset and return a single DataFrame.

    Use this for small/medium datasets. For >500k matching rows, prefer
    `fetch_soda_keyset` — Socrata's $offset cost grows with depth and starts
    timing out past page 10.

    Args:
        dataset_id: Socrata 4x4 ID (e.g. "4ijn-s7e5").
        where: SoQL `$where` filter, e.g. `"inspection_date >= '2019-01-01'"`.
        select: SoQL `$select`, e.g. `"sr_type,count(*) as n"`.
        order: SoQL `$order`. Always pass something; without it Socrata does
            not guarantee stable ordering between pages.
        page_size: rows per request (max 50_000).
        max_pages: hard cap so a runaway loop can't hammer the API.
        timeout: per-request timeout in seconds.
        max_retries: transient-error retry budget per page.
        verbose: print one progress line per page.
    """
    url = f"{SODA_BASE}/{dataset_id}.json"
    frames: list[pd.DataFrame] = []

    for page in range(max_pages):
        params: dict[str, str | int] = {
            "$limit": page_size,
            "$offset": page * page_size,
        }
        if where:
            params["$where"] = where
        if select:
            params["$select"] = select
        if order:
            params["$order"] = order

        response, elapsed = _request_with_retry(url, params, timeout, max_retries, verbose, page)
        chunk = pd.DataFrame(response.json())
        if chunk.empty:
            break
        frames.append(chunk)
        if verbose:
            cum = sum(len(f) for f in frames)
            print(f"  page {page + 1}: +{len(chunk):,} rows (cum {cum:,}, {elapsed:.1f}s)")
        if len(chunk) < page_size:
            break
        time.sleep(0.2)  # be polite to the public API

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fetch_soda_keyset(
    dataset_id: str,
    cursor_col: str,
    cursor_start: str,
    where_extra: str | None = None,
    page_size: int = 50_000,
    max_pages: int = 500,
    timeout: int = 180,
    max_retries: int = 4,
    dedupe_on: str | None = None,
    shard_dir: Path | str | None = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """Keyset-paginate a SODA endpoint by `cursor_col >= last_value`.

    Why over `fetch_soda`: Socrata's `$offset` is O(offset) on the server. For
    >500k-row datasets it starts timing out past page 10. Keyset pagination
    keeps every page fast regardless of depth, and it's exactly the design a
    future Airflow / scheduled-ingestion DAG needs — store the last watermark,
    pass it as `cursor_start`, resume.

    Resilience: if `shard_dir` is given, each page is written to a separate
    parquet shard immediately after fetch. On rerun, the loader picks up from
    the highest cursor value already on disk. Shard dir is auto-cleaned on
    clean exit.

    Dedupe: when rows share the same cursor value across a page boundary, `>=`
    re-fetches them at the boundary. We dedupe at the end. Pass `dedupe_on` for
    a primary-key dedupe (cleaner when the table has unhashable nested columns
    like Socrata's `location: {type, coordinates}`).

    Args:
        dataset_id: Socrata 4x4 ID.
        cursor_col: column to page by. Must be sortable and roughly monotonic
            (e.g. `created_date`, `inspection_date`).
        cursor_start: ISO timestamp to start at (e.g. "2019-01-01T00:00:00").
        where_extra: extra SoQL predicate AND-ed with the cursor clause.
        page_size: rows per request.
        max_pages: hard cap on iterations.
        timeout: per-request timeout in seconds.
        max_retries: transient-error retry budget.
        dedupe_on: column name to dedupe on. If None, dedupe on the subset of
            hashable columns.
        shard_dir: if given, write each page to `<shard_dir>/page_NNNN.parquet`
            and resume from there on rerun.
        verbose: print one progress line per page.
    """
    url = f"{SODA_BASE}/{dataset_id}.json"
    cursor = cursor_start
    frames: list[pd.DataFrame] = []
    # shard_dir may be a local path or an s3:// prefix — route every shard read/write
    # through storage so crash-resume works in both. Never Path()-wrap it (that
    # collapses the // after the s3 scheme).
    shards: list[str] = []

    # Resume from existing shards already written, if any.
    if shard_dir is not None:
        existing = storage.glob(shard_dir, "page_*.parquet")
        if existing:
            shards = existing
            last = storage.read_parquet(existing[-1])
            cursor = str(last[cursor_col].max())
            if verbose:
                cum = sum(len(storage.read_parquet(s)) for s in shards)
                print(
                    f"  resuming from {len(shards)} shard(s): {cum:,} rows, cursor -> {cursor[:19]}"
                )

    start_page = len(shards)
    for page in range(start_page, max_pages):
        where_parts = [f"{cursor_col} >= '{cursor}'"]
        if where_extra:
            where_parts.append(f"({where_extra})")
        params: dict[str, str | int] = {
            "$where": " AND ".join(where_parts),
            "$order": f"{cursor_col} ASC",
            "$limit": page_size,
        }
        response, elapsed = _request_with_retry(url, params, timeout, max_retries, verbose, page)
        chunk = pd.DataFrame(response.json())
        if chunk.empty:
            break
        frames.append(chunk)

        # Persist this page immediately so a downstream crash (or a killed kernel)
        # doesn't lose it. Goes to local disk or S3 depending on shard_dir.
        if shard_dir is not None:
            shard_path = storage.join(str(shard_dir), f"page_{page:04d}.parquet")
            storage.write_parquet(
                chunk.astype({c: "string" for c in chunk.select_dtypes("object").columns}),
                shard_path,
                index=False,
            )
            shards.append(shard_path)

        if verbose:
            print(
                f"  page {page + 1}: +{len(chunk):,} rows (cursor={str(cursor)[:10]}, {elapsed:.1f}s)"
            )
        if len(chunk) < page_size:
            break
        cursor = chunk[cursor_col].iloc[-1]
        time.sleep(0.2)

    # Prefer shards if available (already persisted, dtype-normalized). Else use
    # the in-memory frames. Empty case returns an empty DataFrame.
    if shards:
        out = pd.concat([storage.read_parquet(s) for s in shards], ignore_index=True)
    elif frames:
        out = pd.concat(frames, ignore_index=True)
    else:
        return pd.DataFrame()

    before = len(out)
    out = _safe_dedupe(out, dedupe_on=dedupe_on, verbose=verbose)
    if verbose and len(out) != before:
        print(f"  after dedupe: {len(out):,} rows (removed {before - len(out):,})")

    # On clean success, drop the shard files so the next run starts fresh. No
    # directory removal: S3 has no real directories, and an empty local shard dir
    # under data/ is gitignored and harmless.
    if shard_dir is not None:
        for s in shards:
            storage.delete(s)

    return out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_dedupe(
    df: pd.DataFrame,
    dedupe_on: str | None = None,
    verbose: bool = True,
) -> pd.DataFrame:
    """`drop_duplicates` that survives unhashable columns.

    Socrata returns the `location` column as a dict like
    `{"type": "Point", "coordinates": [-87.63, 41.88]}`. Plain `drop_duplicates`
    raises `TypeError: unhashable type: 'dict'` on tables that include it.
    """
    if dedupe_on:
        return df.drop_duplicates(subset=[dedupe_on])

    # Sample-check the first 200 rows to find unhashable columns cheaply.
    sample = df.head(200)
    unhashable = [
        c
        for c in df.columns
        if sample[c].dropna().apply(lambda x: isinstance(x, (dict, list))).any()
    ]
    if unhashable:
        if verbose:
            print(f"  dedupe: ignoring unhashable cols {unhashable}")
        hashable = [c for c in df.columns if c not in unhashable]
        return df.drop_duplicates(subset=hashable)
    return df.drop_duplicates()


def _request_with_retry(
    url: str,
    params: dict,
    timeout: int,
    max_retries: int,
    verbose: bool,
    page_idx: int,
) -> tuple[requests.Response, float]:
    """GET with exponential-backoff retry. Returns (response, elapsed_seconds).

    Retries on ReadTimeout / ConnectionError only — not on 4xx/5xx, which
    indicate a request error we shouldn't paper over.
    """
    for attempt in range(max_retries):
        try:
            t0 = time.time()
            r = requests.get(
                url,
                params=params,
                timeout=timeout,
                headers={"Accept-Encoding": "gzip"},  # ~3-5x faster on big pages
            )
            r.raise_for_status()
            return r, time.time() - t0
        except (requests.Timeout, requests.ConnectionError) as e:
            if attempt == max_retries - 1:
                raise
            wait = 5 * (2**attempt)  # 5, 10, 20, 40s
            if verbose:
                print(
                    f"  page {page_idx + 1} attempt {attempt + 1} failed "
                    f"({type(e).__name__}); retry in {wait}s"
                )
            time.sleep(wait)
    raise RuntimeError("unreachable")  # for type checkers
