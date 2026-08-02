"""Tests for the NOAA GHCN-Daily loader (``foodsafety.io.noaa``).

The live HTTP is mocked — ``requests.get`` is patched and ``time.sleep`` is
stubbed — so the parse/pivot/unit-conversion/quality-flag LOGIC is exercised
without touching the network or waiting on real backoff.
"""

from __future__ import annotations

import gzip
from unittest.mock import Mock, patch

import pytest
import requests

from foodsafety.io import noaa


def _gzip_csv(rows: list[str]) -> bytes:
    """Build a fake GHCN-Daily by_station gzipped CSV from raw data lines."""
    return gzip.compress("\n".join(rows).encode("utf-8"))


def _resp(content: bytes) -> Mock:
    r = Mock()
    r.content = content
    r.raise_for_status.return_value = None
    return r


@patch("foodsafety.io.noaa.requests.get")
def test_fetch_noaa_ghcnd_pivots_and_converts_units(mock_get):
    # TMAX/TMIN in tenths of degC, PRCP in tenths of mm, SNOW in mm.
    rows = [
        "USW00094846,20240101,TMAX,50,,,,",
        "USW00094846,20240101,TMIN,-10,,,,",
        "USW00094846,20240101,PRCP,0,,,,",
        "USW00094846,20240101,SNOW,0,,,,",
        "USW00094846,20240102,TMAX,100,,,,",
        "USW00094846,20240102,TMIN,20,,,,",
        "USW00094846,20240102,PRCP,25,,,,",
        "USW00094846,20240102,SNOW,5,,,,",
    ]
    mock_get.return_value = _resp(_gzip_csv(rows))

    out = noaa.fetch_noaa_ghcnd("USW00094846")

    assert list(out.columns) == ["date", "tmax_c", "tmin_c", "precip_mm", "snow_mm"]
    assert len(out) == 2
    day1 = out.iloc[0]
    assert day1["tmax_c"] == pytest.approx(5.0)
    assert day1["tmin_c"] == pytest.approx(-1.0)
    assert day1["precip_mm"] == pytest.approx(0.0)
    day2 = out.iloc[1]
    assert day2["tmax_c"] == pytest.approx(10.0)
    assert day2["precip_mm"] == pytest.approx(2.5)
    assert day2["snow_mm"] == pytest.approx(5.0)


@patch("foodsafety.io.noaa.requests.get")
def test_fetch_noaa_ghcnd_drops_failed_quality_flag(mock_get):
    rows = [
        # Q-FLAG "X" (failed gap check) — should be dropped, leaving NaN for that day.
        "USW00094846,20240101,TMAX,999,,X,,",
        "USW00094846,20240101,TMIN,-10,,,,",
    ]
    mock_get.return_value = _resp(_gzip_csv(rows))

    out = noaa.fetch_noaa_ghcnd("USW00094846")

    assert len(out) == 1
    assert out.iloc[0]["tmax_c"] != out.iloc[0]["tmax_c"]  # NaN: dropped by QC flag
    assert out.iloc[0]["tmin_c"] == pytest.approx(-1.0)


@patch("foodsafety.io.noaa.requests.get")
def test_fetch_noaa_ghcnd_ignores_unused_elements(mock_get):
    rows = [
        "USW00094846,20240101,TMAX,50,,,,",
        "USW00094846,20240101,AWND,30,,,,",  # average wind speed — not pulled
    ]
    mock_get.return_value = _resp(_gzip_csv(rows))

    out = noaa.fetch_noaa_ghcnd("USW00094846")

    assert "awnd" not in [c.lower() for c in out.columns]
    assert out.iloc[0]["tmax_c"] == pytest.approx(5.0)


@patch("foodsafety.io.noaa.time.sleep")
@patch("foodsafety.io.noaa.requests.get")
def test_request_with_retry_retries_transient_errors(mock_get, _sleep):
    mock_get.side_effect = [
        requests.ConnectionError("boom"),
        _resp(_gzip_csv(["USW00094846,20240101,TMAX,50,,,,"])),
    ]
    out = noaa.fetch_noaa_ghcnd("USW00094846", max_retries=3)

    assert mock_get.call_count == 2
    assert len(out) == 1


@patch("foodsafety.io.noaa.requests.get")
def test_request_with_retry_does_not_retry_http_error(mock_get):
    bad_resp = Mock()
    bad_resp.raise_for_status.side_effect = requests.HTTPError("404")
    mock_get.return_value = bad_resp

    with pytest.raises(requests.HTTPError):
        noaa.fetch_noaa_ghcnd("BADSTATION", max_retries=3)

    assert mock_get.call_count == 1
