"""Fetch + cache external alcohol/tobacco license datasets for NYC and LA.

CDPH's own model reportedly weighs alcohol + tobacco license status above the
environmental features this project already rejected (see
docs/model-experiments.md). Chicago's Business Licenses data carries these
natively (foodsafety.features.license_history_features); NYC and LA's
inspection feeds don't, so this script pulls a separate license dataset per
city per license type and caches it under data/raw/ (gitignored, like every
other raw pull in this repo) for scripts/run_city_ablations.py to join by
address.

Sources (public, no auth required):
  NYC alcohol : NY State Liquor Authority "Current Liquor Authority Active
                Licenses" (data.ny.gov 9s3h-dpkz), filtered to the 5 NYC
                counties. Has ``originalissuedate`` — leak-safe per anchor.
  NYC tobacco : NYC DCWP "Active Tobacco Retail Dealer Licenses"
                (data.cityofnewyork.us adw8-wvxb). Has ``license_creation_date``
                — leak-safe per anchor.
  LA alcohol  : LA County's own ArcGIS FeatureServer layer backing its public
                "Alcohol Beverage Sales Locations" map. Issue-date fields on
                this layer are sparsely populated (confirmed by inspection),
                so this is treated as a CURRENT-STATUS flag, not date-gated —
                acceptable here because LA's whole modeling window is short
                (~2023-2026, see build_la_scores.LA_TRAIN_START), so "current"
                is a reasonable stand-in for "as of the anchor date".
  LA tobacco  : CDTFA's statewide "Licensed California Cigarette and Tobacco
                Products Retailers" list (cdtfa.ca.gov, current snapshot only
                — by law CDTFA cannot publish an issuance date). Same
                current-status caveat as LA alcohol, more acute since this
                file truly has no historical dimension at all.

Run:
    PYTHONPATH=src uv run --with openpyxl python scripts/fetch_alcohol_tobacco_licenses.py

``--with openpyxl`` is only needed for the one-off CDTFA .xlsx parse (LA
tobacco); it is deliberately NOT added to pyproject.toml since this script is
an experiment-only data pull, not part of the served pipeline (CLAUDE.md: no
new deps without a PR). Once each dataset is cached under data/raw/, reruns
skip the network call (and the openpyxl import) entirely.
"""

from __future__ import annotations

import io
import json
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
RAW_DIR = REPO / "data" / "raw"

NYC_ALCOHOL_OUT = RAW_DIR / "nyc_alcohol_licenses.parquet"
NYC_TOBACCO_OUT = RAW_DIR / "nyc_tobacco_licenses.parquet"
LA_ALCOHOL_OUT = RAW_DIR / "la_alcohol_licenses.parquet"
LA_TOBACCO_OUT = RAW_DIR / "la_tobacco_licenses.parquet"

NYC_COUNTIES = ("New York", "Kings", "Queens", "Bronx", "Richmond")


def _get_json(url: str, timeout: int = 60):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def fetch_nyc_alcohol(force: bool = False) -> pd.DataFrame:
    """NYS Liquor Authority active licenses, filtered to the 5 NYC counties."""
    if NYC_ALCOHOL_OUT.exists() and not force:
        return pd.read_parquet(NYC_ALCOHOL_OUT)
    where = "premisescounty in(" + ",".join(f"'{c}'" for c in NYC_COUNTIES) + ")"
    params = {
        "$limit": "50000",
        "$where": where,
        "$select": (
            "licensepermitid,premisescounty,description,legalname,dba,"
            "actualaddressofpremises,city,zipcode,originalissuedate"
        ),
    }
    url = "https://data.ny.gov/resource/9s3h-dpkz.json?" + urllib.parse.urlencode(params)
    rows = _get_json(url)
    df = pd.DataFrame(rows)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(NYC_ALCOHOL_OUT, index=False)
    print(f"  nyc alcohol: {len(df):,} rows -> {NYC_ALCOHOL_OUT}")
    return df


def fetch_nyc_tobacco(force: bool = False) -> pd.DataFrame:
    """NYC DCWP active tobacco retail dealer licenses (offset-paginated)."""
    if NYC_TOBACCO_OUT.exists() and not force:
        return pd.read_parquet(NYC_TOBACCO_OUT)
    cols = (
        "license_nbr,business_name,address_building,address_street_name,"
        "address_borough,address_zip,license_creation_date"
    )
    rows: list[dict] = []
    offset = 0
    page = 50000
    while True:
        params = {"$limit": str(page), "$offset": str(offset), "$select": cols}
        url = "https://data.cityofnewyork.us/resource/adw8-wvxb.json?" + urllib.parse.urlencode(
            params
        )
        batch = _get_json(url)
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    df = pd.DataFrame(rows)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(NYC_TOBACCO_OUT, index=False)
    print(f"  nyc tobacco: {len(df):,} rows -> {NYC_TOBACCO_OUT}")
    return df


def fetch_la_alcohol(force: bool = False) -> pd.DataFrame:
    """LA County's own ArcGIS layer backing its public alcohol-license map."""
    if LA_ALCOHOL_OUT.exists() and not force:
        return pd.read_parquet(LA_ALCOHOL_OUT)
    base = (
        "https://services.arcgis.com/RmCCgQtiZLDCtblq/arcgis/rest/services/"
        "Alcohol_Beverage_Sales_LA_County_Public_View/FeatureServer/0/query"
    )
    fields = "Premise_Street_Address_1,Premise_City,Premise_Zip,Status"
    rows: list[dict] = []
    offset = 0
    page = 2000
    while True:
        params = {
            "where": "1=1",
            "outFields": fields,
            "resultRecordCount": str(page),
            "resultOffset": str(offset),
            "f": "json",
        }
        url = base + "?" + urllib.parse.urlencode(params)
        data = _get_json(url)
        feats = data.get("features", [])
        rows.extend(f["attributes"] for f in feats)
        if len(feats) < page:
            break
        offset += page
    df = pd.DataFrame(rows)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(LA_ALCOHOL_OUT, index=False)
    print(f"  la alcohol: {len(df):,} rows -> {LA_ALCOHOL_OUT}")
    return df


def fetch_la_tobacco(force: bool = False) -> pd.DataFrame:
    """CDTFA statewide licensed cigarette/tobacco retailers (current snapshot)."""
    if LA_TOBACCO_OUT.exists() and not force:
        return pd.read_parquet(LA_TOBACCO_OUT)
    import openpyxl

    url = "https://www.cdtfa.ca.gov/taxes-and-fees/LR-CA-Statewide.xlsx"
    with urllib.request.urlopen(url, timeout=60) as r:
        raw_bytes = r.read()
    wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), read_only=True)
    ws = wb.worksheets[0]
    rows_iter = ws.iter_rows(values_only=True)
    header = None
    records = []
    for row in rows_iter:
        if header is None:
            if row and row[0] == "License #":
                header = ["license_nbr", "taxpayer", "dba", "address", "city", "state", "zip"]
            continue
        if row[0] is None:
            continue
        records.append(dict(zip(header, row[:7], strict=False)))
    # Statewide file (CDTFA doesn't offer a county filter) — the join step
    # matches only rows whose zip appears in LA's own facility list.
    df = pd.DataFrame(records)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(LA_TOBACCO_OUT, index=False)
    print(f"  la tobacco (statewide, {len(df):,} rows) -> {LA_TOBACCO_OUT}")
    return df


def main() -> None:
    print("Fetching external alcohol/tobacco license datasets...")
    fetch_nyc_alcohol()
    fetch_nyc_tobacco()
    fetch_la_alcohol()
    fetch_la_tobacco()


if __name__ == "__main__":
    main()
