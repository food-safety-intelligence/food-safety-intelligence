"""Tests for label construction.

Critical things this test pins down:
  - The forward window is RIGHT-EXCLUSIVE of the anchor (anchor itself is not
    part of its own forward window). If we ever flip this by accident the
    training loop will silently leak labels into features.
  - The window upper bound is INCLUSIVE: an event exactly 180 days later
    counts.
  - Burn-in rows (pre-2019) get NA labels, not 0.
  - Invalid license tokens (placeholder "0", empty string) get NA labels.
  - Priority violations are detected from the violations text, not from the
    `results` column.
"""

from __future__ import annotations

import pandas as pd

from foodsafety.data.labels import (
    INVALID_LICENSE_TOKENS,
    add_violation_features,
    build_labels,
    extract_violation_codes,
    has_priority_violation,
)

# ---------------------------------------------------------------------------
# Violation-code extraction
# ---------------------------------------------------------------------------


def test_extract_violation_codes_single():
    text = "10. ADEQUATE HANDWASHING SINKS - Comments: ..."
    assert extract_violation_codes(text) == [10]


def test_extract_violation_codes_multiple():
    text = "10. HANDWASHING - Comments: ... | 55. PHYSICAL FACILITIES - Comments: ..."
    assert extract_violation_codes(text) == [10, 55]


def test_extract_violation_codes_missing_returns_empty():
    assert extract_violation_codes(None) == []
    assert extract_violation_codes("") == []
    assert extract_violation_codes(float("nan")) == []


def test_has_priority_violation_recognises_priority_codes():
    # Code 10 is priority (1-29 family)
    assert has_priority_violation("10. HANDWASHING - Comments: ...") is True
    # Code 55 is core (30+ family)
    assert has_priority_violation("55. PHYSICAL FACILITIES - Comments: ...") is False
    # Mixed — priority presence wins
    assert has_priority_violation("10. HANDWASHING - Comments: ... | 55. FACILITIES") is True


def test_boundary_codes_29_and_30():
    """Code 29 is priority; code 30 is core. Pin this boundary down."""
    assert has_priority_violation("29. FOO") is True
    assert has_priority_violation("30. FOO") is False


# ---------------------------------------------------------------------------
# Label construction — the leak-free window
# ---------------------------------------------------------------------------


