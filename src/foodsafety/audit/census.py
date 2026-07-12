"""Census / ACS demographic join for the fairness audit — AUDIT-ONLY.

Maps each establishment ``(lat, lon)`` to its census tract, then attaches
American Community Survey (ACS) 5-year tract attributes. The result is used only
to *measure* disparate impact (decisions 0004 / 0005) — no column produced here
is ever a model feature, and this module is not imported by the model pipeline,
the serving code, or the app. It lives behind the ``audit`` optional-dependency
extra (geopandas + shapely).

Two data pulls, both cached like every other fetch in the repo (``io.cache``):
  * TIGER/Line tract shapefiles per state (point-in-polygon → tract GEOID).
  * ACS 5-year tables per state (tract → demographics).

ACS variable codes below were validated against the live Census data dictionary
(``api.census.gov/.../groups/<table>.json``); they are stable across the recent
5-year vintages this audit uses.
"""

from __future__ import annotations

import io
import os
import zipfile

import numpy as np
import pandas as pd
import requests

from foodsafety.audit import frame
from foodsafety.config import RAW_DIR
from foodsafety.io import cache, storage

# ACS 5-year vintage. Codes were validated on 2022; override with FOODSAFETY_ACS_YEAR.
ACS_YEAR: int = int(os.environ.get("FOODSAFETY_ACS_YEAR", "2022"))
ACS_BASE: str = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5"
TIGER_YEAR: int = ACS_YEAR
TIGER_BASE: str = f"https://www2.census.gov/geo/tiger/TIGER{TIGER_YEAR}/TRACT"

# City → the state FIPS code its tracts live in. NYC spans five counties but one
# state (36); LA County is in California (06). We pull whole-state tracts and join
# on GEOID, so county filtering is unnecessary.
CITY_STATE_FIPS: dict[str, str] = {"chicago": "17", "nyc": "36", "la": "06"}

# Raw ACS estimate codes we request (union across the primary demographic axes).
_ACS_CODES: tuple[str, ...] = (
    "B19013_001E",  # median household income
    "B03002_001E",  # race total
    "B03002_003E",  # not-Hispanic White alone
    "B03002_004E",  # not-Hispanic Black alone
    "B03002_006E",  # not-Hispanic Asian alone
    "B03002_012E",  # Hispanic or Latino
    "B17001_001E",  # poverty universe
    "B17001_002E",  # income below poverty
    "B05002_001E",  # nativity total
    "B05002_013E",  # foreign born
    "C16002_001E",  # households total
    "C16002_004E",  # Spanish, limited-English household
    "C16002_007E",  # other Indo-European, limited-English
    "C16002_010E",  # Asian/Pacific Island, limited-English
    "C16002_013E",  # other languages, limited-English
    "B01003_001E",  # total population
)

# Continuous demographic columns → their within-city quantile column name.
_CONTINUOUS_TO_QUANTILE: dict[str, str] = {
    "area_median_income": "area_income_q",
    "area_pct_nonwhite": "area_pct_nonwhite_q",
    "area_pct_poverty": "area_pct_poverty_q",
    "area_pct_foreign_born": "area_pct_foreign_born_q",
    "area_pct_limited_english": "area_pct_limited_english_q",
}


def _safe_ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    """Numerator / denominator with 0-or-missing denominators → NaN (not inf)."""
    den = den.where(den > 0)
    return num / den


def fetch_acs_tracts(state_fips: str) -> pd.DataFrame:
    """All tracts in a state with the derived demographic columns.

    One API call per state (no key needed at this volume; set CENSUS_API_KEY to
    raise rate limits). Cached as parquet under ``<RAW_DIR>/census/``.
    """

    def _fetch() -> pd.DataFrame:
        params = {
            "get": ",".join(("NAME", *_ACS_CODES)),
            "for": "tract:*",
            "in": f"state:{state_fips}",
        }
        # The Census data API requires a key (free, instant signup). Missing/invalid
        # keys come back as an HTML "Missing Key" page with a 200, which would
        # otherwise blow up as an opaque JSONDecodeError — so check explicitly.
        key = os.environ.get("CENSUS_API_KEY")
        if not key:
            raise RuntimeError(
                "CENSUS_API_KEY is not set. The census audit join needs a free Census "
                "API key (instant: https://api.census.gov/data/key_signup.html). "
                "Add CENSUS_API_KEY=... to your environment or .env and re-run."
            )
        params["key"] = key
        resp = requests.get(ACS_BASE, params=params, timeout=60)
        resp.raise_for_status()
        if "application/json" not in resp.headers.get("Content-Type", ""):
            raise RuntimeError(
                f"Census API returned non-JSON (likely an invalid CENSUS_API_KEY). "
                f"First line: {resp.text.splitlines()[0] if resp.text else '<empty>'!r}"
            )
        rows = resp.json()
        raw = pd.DataFrame(rows[1:], columns=rows[0])
        for c in _ACS_CODES:
            # ACS uses large negative sentinels (e.g. -666666666) for "no data".
            raw[c] = pd.to_numeric(raw[c], errors="coerce").where(lambda s: s > -1e6)
        geoid = raw["state"] + raw["county"] + raw["tract"]
        out = pd.DataFrame({"tract_geoid": geoid})
        out["area_median_income"] = raw["B19013_001E"]
        out["area_pct_nonwhite"] = 1.0 - _safe_ratio(raw["B03002_003E"], raw["B03002_001E"])
        out["area_pct_poverty"] = _safe_ratio(raw["B17001_002E"], raw["B17001_001E"])
        out["area_pct_foreign_born"] = _safe_ratio(raw["B05002_013E"], raw["B05002_001E"])
        limited = raw[["C16002_004E", "C16002_007E", "C16002_010E", "C16002_013E"]].sum(axis=1)
        out["area_pct_limited_english"] = _safe_ratio(limited, raw["C16002_001E"])
        out["area_population"] = raw["B01003_001E"]
        out["area_dominant_group"] = _dominant_group(raw)
        return out

    return cache.load_or_fetch(
        f"acs_{state_fips}_{ACS_YEAR}", _fetch, cache_dir=storage.join(str(RAW_DIR), "census")
    )


