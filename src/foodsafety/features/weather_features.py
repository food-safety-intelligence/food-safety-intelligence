"""Citywide daily-weather features, joined on date (NOAA GHCN-Daily, O'Hare).

Unlike every other ``prior_*`` module, this one has no ``license_id`` grouping:
weather is a single citywide signal shared by every restaurant inspected on the
same day, so the rolling windows are computed once on the daily weather series
(``foodsafety.io.noaa.fetch_noaa_ghcnd``) and then joined onto the anchor table
by date.

Motivation (``docs/data_dictionary.md`` § NOAA weather): heat stresses
refrigeration and drives pest activity; freeze stress affects plumbing/water
systems. `temporal_month` / `temporal_quarter` already capture coarse
seasonality — these features test whether actual daily weather carries
*incremental* signal over that proxy, per the 2014 Chicago forecasting paper's
use of a 3-day rolling high temperature.

Leak guard: every column is ``.shift(1)``-ed on the daily series before the
join, so a row anchored on date D only sees weather strictly BEFORE D — the
same "strictly before" discipline as the license-level ``prior_*`` columns in
``inspection_features.py``, just without a groupby (there's only one weather
series, not one per license).
"""

from __future__ import annotations

import pandas as pd

# Thresholds match the imperial-unit framing used when this feature was scoped
# (90F / 32F), converted to the Celsius units NOAA's GHCN-Daily reports in.
_HEAT_THRESHOLD_C = 32.2  # 90 degF
_FREEZE_THRESHOLD_C = 0.0  # 32 degF


def add_weather_features(
    df: pd.DataFrame,
    weather: pd.DataFrame,
    *,
    date_col: str = "inspection_date",
) -> pd.DataFrame:
    """Append citywide weather features, joined onto ``df`` by ``date_col``.

    Args:
        df: anchor table with a date column (e.g. ``inspections_labeled``).
        weather: output of ``foodsafety.io.noaa.fetch_noaa_ghcnd`` — one row
            per date with ``tmax_c``, ``tmin_c``, ``precip_mm``, ``snow_mm``.
        date_col: column in ``df`` to join on.

    Features added (every one describes weather STRICTLY BEFORE ``date_col``):
        prior_tmax_3d_avg     float — 3-day rolling mean daily max temp, degC
        prior_tmin_3d_avg     float — 3-day rolling mean daily min temp, degC
        prior_precip_7d_sum   float — 7-day rolling total precipitation, mm
        prior_heat_days_30d   float — count of days TMAX > 90 degF in trailing 30d
        prior_freeze_days_30d float — count of days TMIN < 32 degF in trailing 30d

    Rows whose date falls before the weather series' first available date (or
    in a gap the station didn't report) get NaN — tree models handle NaN
    natively; a LogReg pipeline imputes (see ``build_baseline_pipeline``).
    Returns a new DataFrame; does not mutate either input.
    """
    out = df.copy()
    out[date_col] = pd.to_datetime(out[date_col])

    # Reindex to a continuous daily calendar so the rolling windows count
    # actual elapsed days rather than "however many station readings exist" —
    # a station gap shouldn't silently shrink a 30-day window to 30 readings
    # spanning 40 calendar days.
    w = weather.sort_values("date").set_index("date")
    full_idx = pd.date_range(w.index.min(), w.index.max(), freq="D")
    w = w.reindex(full_idx)
    w.index.name = "date"

    daily = pd.DataFrame(
        {
            "prior_tmax_3d_avg": w["tmax_c"].rolling(3, min_periods=1).mean(),
            "prior_tmin_3d_avg": w["tmin_c"].rolling(3, min_periods=1).mean(),
            "prior_precip_7d_sum": w["precip_mm"].rolling(7, min_periods=1).sum(),
            "prior_heat_days_30d": (w["tmax_c"] > _HEAT_THRESHOLD_C)
            .rolling(30, min_periods=1)
            .sum(),
            "prior_freeze_days_30d": (w["tmin_c"] < _FREEZE_THRESHOLD_C)
            .rolling(30, min_periods=1)
            .sum(),
        }
    )
    # The leak guard: shift every column by one calendar day so date D's row
    # carries weather computed over [D-window, D-1], never D itself.
    daily = daily.shift(1)

    out = out.merge(daily, left_on=date_col, right_index=True, how="left")
    for col in (
        "prior_tmax_3d_avg",
        "prior_tmin_3d_avg",
        "prior_precip_7d_sum",
        "prior_heat_days_30d",
        "prior_freeze_days_30d",
    ):
        out[col] = out[col].astype("float64")

    return out
