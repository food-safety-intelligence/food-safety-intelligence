# Weekly S3 Ingestion — Implementation Plan (Phase A: ingestion code)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A scripted, tested, idempotent fetch that incrementally pulls the five Chicago SODA datasets and writes one canonical parquet per dataset to a backend chosen by `FOODSAFETY_DATA_DIR` (local dir or `s3://…`).

**Architecture:** A table of per-dataset specs (`INGEST_SPECS`) drives one reusable code path: read the existing dataset → derive an incremental watermark (minus a lookback window) → keyset-fetch only new/edited rows via the existing `fetch_soda_keyset` → upsert on the natural key → atomically write back. A thin `foodsafety/io/store.py` resolves local-vs-S3 from `FOODSAFETY_DATA_DIR`. `scripts/fetch_all.py` runs it for all datasets; `make ingest` wraps it.

**Tech Stack:** Python 3.11, pandas, pyarrow, `fetch_soda_keyset` (existing), `s3fs`+`boto3` (new) for the S3 backend, pytest, ruff (line length 100), `uv`.

> **Refinement vs the approved spec:** the spec sketched three separate scripts (`fetch_inspections.py`, `fetch_311.py`, `fetch_licenses.py`). This plan consolidates them into **one table-driven path** (`INGEST_SPECS` + `ingest_dataset` + `fetch_all.py`) — DRY, same behavior, much less code — and folds the existing `fetch_building_violations.py` into it too. Same refinement reason: five near-identical scripts is exactly the duplication CLAUDE.md's "three similar lines beat a premature abstraction… no speculative generality" cuts the *other* way on once it's five. **Flag if you'd rather keep separate scripts.**
>
> **Env-var convention (consistency fix):** the spec text said the Fargate task sets `FOODSAFETY_DATA_DIR=s3://food-safety-intelligence-data/raw`. This plan treats `FOODSAFETY_DATA_DIR` as the **data root** in both backends (matching how `config.DATA_DIR` already works locally), so raw always lives at `<root>/raw`. The Fargate value becomes `s3://food-safety-intelligence-data` and raw resolves to `s3://food-safety-intelligence-data/raw`.

## Global Constraints

- Python 3.11; line length 100; `make lint` (`ruff check` + `ruff format --check`) must pass before every commit.
- Notebooks are not linted; the package/scripts/tests are.
- New deps allowed this iteration (Phase-2 AWS in scope): `s3fs`, `boto3`. No others without justification.
- `RANDOM_STATE = 42` — not relevant here (no RNG in ingestion), but do not introduce randomness.
- Do NOT change the model, features, label, temporal-split discipline, or the 2019 training cutoff. This is raw ingestion only; the 2019 cutoff is applied downstream in feature-building and stays untouched.
- Pure functions over classes; type hints on every function in `src/foodsafety/`.
- Comment the WHY for: the lookback window (why we re-pull recent rows), the keyset `>=` boundary re-fetch, and the S3-vs-local atomic-write difference.
- No emoji in code. No `print(df)` (n/a here). Commit code before any tracked experiment (n/a — no experiment here).

## File Structure

| File | Responsibility |
|---|---|
| `src/foodsafety/config.py` (modify) | Add `DatasetSpec`, `INGEST_SPECS`, `LOOKBACK_DAYS`. Single source of truth for what gets ingested and how. |
| `src/foodsafety/io/store.py` (create) | Backend seam: `dataset_uri`, `read_dataset`, `write_dataset`. Resolves local path vs `s3://` from `FOODSAFETY_DATA_DIR`; atomic write per backend. |
| `src/foodsafety/ingest.py` (create) | Orchestration: `watermark`, `cursor_start`, `upsert`, `ingest_dataset`. Pure, network-injected for tests. |
| `scripts/fetch_all.py` (create) | CLI entry: run `ingest_dataset` for all (or `--dataset`-selected) datasets. |
| `scripts/fetch_building_violations.py` (modify) | Re-point to `ingest_dataset("building_violations", …)` so there is one code path. |
| `Makefile` (modify) | Add `ingest` target; point `fetch_bldg_violations` at `fetch_all.py --dataset building_violations`. |
| `pyproject.toml` (modify) | Add `s3fs`, `boto3`. |
| `tests/io/test_store.py` (create) | Tests for `dataset_uri` resolution + local read/write/atomic-replace. |
| `tests/test_ingest.py` (create) | Tests for `watermark`, `cursor_start`, `upsert`, and `ingest_dataset` idempotency (fake fetcher, no network). |

