"""Unit tests for the AuditFrame contract helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from foodsafety.audit import frame


def test_tenure_bucket_boundaries_and_unknown():
    df = pd.DataFrame({"license_age_days": [0, 364, 365, 1094, 1095, 5000, np.nan]})
    out = frame.add_tenure_bucket(df)["tenure_bucket"].tolist()
    assert out == [
        "new (<1yr)",
        "new (<1yr)",
        "established (1-3yr)",
        "established (1-3yr)",
        "mature (3yr+)",
        "mature (3yr+)",
        "unknown",
    ]


def test_quantile_bucket_labels_and_nan():
    s = pd.Series([1.0, 2, 3, 4, 5, 6, 7, 8, np.nan])
    q = frame.quantile_bucket(s)
    assert q.cat.categories[0] == "Q1 (lowest)"
    assert q.cat.categories[-1] == "Q4 (highest)"
    assert pd.isna(q.iloc[-1])  # NaN stays NaN, gets no bucket


def _valid_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "city": ["chicago"],
            "license_id": ["1"],
            "as_of_date": pd.to_datetime(["2025-08-01"]),
            "y_true": [1],
            "y_score": [0.4],
            "risk_tier": ["High"],
            "lat": [41.8],
            "lon": [-87.6],
            "facility_type_norm": ["Restaurant"],
            "license_age_days": [500.0],
            "neighborhood": ["Loop"],
            "cuisine": [None],
            "forecast_score": [0.1],
        }
    )


def test_validate_accepts_good_frame():
    frame.validate(_valid_frame())  # no raise


def test_validate_rejects_bad_label():
    df = _valid_frame()
    df["y_true"] = [2]
    with pytest.raises(ValueError, match="y_true"):
        frame.validate(df)


def test_validate_rejects_unknown_tier():
    df = _valid_frame()
    df["risk_tier"] = ["Critical"]
    with pytest.raises(ValueError, match="risk_tier"):
        frame.validate(df)


def test_validate_requires_census_when_asked():
    with pytest.raises(ValueError, match="census"):
        frame.validate(_valid_frame(), require_census=True)
