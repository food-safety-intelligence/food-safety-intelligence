"""Leak-free tests for ``foodsafety.features.weather_features``.

Mirrors the leak-free test style in ``test_features.py``: synthetic data with
a known answer, checking both the rolling-window arithmetic and the "strictly
before the anchor date" leak guard.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from foodsafety.features.weather_features import add_weather_features


def _weather(dates: list[str], tmax_c, tmin_c, precip_mm, snow_mm=None) -> pd.DataFrame:
    n = len(dates)
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "tmax_c": tmax_c,
            "tmin_c": tmin_c,
            "precip_mm": precip_mm,
            "snow_mm": snow_mm if snow_mm is not None else [0.0] * n,
        }
    )


def _anchors(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {"license_id": [f"L{i}" for i in range(len(dates))], "inspection_date": dates}
    )


def test_weather_features_exclude_anchor_day():
    """Weather recorded ON the anchor date must not enter its own feature value
    — the leak guard mirrors the prior_* "strictly before" convention."""
    weather = _weather(
        ["2024-01-01", "2024-01-02"],
        tmax_c=[0.0, 999.0],  # 999 on the anchor day itself — must not leak in
        tmin_c=[-5.0, -5.0],
        precip_mm=[1.0, 1.0],
    )
    anchors = _anchors(["2024-01-02"])
    out = add_weather_features(anchors, weather)
    assert out.loc[0, "prior_tmax_3d_avg"] == 0.0


def test_weather_rolling_window_arithmetic():
    """3-day avg / 7-day sum computed over the days strictly before the anchor."""
    weather = _weather(
        ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"],
        tmax_c=[0.0, 10.0, 20.0, 30.0, 40.0],
        tmin_c=[-5.0, -5.0, -5.0, 5.0, 5.0],
        precip_mm=[1.0, 2.0, 3.0, 4.0, 5.0],
    )
    anchors = _anchors(["2024-01-04"])
    out = add_weather_features(anchors, weather)
    # 3-day window ending 01-03 (strictly before 01-04): tmax [0,10,20] -> mean 10.
    assert out.loc[0, "prior_tmax_3d_avg"] == 10.0
    assert out.loc[0, "prior_tmin_3d_avg"] == -5.0
    # 7-day sum with min_periods=1: only 3 days of history exist (01-01..01-03).
    assert out.loc[0, "prior_precip_7d_sum"] == 6.0


def test_weather_heat_and_freeze_day_counts():
    weather = _weather(
        ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"],
        tmax_c=[35.0, 35.0, 10.0, 10.0],  # two days over the 32.2C heat threshold
        tmin_c=[-2.0, -2.0, 5.0, 5.0],  # two days under the 0C freeze threshold
        precip_mm=[0.0, 0.0, 0.0, 0.0],
    )
    anchors = _anchors(["2024-01-04"])
    out = add_weather_features(anchors, weather)
    # Strictly before 01-04: 01-01, 01-02, 01-03.
    assert out.loc[0, "prior_heat_days_30d"] == 2.0
    assert out.loc[0, "prior_freeze_days_30d"] == 2.0


def test_weather_features_before_station_history_are_na():
    """An anchor date before the weather series even starts gets NaN, not 0 —
    missing data should never look like "zero hot days"."""
    weather = _weather(
        ["2024-06-01", "2024-06-02"],
        tmax_c=[20.0, 20.0],
        tmin_c=[10.0, 10.0],
        precip_mm=[0.0, 0.0],
    )
    anchors = _anchors(["2024-06-01"])  # first day in the station's history
    out = add_weather_features(anchors, weather)
    assert np.isnan(out.loc[0, "prior_tmax_3d_avg"])
    assert np.isnan(out.loc[0, "prior_heat_days_30d"])


def test_weather_features_do_not_mutate_inputs():
    weather = _weather(
        ["2024-01-01", "2024-01-02"], tmax_c=[0.0, 10.0], tmin_c=[-5.0, -5.0], precip_mm=[1.0, 1.0]
    )
    anchors = _anchors(["2024-01-02"])
    weather_before = weather.copy()
    anchors_before = anchors.copy()
    add_weather_features(anchors, weather)
    pd.testing.assert_frame_equal(weather, weather_before)
    pd.testing.assert_frame_equal(anchors, anchors_before)
