"""Ingest raw Chicago SODA datasets to the configured data dir (local or S3).

Stage 1 of the pipeline, split out from feature-building: this script's only job is
to pull each source dataset from the Chicago SODA API and persist the raw records
under ``RAW_DIR`` (``FOODSAFETY_DATA_DIR/raw`` — a local path by default, or an
``s3://…`` prefix in the AWS iteration). It writes nothing else; feature-building
reads these raw parquets back in Stage 2. Previously these pulls happened as a side
effect of the first feature notebook run; this makes the pull its own entry point.

Run:
    PYTHONPATH=src uv run python scripts/ingest_raw.py                  # all datasets
    PYTHONPATH=src uv run python scripts/ingest_raw.py inspections      # one or more
    FOODSAFETY_DATA_DIR=s3://food-safety-intelligence-data \\
        PYTHONPATH=src uv run python scripts/ingest_raw.py              # pull to S3

``load_or_fetch`` skips a dataset whose raw parquet already exists at the target;
pass ``--force`` to re-pull it. The 311 and building pulls are keyset-paginated and
shard-resume, so a crash mid-pull resumes from the last page on the next run.
"""

from __future__ import annotations

import argparse

from foodsafety.config import DATASETS, INGEST_SPECS, RAW_DIR, RELEVANT_SR_TYPES
from foodsafety.ingest import ingest_dataset
from foodsafety.io import storage
from foodsafety.io.cache import load_or_fetch
from foodsafety.io.soda import fetch_soda, fetch_soda_keyset


def _shards(name: str) -> str:
    """Crash-resume shard prefix for a keyset pull, under RAW_DIR/_shards/<name>."""
    return storage.join(str(RAW_DIR), "_shards", name)


def _fetch_inspections():
    # All food inspections; ordered for stable pagination.
    return fetch_soda(DATASETS["inspections"], order="inspection_date ASC, inspection_id ASC")


def _fetch_311():
    # ~1.1M rows since 2019 across the 8 food-relevant SR types. Keyset-paginate on
    # created_date (offset times out past ~500k); dedupe on sr_number (the table's
    # nested `location` dict breaks the default drop_duplicates).
    quoted = ", ".join(f"'{t}'" for t in RELEVANT_SR_TYPES)
    return fetch_soda_keyset(
        DATASETS["complaints_311"],
        cursor_col="created_date",
        cursor_start="2019-01-01T00:00:00",
        where_extra=f"sr_type IN ({quoted})",
        dedupe_on="sr_number",
        shard_dir=_shards("complaints_311"),
    )


def _fetch_licenses_current():
    # ~80k rows; small enough to pull whole and filter downstream.
    return fetch_soda(DATASETS["licenses_current"], order="license_number ASC")


def _fetch_licenses_historical():
    # Food-related licenses only — server-side filter keeps the pull tractable.
    # Must stay in sync with foodsafety.config._FOOD_LICENSE_WHERE.
    where = (
        "(upper(license_description) like '%FOOD%'"
        " OR upper(license_description) like '%RESTAURANT%'"
        " OR upper(license_description) like '%TAVERN%'"
        " OR upper(license_description) like '%LIQUOR%'"
        " OR upper(license_description) like '%KITCHEN%'"
        " OR upper(license_description) like '%TOBACCO%'"
        " OR upper(license_description) like '%CONSUMPTION ON PREMISES%'"
        " OR upper(license_description) like '%PACKAGE GOODS%')"
    )
    return fetch_soda(
        DATASETS["licenses_historical"],
        where=where,
        order="date_issued ASC, license_number ASC",
    )


# Building permits / violations: physical-plant condition for the block-face join.
# The window starts 2017-01-01 — derived from the existing raw parquets' min
# issue_date / violation_date. Keyset-paginate (violations is ~635k rows, past the
# offset limit); both tables carry a nested `location` dict, so dedupe on `id`.
def _fetch_building_permits():
    return fetch_soda_keyset(
        DATASETS["building_permits"],
        cursor_col="issue_date",
        cursor_start="2017-01-01T00:00:00",
        dedupe_on="id",
        shard_dir=_shards("building_permits"),
    )


def _fetch_building_violations():
    return fetch_soda_keyset(
        DATASETS["building_violations"],
        cursor_col="violation_date",
        cursor_start="2017-01-01T00:00:00",
        dedupe_on="id",
        shard_dir=_shards("building_violations"),
    )


FETCHERS = {
    "inspections": _fetch_inspections,
    "complaints_311": _fetch_311,
    "licenses_current": _fetch_licenses_current,
    "licenses_historical": _fetch_licenses_historical,
    "building_permits": _fetch_building_permits,
    "building_violations": _fetch_building_violations,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "datasets",
        nargs="*",
        choices=list(FETCHERS),
        help="datasets to pull (default: all)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="re-pull even if the raw parquet already exists at the target",
    )
    ap.add_argument(
        "--incremental",
        action="store_true",
        help="incremental mode: read watermark from existing data, fetch only "
        "new/edited rows (with lookback), upsert on natural key",
    )
    args = ap.parse_args()

    names = args.datasets or list(FETCHERS)
    print(f"Ingest target (RAW_DIR): {RAW_DIR}")

    if args.incremental:
        for name in names:
            if name not in INGEST_SPECS:
                print(f"  {name}: no INGEST_SPEC, skipping incremental")
                continue
            df = ingest_dataset(name, INGEST_SPECS[name])
            target = storage.join(str(RAW_DIR), f"{name}.parquet")
            print(f"  {name}: {len(df):,} rows -> {target}")
        return

    for name in names:
        target = storage.join(str(RAW_DIR), f"{name}.parquet")
        if args.force and storage.exists(target):
            print(f"--force: removing existing {target}")
            storage.delete(target)
        df = load_or_fetch(name, FETCHERS[name])
        print(f"  {name}: {len(df):,} rows -> {target}")


if __name__ == "__main__":
    main()
