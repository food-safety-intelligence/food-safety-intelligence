"""Schema-conformance tests for the cross-team parquet contracts.

For now only `scores.parquet` (via the mock fixture) is tested — the other two
files don't exist yet. As `inspections_labeled.parquet` and `features.parquet`
land, add their conformance tests here against the schemas in
`docs/interface_contracts.md`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "scores_mock.parquet"


# Required columns per docs/interface_contracts.md § 3.
SCORES_REQUIRED_COLS: dict[str, str] = {
    "license_id": "string",
    "dba_name": "string",
    "address": "string",
    "lat": "float",
    "lon": "float",
    "as_of_date": "datetime",
    "risk_score": "float",
    "risk_tier": "string",
    "top_drivers": "list",  # list[struct]
    "trend_slope": "float",
}

VALID_TIERS = {"Low", "Moderate", "Elevated", "High"}


@pytest.fixture(scope="module")
def scores() -> pd.DataFrame:
    if not FIXTURE.exists():
        pytest.skip(f"{FIXTURE} missing — run `python scripts/build_scores_mock.py` to regenerate.")
    return pd.read_parquet(FIXTURE)


def test_scores_has_all_required_columns(scores):
    missing = set(SCORES_REQUIRED_COLS) - set(scores.columns)
    assert not missing, f"scores.parquet missing required columns: {missing}"


def test_scores_dtypes(scores):
    # We're permissive on exact dtype names (string vs object, datetime64 vs Timestamp)
    # and just check semantics.
    assert (
        pd.api.types.is_string_dtype(scores["license_id"]) or scores["license_id"].dtype == object
    )
    assert pd.api.types.is_string_dtype(scores["dba_name"]) or scores["dba_name"].dtype == object
    assert pd.api.types.is_float_dtype(scores["lat"])
    assert pd.api.types.is_float_dtype(scores["lon"])
    assert pd.api.types.is_datetime64_any_dtype(scores["as_of_date"])
    assert pd.api.types.is_float_dtype(scores["risk_score"])
    assert pd.api.types.is_float_dtype(scores["trend_slope"])


def test_scores_in_valid_range(scores):
    # risk_score in [0, 1], OR the sentinel -1.0 for stub rows.
    invalid = scores[
        ~(
            ((scores["risk_score"] >= 0) & (scores["risk_score"] <= 1))
            | (scores["risk_score"] == -1.0)
        )
    ]
    assert invalid.empty, f"{len(invalid)} rows have risk_score outside [0,1] and != -1.0"


def test_risk_tier_uses_documented_values(scores):
    unknown = set(scores["risk_tier"].unique()) - VALID_TIERS
    assert not unknown, f"unexpected risk_tier values: {unknown}"


def test_top_drivers_structure(scores):
    # Each row's top_drivers must be a non-empty iterable of dicts with the
    # four required keys. Note: pyarrow round-trips list[dict] as a numpy
    # object array, not a Python list — so we check iterability + length
    # rather than `isinstance(..., list)`.
    required_keys = {"feature", "value", "shap", "label"}
    for drivers in scores["top_drivers"].head(20):  # spot-check 20 rows
        assert len(drivers) > 0
        for d in drivers:
            assert isinstance(d, dict), f"driver is not a dict: {type(d)}"
            assert required_keys.issubset(d.keys()), (
                f"driver missing keys: {required_keys - d.keys()}"
            )


def test_mock_fixture_marker_present(scores):
    # The mock has an `_is_mock` column the app uses to render the demo-data
    # banner. Production scores.parquet will NOT have this column — that's how
    # the app distinguishes them.
    assert "_is_mock" in scores.columns
    assert scores["_is_mock"].all(), "_is_mock should be True for all rows in the fixture"
