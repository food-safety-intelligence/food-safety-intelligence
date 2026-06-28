"""Schema-conformance tests for the REAL generated parquets.

These tests run against `data/processed/inspections_labeled.parquet`,
`data/processed/features.parquet`, and `data/predictions/scores.parquet`
when present. Skip silently if a file is missing, so CI on a fresh clone
that hasn't run the pipeline still passes.

Catches regressions that the mock-fixture test in `test_contracts.py`
can't see — e.g. a feature renamed in `build.py` would still pass the
mock test but break the modeling pipeline.

Authoritative schemas: docs/interface_contracts.md.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSPECTIONS_PATH = REPO_ROOT / "data" / "processed" / "inspections_labeled.parquet"
FEATURES_PATH = REPO_ROOT / "data" / "processed" / "features.parquet"
SCORES_PATH = REPO_ROOT / "data" / "predictions" / "scores.parquet"


def _load_or_skip(path: Path) -> pd.DataFrame:
    if not path.exists():
        pytest.skip(f"{path} not present — run the pipeline to generate.")
    return pd.read_parquet(path)


# ---------------------------------------------------------------------------
# inspections_labeled.parquet
# ---------------------------------------------------------------------------

INSPECTIONS_REQUIRED = {
    "license_id",
    "inspection_date",
    "dba_name",
    "results",
    "violations",
    "is_burnin",
    "y_fail_or_critical_next_180d",
}

# `right_truncated` was added later — flag separately so older parquets still
# pass the required-column test while we surface its absence as a warning.
INSPECTIONS_OPTIONAL_BUT_EXPECTED = {"right_truncated", "is_fail_or_priority"}


@pytest.fixture(scope="module")
def inspections() -> pd.DataFrame:
    return _load_or_skip(INSPECTIONS_PATH)


def test_inspections_required_columns(inspections):
    missing = INSPECTIONS_REQUIRED - set(inspections.columns)
    assert not missing, f"inspections_labeled.parquet missing: {missing}"


def test_inspections_optional_columns_present(inspections):
    """`right_truncated` is needed by the trainer to avoid biased eval."""
    missing = INSPECTIONS_OPTIONAL_BUT_EXPECTED - set(inspections.columns)
    assert not missing, (
        f"inspections_labeled.parquet missing optional-but-expected columns "
        f"({missing}); rebuild the parquet with the current labels.py."
    )


def test_inspections_dtypes(inspections):
    assert pd.api.types.is_datetime64_any_dtype(inspections["inspection_date"])
    assert pd.api.types.is_bool_dtype(inspections["is_burnin"])
    if "right_truncated" in inspections.columns:
        assert pd.api.types.is_bool_dtype(inspections["right_truncated"])


def test_inspections_burnin_labels_are_na(inspections):
    # Per contract: y is NA for burn-in rows (pre-2019).
    burnin = inspections[inspections["is_burnin"]]
    if len(burnin):
        assert burnin["y_fail_or_critical_next_180d"].isna().all(), (
            "burn-in rows must have NA labels (we don't compute labels pre-2019)"
        )


# ---------------------------------------------------------------------------
# features.parquet
# ---------------------------------------------------------------------------

# These mirror the canonical feature contract in
# `src/foodsafety/models/baseline.py::ALL_FEATURES`. They reflect what the
# IMPLEMENTATION ships today — see docs/weekly/ for any drift notes
# against the older docs/interface_contracts.md.
FEATURES_REQUIRED_NUMERIC = {
    "prior_inspections",
    "prior_fails",
    "prior_priority_violations",
    "prior_core_violations",
    "prior_fail_or_priority_events",
    "days_since_last_inspection",
    "days_since_last_fail",
    "temporal_month",
    "temporal_quarter",
    "license_age_days",
    "license_n_history_rows",
}

FEATURES_REQUIRED_CATEGORICAL = {
    "static_facility_type",
    "static_risk_tier",
    "static_zip",
}

FEATURES_REQUIRED_FLAGS = {
    "flag_kw_temperature",
    "flag_kw_cooling",
    "flag_kw_raw_food",
    "flag_kw_cross_contamination",
    "flag_kw_expired",
    "flag_kw_rodent",
    "flag_kw_pest",
    "flag_kw_no_soap",
    "flag_kw_no_paper_towels",
    "flag_kw_handwash_sink",
    "flag_kw_sewage",
    "flag_kw_certified_manager",
}

FEATURES_REQUIRED = (
    FEATURES_REQUIRED_NUMERIC
    | FEATURES_REQUIRED_CATEGORICAL
    | FEATURES_REQUIRED_FLAGS
    | {"license_id", "as_of_date", "y_fail_or_critical_next_180d"}
)


@pytest.fixture(scope="module")
def features() -> pd.DataFrame:
    return _load_or_skip(FEATURES_PATH)


def test_features_required_columns(features):
    missing = FEATURES_REQUIRED - set(features.columns)
    assert not missing, f"features.parquet missing required columns: {missing}"


def test_features_baseline_alignment(features):
    """The trainer expects the canonical 26 features from baseline.py."""
    from foodsafety.models.baseline import ALL_FEATURES

    missing = set(ALL_FEATURES) - set(features.columns)
    assert not missing, (
        f"features.parquet is missing features the baseline trainer needs: {missing}"
    )


def test_features_label_present_for_non_burnin(features):
    if "is_burnin" not in features.columns:
        pytest.skip("features.parquet missing is_burnin")
    modelable = features[~features["is_burnin"]]
    # Allow NA on right-truncated rows when that flag exists — those have
    # under-counted labels by design.
    if "right_truncated" in features.columns:
        modelable = modelable[~modelable["right_truncated"]]
    null_rate = modelable["y_fail_or_critical_next_180d"].isna().mean()
    assert null_rate == 0, (
        f"non-burnin / non-truncated rows should have a label; got {null_rate:.1%} null"
    )


# ---------------------------------------------------------------------------
# scores.parquet (real, not mock)
# ---------------------------------------------------------------------------

SCORES_REQUIRED = {
    "license_id",
    "dba_name",
    "as_of_date",
    "risk_score",
    "risk_tier",
    "top_drivers",
    "trend_slope",
}

VALID_TIERS = {"Low", "Moderate", "Elevated", "High"}


@pytest.fixture(scope="module")
def scores_real() -> pd.DataFrame:
    return _load_or_skip(SCORES_PATH)


def test_scores_real_required_columns(scores_real):
    missing = SCORES_REQUIRED - set(scores_real.columns)
    assert not missing, f"scores.parquet missing required columns: {missing}"


def test_scores_real_no_mock_marker(scores_real):
    """The real artifact must NOT carry `_is_mock` — that's how the web app
    decides whether to render the demo banner."""
    assert "_is_mock" not in scores_real.columns, (
        "scores.parquet has `_is_mock` column — the web app will mistakenly "
        "render the demo banner. Make sure write_scores_json/_parquet doesn't "
        "carry it through from the fixture."
    )


def test_scores_real_in_valid_range(scores_real):
    s = scores_real["risk_score"]
    assert s.notna().all(), "risk_score has NaNs"
    assert (s >= 0).all() and (s <= 1).all(), (
        f"risk_score outside [0,1]: min={s.min()}, max={s.max()}"
    )


def test_scores_real_tier_consistency(scores_real):
    unknown = set(scores_real["risk_tier"].unique()) - VALID_TIERS
    assert not unknown, f"unexpected risk_tier values: {unknown}"


def test_scores_real_top_drivers_well_formed(scores_real):
    required_keys = {"feature", "shap", "label"}
    for drivers in scores_real["top_drivers"].head(20):
        assert len(drivers) > 0, "top_drivers should be non-empty"
        for d in drivers:
            assert isinstance(d, dict), f"driver is not a dict: {type(d)}"
            assert required_keys.issubset(d.keys()), (
                f"driver missing keys: {required_keys - d.keys()}"
            )
