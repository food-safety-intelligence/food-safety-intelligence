"""NOAA GHCN-Daily loader — Chicago O'Hare station (citywide weather proxy).

Per ``docs/decisions/0014-noaa-weather-citywide-station.md``: GHCN-Daily publishes
one plain CSV per station, no API key required, so this is a single GET + parse —
no pagination/retry machinery like ``foodsafety.io.soda`` needs for the Socrata
API. We use Chicago O'Hare International Airport (GHCND ID ``USW00094846``) as a
single citywide weather signal — the inspections data has no per-restaurant
weather station, and O'Hare is NOAA's most complete, longest-running Chicago
station.

GHCN-Daily's ``by_station`` format is long: one row per
``(station, date, element)`` with raw integer ``DATA_VALUE`` in tenths of a unit
(tenths of °C for TMAX/TMIN, tenths of mm for PRCP, mm for SNOW — see NOAA's
``readme.txt``). ``fetch_noaa_ghcnd`` pivots to one row per date with cleaned,
unit-converted columns.
"""

from __future__ import annotations

import gzip
import io
import time

import pandas as pd
import requests

NOAA_GHCND_BASE = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/by_station"

# Chicago O'Hare International Airport — NOAA's most complete, longest-running
# Chicago station; used as a single citywide weather proxy (the inspections
# data has no per-restaurant weather station).
CHICAGO_OHARE_STATION_ID = "USW00094846"

# Elements we keep; GHCN-Daily carries dozens (snow depth, wind, etc.) that are
# unused here. Keeping the pivot narrow avoids dragging in element codes the
# rest of the pipeline never reads.
_ELEMENTS = {"TMAX", "TMIN", "PRCP", "SNOW"}

_GHCND_COLUMNS = [
    "station_id",
    "date",
    "element",
    "data_value",
    "m_flag",
    "q_flag",
    "s_flag",
    "obs_time",
]


def fetch_noaa_ghcnd(
    station_id: str = CHICAGO_OHARE_STATION_ID,
    *,
    timeout: int = 60,
    max_retries: int = 4,
) -> pd.DataFrame:
    """Fetch + clean one GHCN-Daily station's full daily history.

    Returns one row per ``date`` with columns:
        date          datetime64 — calendar date
        tmax_c        float64    — daily max temperature, °C
        tmin_c        float64    — daily min temperature, °C
        precip_mm     float64    — daily precipitation, mm
        snow_mm       float64    — daily snowfall, mm

    Rows that failed NOAA's own quality-control flag (``Q-FLAG`` non-blank) are
    dropped — a flagged value is NOAA's own assessment that the reading is
    suspect (e.g. a sensor spike), not a transient fetch error, so it's cleaned
    here rather than passed through for a downstream consumer to filter.
    """
    raw = _request_with_retry(station_id, timeout, max_retries)
    df = pd.read_csv(
        io.BytesIO(gzip.decompress(raw)),
        header=None,
        names=_GHCND_COLUMNS,
        dtype={"station_id": "string", "element": "string", "q_flag": "string"},
    )

    df = df[df["element"].isin(_ELEMENTS)]
    # Q-FLAG blank/NaN means the value passed NOAA's quality control; any other
    # value (e.g. "G" gap, "X" failed bounds check) flags a suspect reading.
    df = df[df["q_flag"].isna() | (df["q_flag"].str.strip() == "")]

    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    wide = df.pivot_table(index="date", columns="element", values="data_value", aggfunc="first")
    wide = wide.reindex(columns=sorted(_ELEMENTS))

    out = pd.DataFrame(index=wide.index)
    # TMAX/TMIN are tenths of °C; PRCP is tenths of mm; SNOW is already mm.
    out["tmax_c"] = wide["TMAX"] / 10.0
    out["tmin_c"] = wide["TMIN"] / 10.0
    out["precip_mm"] = wide["PRCP"] / 10.0
    out["snow_mm"] = wide["SNOW"]

    return out.reset_index().sort_values("date", kind="mergesort").reset_index(drop=True)


def _request_with_retry(station_id: str, timeout: int, max_retries: int) -> bytes:
    """GET the station's gzipped CSV with exponential-backoff retry.

    Mirrors ``foodsafety.io.soda._request_with_retry``: retries on
    ReadTimeout / ConnectionError only, not on 4xx/5xx (a bad station id is a
    request error, not a transient one).
    """
    url = f"{NOAA_GHCND_BASE}/{station_id}.csv.gz"
    for attempt in range(max_retries):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r.content
        except (requests.Timeout, requests.ConnectionError) as e:
            if attempt == max_retries - 1:
                raise
            wait = 5 * (2**attempt)
            print(
                f"  NOAA fetch attempt {attempt + 1} failed ({type(e).__name__}); retry in {wait}s"
            )
            time.sleep(wait)
    raise RuntimeError("unreachable")