def _make_df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal inspections-shaped DataFrame for testing."""
    df = pd.DataFrame(rows)
    if "violations" not in df.columns:
        df["violations"] = None
    if "license_" not in df.columns:
        df["license_"] = "L1"
    if "inspection_id" not in df.columns:
        df["inspection_id"] = range(1, len(df) + 1)
    return df


def test_anchor_inspection_is_excluded_from_its_own_window():
    """The Fail on 2019-04-01 is the anchor itself; that should NOT count as
    a future Fail for itself. Label for this row must be 0 unless something
    AFTER it is also a Fail or priority violation.
    """
    df = _make_df(
        [
            {"inspection_date": "2019-04-01", "results": "Fail"},
            {"inspection_date": "2020-01-01", "results": "Pass"},
        ]
    )
    out = build_labels(df, train_start_date="2019-01-01")
    label_2019_04 = out.loc[
        out["inspection_date"] == pd.Timestamp("2019-04-01"),
        "y_fail_or_critical_next_180d",
    ].iloc[0]
    assert label_2019_04 == 0


def test_event_within_window_produces_positive_label():
    """A Fail 90 days after the anchor must be labelled positive."""
    df = _make_df(
        [
            {"inspection_date": "2019-04-01", "results": "Pass"},
            {"inspection_date": "2019-06-30", "results": "Fail"},  # 90 days later
        ]
    )
    out = build_labels(df, train_start_date="2019-01-01")
    label = out.loc[
        out["inspection_date"] == pd.Timestamp("2019-04-01"),
        "y_fail_or_critical_next_180d",
    ].iloc[0]
    assert label == 1


def test_event_at_window_upper_bound_is_inclusive():
    """An event exactly 180 days after the anchor counts."""
    df = _make_df(
        [
            {"inspection_date": "2019-04-01", "results": "Pass"},
            {"inspection_date": "2019-09-28", "results": "Fail"},  # +180 days exactly
        ]
    )
    out = build_labels(df, train_start_date="2019-01-01")
    label = out.loc[
        out["inspection_date"] == pd.Timestamp("2019-04-01"),
        "y_fail_or_critical_next_180d",
    ].iloc[0]
    assert label == 1


def test_event_past_window_does_not_produce_positive_label():
    """A Fail 181 days after the anchor must NOT count."""
    df = _make_df(
        [
            {"inspection_date": "2019-04-01", "results": "Pass"},
            {"inspection_date": "2019-09-29", "results": "Fail"},  # +181 days
        ]
    )
    out = build_labels(df, train_start_date="2019-01-01")
    label = out.loc[
        out["inspection_date"] == pd.Timestamp("2019-04-01"),
        "y_fail_or_critical_next_180d",
    ].iloc[0]
    assert label == 0


def test_priority_violation_in_pass_inspection_counts_as_event():
    """A Pass-with-Conditions inspection with a priority-code violation in
    its text is a positive event for the label even though `results != Fail`.
    """
    df = _make_df(
        [
            {"inspection_date": "2019-04-01", "results": "Pass", "violations": None},
            {
                "inspection_date": "2019-06-30",
                "results": "Pass w/ Conditions",
                "violations": "10. HANDWASHING - Comments: ...",
            },
        ]
    )
    out = build_labels(df, train_start_date="2019-01-01")
    label = out.loc[
        out["inspection_date"] == pd.Timestamp("2019-04-01"),
        "y_fail_or_critical_next_180d",
    ].iloc[0]
    assert label == 1


def test_core_only_violation_does_not_count():
    """A Pass with only core-code (30+) violations is NOT a positive event."""
    df = _make_df(
        [
            {"inspection_date": "2019-04-01", "results": "Pass", "violations": None},
            {
                "inspection_date": "2019-06-30",
                "results": "Pass w/ Conditions",
                "violations": "55. FACILITIES - Comments: ...",
            },
        ]
    )
    out = build_labels(df, train_start_date="2019-01-01")
    label = out.loc[
        out["inspection_date"] == pd.Timestamp("2019-04-01"),
        "y_fail_or_critical_next_180d",
    ].iloc[0]
    assert label == 0


# ---------------------------------------------------------------------------
# Burn-in and invalid-license handling
# ---------------------------------------------------------------------------


def test_burnin_rows_get_na_label():
    """Inspections before train_start_date are kept (for prior-* features
    later) but their label is NA, not 0."""
    df = _make_df(
        [
            {"inspection_date": "2018-06-01", "results": "Pass"},  # burn-in
            {"inspection_date": "2019-06-01", "results": "Pass"},  # post-cutoff
        ]
    )
    out = build_labels(df, train_start_date="2019-01-01")
    assert out.loc[out["inspection_date"] == pd.Timestamp("2018-06-01"), "is_burnin"].iloc[0]
    assert pd.isna(
        out.loc[
            out["inspection_date"] == pd.Timestamp("2018-06-01"),
            "y_fail_or_critical_next_180d",
        ].iloc[0]
    )


def test_invalid_license_tokens_get_na_label():
    """Placeholder license values ("0", "") pool unrelated establishments —
    the per-license label would be meaningless, so it's NA."""
    df = _make_df(
        [
            {"inspection_date": "2019-04-01", "results": "Pass", "license_": "0"},
            {"inspection_date": "2019-06-30", "results": "Fail", "license_": "0"},
            {"inspection_date": "2019-04-01", "results": "Pass", "license_": "L42"},
            {"inspection_date": "2019-06-30", "results": "Fail", "license_": "L42"},
        ]
    )
    out = build_labels(df, train_start_date="2019-01-01")
    # Placeholder license rows: label NA
    placeholder_labels = out.loc[out["license_id"] == "0", "y_fail_or_critical_next_180d"]
    assert placeholder_labels.isna().all()
    # Valid license rows: label computed normally
    valid_labels = out.loc[out["license_id"] == "L42", "y_fail_or_critical_next_180d"]
    assert not valid_labels.isna().any()


def test_invalid_license_tokens_constant():
    """The placeholder set should at least contain "0" and "" — those are
    the values present in the actual Chicago data."""
    assert "0" in INVALID_LICENSE_TOKENS
    assert "" in INVALID_LICENSE_TOKENS


# ---------------------------------------------------------------------------
# Cross-license isolation
# ---------------------------------------------------------------------------


def test_labels_do_not_leak_across_licenses():
    """A Fail at License B should NOT contribute to a positive label at
    License A even if the dates fall within the window."""
    df = _make_df(
        [
            {"inspection_date": "2019-04-01", "results": "Pass", "license_": "A"},
            {"inspection_date": "2019-06-30", "results": "Fail", "license_": "B"},
        ]
    )
    out = build_labels(df, train_start_date="2019-01-01")
    label_A = out.loc[
        (out["license_id"] == "A") & (out["inspection_date"] == pd.Timestamp("2019-04-01")),
        "y_fail_or_critical_next_180d",
    ].iloc[0]
    assert label_A == 0


# ---------------------------------------------------------------------------
# add_violation_features
# ---------------------------------------------------------------------------


def test_add_violation_features_columns_present():
    df = pd.DataFrame({"violations": ["10. HANDWASHING | 30. FOO | 55. BAR", None, "29. PRIORITY"]})
    out = add_violation_features(df)
    assert list(out["n_violations"]) == [3, 0, 1]
    assert list(out["has_priority_violation"]) == [True, False, True]
    assert list(out["n_priority_violations"]) == [1, 0, 1]
    assert list(out["n_core_violations"]) == [2, 0, 0]