---

### Task 1: Dependencies + dataset spec table

**Files:**
- Modify: `pyproject.toml` (dependencies)
- Modify: `src/foodsafety/config.py`
- Test: `tests/test_ingest.py` (new file, one spec-shape test)

**Interfaces:**
- Produces: `DatasetSpec(dataset_id, cursor_col, pk, start, where_extra=None)` frozen dataclass; `INGEST_SPECS: dict[str, DatasetSpec]` keyed by the same names as `config.DATASETS`; `LOOKBACK_DAYS: int`.

- [ ] **Step 1: Add deps**

In `pyproject.toml`, add to the project dependencies array (keep alphabetical if the file is sorted):

```toml
  "s3fs>=2024.6.0",
  "boto3>=1.34",
```

Then sync:

```bash
uv sync
```

Expected: resolves and installs `s3fs`, `boto3` (and `fsspec`) with no conflicts.

- [ ] **Step 2: Write the failing test for the spec table**

Create `tests/test_ingest.py`:

```python
from foodsafety.config import INGEST_SPECS, LOOKBACK_DAYS, DATASETS


def test_ingest_specs_cover_all_datasets_with_required_fields():
    # Every ingestable dataset has a Socrata id that matches DATASETS, a cursor
    # column, a natural key to upsert on, and a first-pull start date.
    assert set(INGEST_SPECS) == set(DATASETS)
    for name, spec in INGEST_SPECS.items():
        assert spec.dataset_id == DATASETS[name]
        assert spec.cursor_col and spec.pk and spec.start
    assert LOOKBACK_DAYS > 0
```

- [ ] **Step 3: Run it to verify it fails**

Run: `PYTHONPATH=src uv run python -m pytest tests/test_ingest.py -v`
Expected: FAIL with `ImportError: cannot import name 'INGEST_SPECS'`.

- [ ] **Step 4: Implement the spec table**

Append to `src/foodsafety/config.py` (after `DATASETS` / `RELEVANT_SR_TYPES`):

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetSpec:
    """How to incrementally ingest one SODA dataset.

    cursor_col drives keyset paging and the incremental watermark; pk is the
    natural key we upsert on so a re-pull (lookback overlap, or an edited
    record) never duplicates a row. start is the horizon for the first full
    pull when no data exists yet.
    """

    dataset_id: str
    cursor_col: str
    pk: str
    start: str  # ISO timestamp, e.g. "2010-01-01T00:00:00"
    where_extra: str | None = None


# Re-pull this many days behind the stored watermark every run. Chicago records
# are mutable (an inspection is amended, a 311 status changes), and a pure
# "cursor >= watermark" pull would miss edits to already-ingested rows. The
# upsert-on-pk merge makes the overlap free of duplicates.
LOOKBACK_DAYS: int = 90

# 311 carries ~14M rows across 110 types; we only ingest the food-safety-relevant
# ones (RELEVANT_SR_TYPES), as a SoQL IN() predicate.
_SR_TYPES_SOQL: str = "sr_type in (" + ", ".join(f"'{t}'" for t in RELEVANT_SR_TYPES) + ")"

