"""Tests for license-history features (``foodsafety.features.license_history_features``).

The thing that must not break here is the **leak guard**: license records issued
on or after the anchor's inspection date can't be visible to the model at
inspection time, so ``license_n_history_rows`` counts issuances strictly BEFORE
``inspection_date``. The same anchor at a later date sees more history. A license
absent from the historical table degrades to age=NaN / count=0, not a crash.
"""

from __future__ import annotations

import pandas as pd

from foodsafety.features.license_history_features import add_license_history_features


def _fixtures():
    inspections = pd.DataFrame(
        {
            "license_id": ["100", "100", "200"],
            "inspection_date": pd.to_datetime(["2023-01-01", "2023-06-01", "2023-01-01"]),
        }
    )
    historical = pd.DataFrame(
        {
            "license_number": ["100", "100", "100"],
            "date_issued": pd.to_datetime(["2020-01-01", "2022-01-01", "2023-03-01"]),
        }
    )
    return inspections, historical


def test_history_count_respects_leak_guard():
    inspections, historical = _fixtures()
    out = add_license_history_features(inspections, historical)

    by_anchor = out.set_index(["license_id", "inspection_date"])

    # Anchor 2023-01-01: only the 2020 + 2022 issuances precede it. The
    # 2023-03-01 issuance is AFTER the inspection and must NOT be counted.
    assert by_anchor.loc[("100", pd.Timestamp("2023-01-01")), "license_n_history_rows"] == 2

    # Same license, later anchor (2023-06-01): now all three precede it.
    assert by_anchor.loc[("100", pd.Timestamp("2023-06-01")), "license_n_history_rows"] == 3


def test_license_age_is_days_since_first_issuance():
    inspections, historical = _fixtures()
    out = add_license_history_features(inspections, historical)
    by_anchor = out.set_index(["license_id", "inspection_date"])

    # 2020-01-01 -> 2023-01-01 is 1096 days (2020 is a leap year).
    age = by_anchor.loc[("100", pd.Timestamp("2023-01-01")), "license_age_days"]
    assert age == 1096


def test_unknown_license_gets_null_age_and_zero_count():
    inspections, historical = _fixtures()
    out = add_license_history_features(inspections, historical)
    by_anchor = out.set_index(["license_id", "inspection_date"])

    row = by_anchor.loc[("200", pd.Timestamp("2023-01-01"))]
    assert pd.isna(row["license_age_days"])
    assert row["license_n_history_rows"] == 0


def test_no_helper_columns_leak_into_output():
    inspections, historical = _fixtures()
    out = add_license_history_features(inspections, historical)
    # The internal join scratch columns must be dropped.
    assert not any(c.startswith("_") for c in out.columns)
    assert {"license_age_days", "license_n_history_rows"} <= set(out.columns)
