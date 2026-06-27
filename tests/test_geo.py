"""Tests for the Chicago lat/lon sanity check (foodsafety.utils.geo)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from foodsafety.utils.geo import out_of_chicago_bbox, warn_and_null_out_of_bbox


def test_chicago_point_is_in_bbox():
    # The Loop, downtown Chicago.
    assert not out_of_chicago_bbox([41.88], [-87.63])[0]


def test_out_of_bbox_flagged():
    assert out_of_chicago_bbox([40.71], [-74.00])[0]  # NYC
    assert out_of_chicago_bbox([0.0], [0.0])[0]  # null-island


def test_missing_coords_not_flagged():
    # Missing is "unknown", not "wrong" — handled separately, not flagged here.
    assert not out_of_chicago_bbox([np.nan], [np.nan])[0]


def test_warn_and_null_keeps_rows_and_nulls_bad_coords():
    df = pd.DataFrame(
        {
            "license_id": ["a", "b", "c"],
            "latitude": [41.88, 0.0, np.nan],  # good, null-island, already-null
            "longitude": [-87.63, 0.0, np.nan],
        }
    )
    out = warn_and_null_out_of_bbox(df)
    assert len(out) == 3  # no rows dropped
    assert out.loc[0, "latitude"] == 41.88  # in-bbox preserved
    assert pd.isna(out.loc[1, "latitude"]) and pd.isna(out.loc[1, "longitude"])  # nulled
    assert out.loc[0, "license_id"] == "a"  # other columns untouched
    # input not mutated
    assert df.loc[1, "latitude"] == 0.0


def test_missing_columns_is_noop():
    df = pd.DataFrame({"a": [1]})
    assert warn_and_null_out_of_bbox(df).equals(df)