INGEST_SPECS: dict[str, DatasetSpec] = {
    "inspections": DatasetSpec("4ijn-s7e5", "inspection_date", "inspection_id", "2010-01-01T00:00:00"),
    "complaints_311": DatasetSpec(
        "v6vf-nfxy", "created_date", "sr_number", "2010-01-01T00:00:00", where_extra=_SR_TYPES_SOQL
    ),
    # NOTE: license cursor/pk column names are best-known and MUST be confirmed
    # against the live Socrata schema during first backfill. `license_id` is NOT
    # unique across renewals — the unique row key is `id`.
    "licenses_current": DatasetSpec("uupf-x98q", "license_start_date", "id", "2010-01-01T00:00:00"),
    "licenses_historical": DatasetSpec("vgg9-bn8p", "license_start_date", "id", "2010-01-01T00:00:00"),
    "building_violations": DatasetSpec(
        "22u3-xenr",
        "violation_date",
        "id",
        "2010-01-01T00:00:00",
        where_extra="latitude IS NOT NULL AND longitude IS NOT NULL AND violation_date IS NOT NULL",
    ),
}
```

Match the dict keys to `config.DATASETS` exactly (`inspections`, `complaints_311`, `licenses_current`, `licenses_historical`, `building_violations`).

- [ ] **Step 5: Run it to verify it passes**

Run: `PYTHONPATH=src uv run python -m pytest tests/test_ingest.py -v`
Expected: PASS.

- [ ] **Step 6: Lint + commit**

```bash
make lint
git add pyproject.toml uv.lock src/foodsafety/config.py tests/test_ingest.py
git commit -m "feat(ingest): add dataset spec table + s3fs/boto3 deps"
```

---

### Task 2: Backend seam — `store.py` (dataset_uri + read/write)

**Files:**
- Create: `src/foodsafety/io/store.py`
- Test: `tests/io/test_store.py`

**Interfaces:**
- Produces: `dataset_uri(name: str) -> str`; `read_dataset(name: str) -> pd.DataFrame` (empty frame if absent); `write_dataset(name: str, df: pd.DataFrame) -> None` (atomic per backend).
- Consumes: nothing from other tasks; reads `FOODSAFETY_DATA_DIR` directly (not `config.DATA_DIR`, which stays a local-only `Path` — `Path("s3://…")` collapses the double slash).

- [ ] **Step 1: Write the failing tests**

Create `tests/io/test_store.py`:

```python
import os

import pandas as pd

from foodsafety.io import store


def test_dataset_uri_local(monkeypatch, tmp_path):
    monkeypatch.setenv("FOODSAFETY_DATA_DIR", str(tmp_path))
    assert store.dataset_uri("inspections") == f"{tmp_path}/raw/inspections.parquet"


def test_dataset_uri_s3_preserves_scheme(monkeypatch):
    monkeypatch.setenv("FOODSAFETY_DATA_DIR", "s3://my-bucket")
    # Must keep the double slash — a Path() round-trip would mangle it.
    assert store.dataset_uri("inspections") == "s3://my-bucket/raw/inspections.parquet"


def test_read_missing_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("FOODSAFETY_DATA_DIR", str(tmp_path))
    assert store.read_dataset("inspections").empty


def test_write_then_read_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("FOODSAFETY_DATA_DIR", str(tmp_path))
    df = pd.DataFrame({"inspection_id": [1, 2], "x": ["a", "b"]})
    store.write_dataset("inspections", df)
    back = store.read_dataset("inspections")
    pd.testing.assert_frame_equal(back, df)


