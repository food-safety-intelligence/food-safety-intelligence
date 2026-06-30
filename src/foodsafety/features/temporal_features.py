"""Calendar-based features derived from ``inspection_date``.

Cheap, leak-free, and well-motivated:

  * **Seasonality.** Food-safety violations are seasonal — Chicago summers
    drive cold-holding failures, winters the inverse. The 2014 Chicago
    forecasting paper used a 3-day rolling high temperature; month and
    quarter are zero-cost proxies for that. NOAA weather itself is now
    implemented (``foodsafety.features.weather_features``) as an opt-in
    family pending an A/B that tests whether it adds *incremental* signal
    over these calendar proxies — see ``docs/data_dictionary.md`` § NOAA
    weather.
  * **Day-of-week.** Inspection cadence varies by weekday. Weekend
    inspections are rare; Monday inspections often follow weekend complaints.

No leak risk: these are derived purely from the anchor's own date, no
dependence on any other row.
"""

from __future__ import annotations

import pandas as pd

# Quarter → season mapping used by the inspection-procedure literature.
# Winter = Dec/Jan/Feb (months 12/1/2), Spring = Mar/Apr/May, etc. We treat
# December as Winter — a calendar quarter would put it with Q4.
_MONTH_TO_SEASON = {
    12: "Winter",
    1: "Winter",
    2: "Winter",
    3: "Spring",
    4: "Spring",
    5: "Spring",
    6: "Summer",
    7: "Summer",
    8: "Summer",
    9: "Fall",
    10: "Fall",
    11: "Fall",
}


def add_temporal_features(
    df: pd.DataFrame,
    *,
    date_col: str = "inspection_date",
) -> pd.DataFrame:
    """Append calendar features derived from ``date_col``.

    Features added:
        temporal_month    (Int8)     — 1..12
        temporal_dow      (Int8)     — 0=Monday .. 6=Sunday
        temporal_quarter  (Int8)     — 1..4
        temporal_year     (Int16)    — calendar year (for year-fixed-effects)
        temporal_season   (category) — Winter / Spring / Summer / Fall
    """
    out = df.copy()
    out[date_col] = pd.to_datetime(out[date_col])

    out["temporal_month"] = out[date_col].dt.month.astype("Int8")
    out["temporal_dow"] = out[date_col].dt.dayofweek.astype("Int8")
    out["temporal_quarter"] = out[date_col].dt.quarter.astype("Int8")
    out["temporal_year"] = out[date_col].dt.year.astype("Int16")
    out["temporal_season"] = (
        out["temporal_month"].astype(int).map(_MONTH_TO_SEASON).astype("category")
    )

    return out