def _dominant_group(raw: pd.DataFrame) -> pd.Series:
    """Majority race/ethnicity per tract, else "no majority" (share < 50%)."""
    total = raw["B03002_001E"]
    shares = pd.DataFrame(
        {
            "White": _safe_ratio(raw["B03002_003E"], total),
            "Black": _safe_ratio(raw["B03002_004E"], total),
            "Asian": _safe_ratio(raw["B03002_006E"], total),
            "Hispanic": _safe_ratio(raw["B03002_012E"], total),
        }
    )
    # idxmax raises on all-NA rows (tracts with no race data), so only rank rows
    # that have at least one non-null share; the rest stay NaN.
    valid = shares.notna().any(axis=1)
    top = pd.Series(np.nan, index=shares.index, dtype="object")
    if valid.any():
        top.loc[valid] = shares.loc[valid].idxmax(axis=1)
    is_majority = shares.max(axis=1) >= 0.5  # NaN (all-NA row) compares False
    return top.where(is_majority, "no majority").where(valid, np.nan)


def _tiger_tracts_gdf(state_fips: str):
    """Read (and cache) the state's TIGER tract polygons as a GeoDataFrame.

    Imported lazily so the module loads without the ``audit`` extra installed;
    only ``attach_area_demographics`` needs geopandas.
    """
    import geopandas as gpd

    fname = f"tl_{TIGER_YEAR}_{state_fips}_tract"
    local_zip = storage.join(str(RAW_DIR), "census", f"{fname}.zip")
    if not storage.exists(local_zip):
        url = f"{TIGER_BASE}/{fname}.zip"
        resp = requests.get(url, timeout=180)
        resp.raise_for_status()
        # Extract to a sibling dir so pyogrio reads the .shp set directly.
        dest = storage.join(str(RAW_DIR), "census", fname)
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            os.makedirs(dest, exist_ok=True)
            zf.extractall(dest)
    dest = storage.join(str(RAW_DIR), "census", fname)
    gdf = gpd.read_file(os.path.join(dest, f"{fname}.shp"))
    return gdf[["GEOID", "ALAND", "geometry"]]


def _points_to_tract(df: pd.DataFrame, state_fips: str) -> pd.DataFrame:
    """Spatial-join lat/lon → tract GEOID + tract land area (for density)."""
    import geopandas as gpd

    tracts = _tiger_tracts_gdf(state_fips)
    pts = gpd.GeoDataFrame(
        df.index.to_frame(name="_row"),
        geometry=gpd.points_from_xy(df["lon"], df["lat"]),
        crs="EPSG:4326",
    ).to_crs(tracts.crs)
    joined = gpd.sjoin(pts, tracts, how="left", predicate="within")
    # Drop duplicate matches on tract boundaries (keep first) and realign to df.
    joined = joined[~joined.index.duplicated(keep="first")]
    out = pd.DataFrame(index=df.index)
    out["tract_geoid"] = joined["GEOID"]
    out["_aland_m2"] = joined["ALAND"]
    return out


def attach_area_demographics(df: pd.DataFrame, *, city: str) -> pd.DataFrame:
    """Attach the census columns (§ ``frame.CENSUS_COLUMNS``) to an audit frame.

    Adds the tract GEOID, the raw demographic columns, population density, and the
    within-city quantile buckets. Establishments whose coordinates fall outside
    any tract (missing / bad geo) get NaN demographics and drop out of the
    demographic axes — reported as coverage, never imputed.
    """
    state_fips = CITY_STATE_FIPS.get(city)
    if state_fips is None:
        raise ValueError(f"No state FIPS mapping for city {city!r}; add it to CITY_STATE_FIPS")

    tract = _points_to_tract(df, state_fips)
    acs = fetch_acs_tracts(state_fips)
    merged = tract.join(df).merge(acs, on="tract_geoid", how="left")
    merged.index = df.index

    # Population density: residents per square kilometre of tract land area.
    merged["area_pop_density"] = _safe_ratio(merged["area_population"], merged["_aland_m2"] / 1e6)
    merged = merged.drop(columns=["_aland_m2"])

    # Within-city quantile buckets for the continuous demographic axes.
    for raw_col, q_col in _CONTINUOUS_TO_QUANTILE.items():
        merged[q_col] = frame.quantile_bucket(merged[raw_col])

    return merged