def test_write_is_atomic_no_tmp_left(monkeypatch, tmp_path):
    monkeypatch.setenv("FOODSAFETY_DATA_DIR", str(tmp_path))
    store.write_dataset("inspections", pd.DataFrame({"inspection_id": [1]}))
    leftovers = list((tmp_path / "raw").glob("*.tmp"))
    assert leftovers == []
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src uv run python -m pytest tests/io/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'foodsafety.io.store'`.

- [ ] **Step 3: Implement `store.py`**

Create `src/foodsafety/io/store.py`:

```python
"""Backend seam for the raw-data store.

Reads/writes one canonical parquet per dataset under `<root>/raw/<name>.parquet`,
where `root` is `FOODSAFETY_DATA_DIR` (a local dir by default, or an `s3://…`
URI on the scheduled Fargate task). We read the env var as a raw string rather
than via `config.DATA_DIR`, because `Path("s3://bucket")` collapses the `//`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _root() -> str:
    return (os.environ.get("FOODSAFETY_DATA_DIR") or str(_PROJECT_ROOT / "data")).rstrip("/")


def _is_s3(uri: str) -> bool:
    return uri.startswith("s3://")


def dataset_uri(name: str) -> str:
    """Canonical location of dataset `name` as a path-or-URI string."""
    return f"{_root()}/raw/{name}.parquet"


def read_dataset(name: str) -> pd.DataFrame:
    """Read the dataset, or an empty frame if it does not exist yet."""
    uri = dataset_uri(name)
    if _is_s3(uri):
        import s3fs  # lazy: only needed on the S3 backend

        if not s3fs.S3FileSystem().exists(uri):
            return pd.DataFrame()
        return pd.read_parquet(uri)
    p = Path(uri)
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def write_dataset(name: str, df: pd.DataFrame) -> None:
    """Atomically overwrite the canonical object for `name`.

    Local: write a temp file then `os.replace` (atomic rename on one filesystem).
    S3: a single PUT to the canonical key is itself atomic — a reader sees either
    the whole old object or the whole new one, never a partial — and a failed PUT
    leaves the existing object intact, so no temp dance is needed.
    """
    uri = dataset_uri(name)
    if _is_s3(uri):
        df.to_parquet(uri, index=False)
        return
    p = Path(uri)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, p)
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src uv run python -m pytest tests/io/test_store.py -v`
Expected: 5 passed. (If `tests/io/` needs an `__init__.py` to match the existing test layout, add an empty one.)

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/foodsafety/io/store.py tests/io/
git commit -m "feat(ingest): local/S3 backend seam with atomic write"
```

---

### Task 3: Watermark + lookback (`ingest.py`, part 1)

**Files:**
- Create: `src/foodsafety/ingest.py`
- Modify: `tests/test_ingest.py`

**Interfaces:**
- Produces: `watermark(df, cursor_col) -> str | None`; `cursor_start(df, spec) -> str`.
- Consumes: `DatasetSpec`, `LOOKBACK_DAYS` from `config`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ingest.py`:

```python
import pandas as pd

from foodsafety.config import DatasetSpec
from foodsafety import ingest

_SPEC = DatasetSpec("x", "inspection_date", "inspection_id", "2010-01-01T00:00:00")


def test_watermark_empty_is_none():
    assert ingest.watermark(pd.DataFrame(), "inspection_date") is None


def test_watermark_returns_max():
    df = pd.DataFrame({"inspection_date": ["2026-01-01", "2026-03-15", "2026-02-01"]})
    assert ingest.watermark(df, "inspection_date").startswith("2026-03-15")


def test_cursor_start_no_data_uses_spec_start():
    assert ingest.cursor_start(pd.DataFrame(), _SPEC) == "2010-01-01T00:00:00"


def test_cursor_start_applies_lookback():
    df = pd.DataFrame({"inspection_date": ["2026-06-01"]})
    # 2026-06-01 minus 90-day lookback = 2026-03-03.
    assert ingest.cursor_start(df, _SPEC).startswith("2026-03-03")
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src uv run python -m pytest tests/test_ingest.py -k "watermark or cursor_start" -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'foodsafety.ingest'`.

- [ ] **Step 3: Implement**

Create `src/foodsafety/ingest.py`:

```python
"""Incremental, idempotent ingestion of one SODA dataset into the raw store."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from foodsafety.config import LOOKBACK_DAYS, DatasetSpec


def watermark(df: pd.DataFrame, cursor_col: str) -> str | None:
    """Highest cursor value already ingested, or None if there is no data."""
    if df.empty or cursor_col not in df.columns:
        return None
    return str(pd.to_datetime(df[cursor_col]).max())


