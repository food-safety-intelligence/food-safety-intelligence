"""Geographic sanity checks for Chicago inspection coordinates.

lat/lon are NOT model features — they drive the web-app map and the 311 spatial
join only. So an out-of-range coordinate can't corrupt the model, but it would
misplace a map pin or produce a wrong 311 count. We **warn and null** such
coordinates (emit a warning, then set them to NaN) but **keep the row**: a bad
geocode is a broken display field, not a reason to drop a valid inspection (real
label, real prior_* history, a real restaurant). "Warn", not a persisted flag
column — the signal is the log line, not a new field. Nulling routes the bad
point into the same "missing geo" path every consumer already handles — the map
skips the pin (`getMapPins` filters null/NaN) and any spatial join over the
cleaned frame counts 0 — instead of plotting it in Lake Michigan or computing a
wrong spatial count. The warning still surfaces the upstream geocoding bug so it
gets fixed rather than silently hidden.

Most useful as insurance for the Phase-2 incremental ingestion; the current
snapshot is 100% inside the bbox, and ~0.4% of rows already have (handled) null
geo, so nulling a bad coord introduces no new state.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

# Generous Chicago bounding box (covers the city + O'Hare). Points outside this
# are data-entry errors or null-island (0, 0).
CHICAGO_LAT_MIN, CHICAGO_LAT_MAX = 41.60, 42.05
CHICAGO_LON_MIN, CHICAGO_LON_MAX = -87.95, -87.52


def out_of_chicago_bbox(lat, lon) -> np.ndarray:
    """Boolean mask: True where a (lat, lon) pair is **present but outside** the
    Chicago bounding box (includes null-island 0,0).

    Missing coordinates are ``False`` — they're "unknown", not "wrong", and are
    already handled (the 311 join drops them; the map skips the pin).
    """
    lat_arr = pd.to_numeric(pd.Series(lat), errors="coerce").to_numpy()
    lon_arr = pd.to_numeric(pd.Series(lon), errors="coerce").to_numpy()
    present = ~(np.isnan(lat_arr) | np.isnan(lon_arr))
    inside = (
        (lat_arr >= CHICAGO_LAT_MIN)
        & (lat_arr <= CHICAGO_LAT_MAX)
        & (lon_arr >= CHICAGO_LON_MIN)
        & (lon_arr <= CHICAGO_LON_MAX)
    )
    return present & ~inside


def warn_and_null_out_of_bbox(
    df: pd.DataFrame, *, lat_col: str = "latitude", lon_col: str = "longitude"
) -> pd.DataFrame:
    """Return a copy with out-of-Chicago-bbox coordinates set to NaN (row kept).

    Warns with the count so the upstream geocoding bug surfaces (a log line, not
    a persisted flag column). Nulling — not dropping — keeps the valid inspection
    and routes the bad point into the existing missing-geo path (map skips pin,
    any spatial join over the cleaned frame counts 0).
    """
    if lat_col not in df.columns or lon_col not in df.columns:
        return df
    out = df.copy()
    mask = out_of_chicago_bbox(out[lat_col], out[lon_col])
    n = int(mask.sum())
    if n:
        warnings.warn(
            f"{n} row(s) had lat/lon outside the Chicago bounding box; nulling "
            "those coordinates (row kept — map pin skipped). "
            "Review the upstream geocoding.",
            stacklevel=2,
        )
        rows = np.flatnonzero(mask)
        out.iloc[
            rows, [out.columns.get_loc(lat_col), out.columns.get_loc(lon_col)]
        ] = np.nan
    return out
