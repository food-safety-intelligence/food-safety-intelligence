"""Download all raw Chicago datasets and upload them to S3.

Fetches four datasets from the Chicago SODA API and writes them as parquet
to s3://<bucket>/raw/. Run once to seed the bucket; re-run is idempotent
(existing files are overwritten).

Usage:
    uv run python scripts/download_to_s3.py --bucket YOUR-BUCKET-NAME

Requirements (already in pyproject.toml dev deps):
    pip install boto3

AWS credentials must be configured via `aws configure` or environment vars
(AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION).
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import boto3
import pandas as pd

# Allow importing from src/foodsafety/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from foodsafety.config import DATASETS, RELEVANT_SR_TYPES, TRAIN_START_DATE
from foodsafety.io.soda import fetch_soda, fetch_soda_keyset


def upload_df(df: pd.DataFrame, s3: "boto3.client", bucket: str, key: str) -> None:
    buf = io.BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)
    s3.put_object(Bucket=bucket, Key=key, Body=buf.getvalue())
    print(f"  uploaded s3://{bucket}/{key} ({len(df):,} rows, {buf.tell() / 1e6:.1f} MB)")


def download_inspections() -> pd.DataFrame:
    print("\n[1/4] Food Inspections (2010-present) ...")
    # Fetch from 2012 onward: pre-2019 rows are burn-in for prior_* features.
    return fetch_soda(
        DATASETS["inspections"],
        where="inspection_date >= '2012-01-01T00:00:00'",
        order="inspection_date ASC, inspection_id ASC",
    )


def download_complaints() -> pd.DataFrame:
    print("\n[2/4] 311 Complaints (food-safety-relevant types, 2019-present) ...")
    sr_list = ", ".join(f"'{t}'" for t in RELEVANT_SR_TYPES)
    return fetch_soda_keyset(
        DATASETS["complaints_311"],
        cursor_col="created_date",
        cursor_start=f"{TRAIN_START_DATE}T00:00:00",
        where_extra=f"sr_type in({sr_list})",
        dedupe_on="sr_number",
    )


def download_licenses_current() -> pd.DataFrame:
    print("\n[3/4] Business Licenses — current active ...")
    return fetch_soda(
        DATASETS["licenses_current"],
        order="license_id ASC",
    )


def download_licenses_historical() -> pd.DataFrame:
    print("\n[4/4] Business Licenses — historical ...")
    return fetch_soda(
        DATASETS["licenses_historical"],
        order="license_number ASC, date_issued ASC",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Chicago datasets → S3")
    parser.add_argument("--bucket", required=True, help="S3 bucket name")
    parser.add_argument("--prefix", default="raw", help="S3 key prefix (default: raw)")
    parser.add_argument("--region", default=None, help="AWS region (default: from aws configure)")
    parser.add_argument("--skip", nargs="*", default=[], metavar="FILENAME",
                        help="Filenames to skip, e.g. --skip inspections.parquet complaints_311.parquet")
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)

    datasets = [
        (download_inspections,         "inspections.parquet"),
        (download_complaints,          "complaints_311.parquet"),
        (download_licenses_current,    "licenses_current.parquet"),
        (download_licenses_historical, "licenses_historical.parquet"),
    ]

    for fetch_fn, filename in datasets:
        if filename in args.skip:
            print(f"\nSkipping {filename}")
            continue
        df = fetch_fn()
        key = f"{args.prefix}/{filename}"
        upload_df(df, s3, args.bucket, key)

    print(f"\nDone. All datasets are at s3://{args.bucket}/{args.prefix}/")


if __name__ == "__main__":
    main()