def cursor_start(df: pd.DataFrame, spec: DatasetSpec) -> str:
    """Where to start the next pull: the watermark minus a lookback window, or
    the dataset's first-pull horizon if nothing has been ingested yet.

    The lookback re-fetches recently-changed rows so edits to already-stored
    records are picked up; the upsert merge dedupes the overlap.
    """
    wm = watermark(df, spec.cursor_col)
    if wm is None:
        return spec.start
    start = pd.to_datetime(wm) - timedelta(days=LOOKBACK_DAYS)
    return start.strftime("%Y-%m-%dT%H:%M:%S")
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src uv run python -m pytest tests/test_ingest.py -k "watermark or cursor_start" -v`
Expected: 4 passed.

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/foodsafety/ingest.py tests/test_ingest.py
git commit -m "feat(ingest): watermark + lookback cursor"
```

---

### Task 4: Upsert (`ingest.py`, part 2)

**Files:**
- Modify: `src/foodsafety/ingest.py`
- Modify: `tests/test_ingest.py`

**Interfaces:**
- Produces: `upsert(existing, new, pk) -> pd.DataFrame` — concat then keep the last row per `pk` so re-pulled/edited rows win, index reset.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_ingest.py`:

```python
def test_upsert_into_empty():
    new = pd.DataFrame({"inspection_id": [1, 2], "result": ["Pass", "Fail"]})
    out = ingest.upsert(pd.DataFrame(), new, "inspection_id")
    assert len(out) == 2


def test_upsert_dedupes_and_prefers_new():
    existing = pd.DataFrame({"inspection_id": [1, 2], "result": ["Pass", "Pass"]})
    new = pd.DataFrame({"inspection_id": [2, 3], "result": ["Fail", "Pass"]})  # id=2 edited
    out = ingest.upsert(existing, new, "inspection_id").sort_values("inspection_id")
    assert list(out["inspection_id"]) == [1, 2, 3]  # no dupes
    assert out.loc[out.inspection_id == 2, "result"].iloc[0] == "Fail"  # new wins
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src uv run python -m pytest tests/test_ingest.py -k upsert -v`
Expected: FAIL with `AttributeError: module 'foodsafety.ingest' has no attribute 'upsert'`.

- [ ] **Step 3: Implement**

Append to `src/foodsafety/ingest.py`:

```python
def upsert(existing: pd.DataFrame, new: pd.DataFrame, pk: str) -> pd.DataFrame:
    """Merge `new` into `existing`, keeping one row per `pk`. `new` is
    concatenated last, so `keep="last"` makes the freshest copy win — this is
    what makes a lookback re-pull (or an edited record) idempotent.
    """
    if existing.empty:
        return new.drop_duplicates(subset=[pk], keep="last").reset_index(drop=True)
    combined = pd.concat([existing, new], ignore_index=True)
    return combined.drop_duplicates(subset=[pk], keep="last").reset_index(drop=True)
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src uv run python -m pytest tests/test_ingest.py -k upsert -v`
Expected: 2 passed.

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/foodsafety/ingest.py tests/test_ingest.py
git commit -m "feat(ingest): upsert-on-pk merge"
```

---

### Task 5: `ingest_dataset` orchestration + idempotency test

**Files:**
- Modify: `src/foodsafety/ingest.py`
- Modify: `tests/test_ingest.py`

**Interfaces:**
- Produces: `ingest_dataset(name, spec, *, fetch=fetch_soda_keyset) -> int` — reads existing, computes start, fetches, upserts, writes, returns total row count. `fetch` is injectable so tests run without network.
- Consumes: `store.read_dataset`/`store.write_dataset` (Task 2), `cursor_start`/`upsert` (Tasks 3–4), `fetch_soda_keyset` (existing, `src/foodsafety/io/soda.py`).

- [ ] **Step 1: Write the failing idempotency test**

Append to `tests/test_ingest.py`:

