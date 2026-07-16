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


def _fixtures_with_alcohol_tobacco():
    inspections = pd.DataFrame(
        {
            "license_id": ["100", "100", "200"],
            "inspection_date": pd.to_datetime(["2023-01-01", "2023-06-01", "2023-01-01"]),
        }
    )
    historical = pd.DataFrame(
        {
            "license_number": ["100", "100", "200"],
            "date_issued": pd.to_datetime(["2020-01-01", "2023-03-01", "2019-01-01"]),
            "license_description": [
                "Retail Food Establishment",
                "Consumption on Premises - Incidental Activity",
                "Tobacco",
            ],
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


def test_missing_license_description_degrades_to_all_false():
    # A caller passing a minimal historical frame (no license_description) gets
    # False rather than a KeyError — same degrade-gracefully contract as the
    # NaN age / zero count for an unseen license.
    inspections, historical = _fixtures()
    out = add_license_history_features(inspections, historical)
    assert not out["has_alcohol_license"].any()
    assert not out["has_tobacco_license"].any()


def test_alcohol_and_tobacco_flags_respect_leak_guard():
    inspections, historical = _fixtures_with_alcohol_tobacco()
    out = add_license_history_features(inspections, historical)
    by_anchor = out.set_index(["license_id", "inspection_date"])

    # License 100's "Consumption on Premises" row is issued 2023-03-01 — AFTER
    # the 2023-01-01 anchor (must not leak) but BEFORE the 2023-06-01 anchor.
    assert not by_anchor.loc[("100", pd.Timestamp("2023-01-01")), "has_alcohol_license"]
    assert by_anchor.loc[("100", pd.Timestamp("2023-06-01")), "has_alcohol_license"]
    assert not by_anchor.loc[("100", pd.Timestamp("2023-01-01")), "has_tobacco_license"]

    # License 200's Tobacco license (2019-01-01) precedes its 2023-01-01 anchor.
    row_200 = by_anchor.loc[("200", pd.Timestamp("2023-01-01"))]
    assert row_200["has_tobacco_license"]
    assert not row_200["has_alcohol_license"]


def test_liquor_synonyms_all_match_alcohol_marker():
    # Chicago spreads alcohol across several license_description strings —
    # Tavern, Package Goods, and the caterer's/special-event liquor variants —
    # not one code. Each must independently flip the flag.
    inspections = pd.DataFrame(
        {"license_id": ["1", "2", "3"], "inspection_date": pd.to_datetime(["2023-01-01"] * 3)}
    )
    historical = pd.DataFrame(
        {
            "license_number": ["1", "2", "3"],
            "date_issued": pd.to_datetime(["2020-01-01"] * 3),
            "license_description": ["Tavern", "Package Goods", "Caterer's Liquor License"],
        }
    )
    out = add_license_history_features(inspections, historical)
    assert out["has_alcohol_license"].all()