```python
def test_ingest_dataset_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("FOODSAFETY_DATA_DIR", str(tmp_path))
    spec = DatasetSpec("x", "inspection_date", "inspection_id", "2010-01-01T00:00:00")

    # Fake fetcher ignores the cursor and always returns the same 3 rows, so a
    # second run is pure overlap — the upsert must keep the row count stable.
    def fake_fetch(**kwargs):
        return pd.DataFrame(
            {
                "inspection_id": [1, 2, 3],
                "inspection_date": ["2026-01-01", "2026-02-01", "2026-03-01"],
                "result": ["Pass", "Fail", "Pass"],
            }
        )

    n1 = ingest.ingest_dataset("inspections", spec, fetch=fake_fetch)
    n2 = ingest.ingest_dataset("inspections", spec, fetch=fake_fetch)
    assert n1 == 3
    assert n2 == 3  # idempotent: re-running does not duplicate


def test_ingest_dataset_passes_cursor_and_pk_to_fetch(monkeypatch, tmp_path):
    monkeypatch.setenv("FOODSAFETY_DATA_DIR", str(tmp_path))
    spec = DatasetSpec("x", "inspection_date", "inspection_id", "2010-01-01T00:00:00")
    seen = {}

    def fake_fetch(**kwargs):
        seen.update(kwargs)
        return pd.DataFrame({"inspection_id": [1], "inspection_date": ["2026-01-01"]})

    ingest.ingest_dataset("inspections", spec, fetch=fake_fetch)
    assert seen["dataset_id"] == "x"
    assert seen["cursor_col"] == "inspection_date"
    assert seen["cursor_start"] == "2010-01-01T00:00:00"  # first run, no watermark
    assert seen["dedupe_on"] == "inspection_id"
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=src uv run python -m pytest tests/test_ingest.py -k ingest_dataset -v`
Expected: FAIL with `AttributeError: module 'foodsafety.ingest' has no attribute 'ingest_dataset'`.

- [ ] **Step 3: Implement**

Add the import at the top of `src/foodsafety/ingest.py` (with the other imports):

```python
from collections.abc import Callable

from foodsafety.io import store
from foodsafety.io.soda import fetch_soda_keyset
```

Append the function:

```python
def ingest_dataset(
    name: str,
    spec: DatasetSpec,
    *,
    fetch: Callable[..., pd.DataFrame] = fetch_soda_keyset,
) -> int:
    """Incrementally ingest `name`: fetch new/edited rows from its watermark,
    upsert on the natural key, atomically write back. Returns total row count.

    `fetch` is injected so tests can run without hitting the network.
    """
    existing = store.read_dataset(name)
    start = cursor_start(existing, spec)
    new = fetch(
        dataset_id=spec.dataset_id,
        cursor_col=spec.cursor_col,
        cursor_start=start,
        where_extra=spec.where_extra,
        dedupe_on=spec.pk,
    )
    if new.empty:
        return len(existing)
    merged = upsert(existing, new, spec.pk)
    store.write_dataset(name, merged)
    return len(merged)
```

- [ ] **Step 4: Run to verify pass**

Run: `PYTHONPATH=src uv run python -m pytest tests/test_ingest.py -v`
Expected: all tests in the file pass.

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add src/foodsafety/ingest.py tests/test_ingest.py
git commit -m "feat(ingest): idempotent ingest_dataset orchestration"
```

---

### Task 6: `fetch_all.py` CLI + Makefile + fold in building violations

**Files:**
- Create: `scripts/fetch_all.py`
- Modify: `scripts/fetch_building_violations.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `INGEST_SPECS` (Task 1), `ingest_dataset` (Task 5).

- [ ] **Step 1: Write the CLI**

Create `scripts/fetch_all.py`:

```python
"""Incrementally fetch the Chicago SODA datasets into the raw store.

Runs every dataset by default, or a subset via repeated --dataset flags. The
write target is chosen by FOODSAFETY_DATA_DIR (local dir or s3://…).

Usage:
    PYTHONPATH=src uv run python scripts/fetch_all.py
    PYTHONPATH=src uv run python scripts/fetch_all.py --dataset inspections --dataset complaints_311
"""

from __future__ import annotations

import argparse

from foodsafety.config import INGEST_SPECS
from foodsafety.ingest import ingest_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        action="append",
        choices=sorted(INGEST_SPECS),
        help="dataset name to ingest (repeatable); default = all",
    )
    args = parser.parse_args()
    names = args.dataset or list(INGEST_SPECS)
    for name in names:
        total = ingest_dataset(name, INGEST_SPECS[name])
        print(f"{name}: {total:,} rows total")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Re-point the building-violations script to the shared path**

Replace the body of `scripts/fetch_building_violations.py` with a thin wrapper (keeps `make fetch_bldg_violations` working, one code path now):

```python
"""Fetch Chicago Building Violations into the raw store (thin wrapper).

The reusable logic now lives in foodsafety.ingest; this stays for the existing
`make fetch_bldg_violations` entry point. Note: the shared path keeps the `id`
column (needed to upsert), unlike the old 4-column-only fetch.

Usage:
    PYTHONPATH=src uv run python scripts/fetch_building_violations.py
"""

from __future__ import annotations

from foodsafety.config import INGEST_SPECS
from foodsafety.ingest import ingest_dataset


def main() -> None:
    total = ingest_dataset("building_violations", INGEST_SPECS["building_violations"])
    print(f"building_violations: {total:,} rows total")


if __name__ == "__main__":
    main()
```

> Note for the implementer: downstream `add_building_features` reads `violation_date, latitude, longitude, department_bureau`. The shared path no longer trims to those four columns (it keeps the full fetched schema incl. `id`). Confirm `add_building_features` selects the columns it needs by name (it does) so the extra columns are harmless; if disk size matters, a column-trim can be added to the spec later — out of scope here.

- [ ] **Step 3: Add the Makefile target**

In `Makefile`, add `ingest` to `.PHONY` and add the targets; re-point `fetch_bldg_violations`:

```makefile
ingest:
	PYTHONPATH=src $(PYTHON) scripts/fetch_all.py

fetch_bldg_violations:
	PYTHONPATH=src $(PYTHON) scripts/fetch_all.py --dataset building_violations
```

Also add a help line under "Python pipeline:" in the `help` target:

```makefile
	@echo "  ingest                 Incremental fetch of all SODA datasets → <DATA_DIR>/raw"
```

- [ ] **Step 4: Smoke-test the CLI wiring (no full network pull)**

Run a syntax/arg check that does not hit the network:

```bash
PYTHONPATH=src uv run python scripts/fetch_all.py --help
```

Expected: argparse help text listing the five dataset choices. (A real pull is exercised in Task 7's local dry-run.)

- [ ] **Step 5: Lint + commit**

```bash
make lint
git add scripts/fetch_all.py scripts/fetch_building_violations.py Makefile
git commit -m "feat(ingest): fetch_all CLI + make ingest, fold in building violations"
```

---

### Task 7: Local end-to-end dry-run (verification, no new code)

**Files:** none (verification task).

This proves the whole path against the live API on the laptop before any AWS work. It is a *small* incremental pull, not a full historical backfill — point at a throwaway dir and let the watermark logic do its thing.

- [ ] **Step 1: Run one dataset to a scratch dir**

```bash
FOODSAFETY_DATA_DIR=/tmp/fsi-dryrun PYTHONPATH=src uv run python \
  scripts/fetch_all.py --dataset complaints_311
```

Expected: progress lines from `fetch_soda_keyset`, then `complaints_311: <N> rows total`, and a file at `/tmp/fsi-dryrun/raw/complaints_311.parquet`.

- [ ] **Step 2: Run it again — prove idempotency**

```bash
FOODSAFETY_DATA_DIR=/tmp/fsi-dryrun PYTHONPATH=src uv run python \
  scripts/fetch_all.py --dataset complaints_311
```

Expected: the second run pulls only the lookback window, and the printed total is **stable (±0)** vs run 1 — confirming no duplication. (A handful of genuinely new rows since run 1 is also fine; what must NOT happen is the count roughly doubling.)

- [ ] **Step 3: Confirm no temp files and a single canonical object**

```bash
ls -la /tmp/fsi-dryrun/raw/
```

Expected: exactly `complaints_311.parquet`, no `*.tmp`.

- [ ] **Step 4: Clean up + final full-suite run**

```bash
rm -rf /tmp/fsi-dryrun
PYTHONPATH=src uv run python -m pytest -q
make lint
```

Expected: full test suite green, lint clean.

- [ ] **Step 5: (No commit — verification only.)** Record the observed run-1 vs run-2 counts in the PR description.

---

## Phase B (separate follow-on plan — AWS scheduling infra)

Not written here on purpose: it is operational (not TDD), depends on the Phase-A image existing, and writing faithful CDK requires first reading the existing `agentcore-deploy/agentcore/cdk` app to match its conventions. Outline of what Plan B will cover, so the whole path is visible:

1. **Container** — `Dockerfile` (slim Python 3.11 + the `foodsafety` package + `s3fs`), `.dockerignore`, build + push to ECR.
2. **CDK stack** — ECS Fargate task definition (0.5 vCPU / 1 GB) running `scripts/fetch_all.py` with `FOODSAFETY_DATA_DIR=s3://food-safety-intelligence-data`; an IAM task role scoped to `s3:GetObject/PutObject/ListBucket` on `food-safety-intelligence-data/raw/*` only; CloudWatch Logs.
3. **Schedule** — EventBridge Scheduler rule, weekly cron (e.g. `cron(0 11 ? * MON *)`), target = run-task.
4. **Backfill + cutover** — one manual run with `FOODSAFETY_DATA_DIR` pointed at S3 to seed the canonical objects; confirm idempotency on a second manual run; then enable the schedule. SageMaker retrain stays manual.

Write Plan B with the brainstorming → writing-plans flow once Phase A is merged.

---

## Self-Review

**Spec coverage:** weekly incremental fetch ✓ (Tasks 1,5,6); no full re-download ✓ (watermark, Task 3); no duplicates ✓ (upsert, Task 4); safe re-runs / atomic write ✓ (Task 2); catches edits ✓ (lookback, Task 3); "latest" trivial to read ✓ (canonical single object, Task 2); local-or-S3 via `FOODSAFETY_DATA_DIR` ✓ (Task 2); new deps `s3fs`/`boto3` ✓ (Task 1); tests for watermark/upsert/atomic-write/idempotency ✓ (Tasks 2–5); local dry-run ✓ (Task 7); script-ify notebook fetches ✓ (consolidated in Tasks 1,5,6); PK column kept ✓ (specs carry `pk`, building-violations folded in Task 6). Infra (Fargate/EventBridge/IAM/ECR) and the one-time S3 backfill → deferred to Plan B (flagged).

**Placeholder scan:** no TBD/TODO tasks; the two "confirm against live schema" notes (license columns) mirror the spec's own caveat and are surfaced as comments, not unfinished steps. Phase B is an explicitly-deferred separate plan, not placeholder tasks.

**Type consistency:** `dataset_uri`/`read_dataset`/`write_dataset` (Task 2) used unchanged in Task 5; `watermark`/`cursor_start` (Task 3) and `upsert` (Task 4) signatures match their use in `ingest_dataset` (Task 5); `DatasetSpec` fields (`dataset_id`, `cursor_col`, `pk`, `start`, `where_extra`) consistent across Tasks 1, 3, 5; `fetch_soda_keyset` kwargs (`dataset_id`, `cursor_col`, `cursor_start`, `where_extra`, `dedupe_on`) match its real signature in `src/foodsafety/io/soda.py`.
