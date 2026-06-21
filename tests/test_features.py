"""Tests for the feature pipeline.

The crown jewel of this file is the leak-freeness test:
``test_prior_features_do_not_leak_anchor`` constructs a tiny synthetic dataset
where the anchor row's outcome would change the feature value if the leak
guard were broken. The assertion locks down the right answer.

Other tests pin down:
  - cross-license isolation (License A's prior history doesn't bleed into B)
  - days_since_last_inspection / days_since_last_fail semantics
  - keyword-flag regex behaviour on representative violations text
  - the orchestrator's row-filter rules (burn-in / invalid license / non-modelable)
"""

from __future__ import annotations

import pandas as pd
import pytest

from foodsafety.features.build import build_features
from foodsafety.features.inspection_features import add_inspection_features
from foodsafety.features.keyword_flags import add_keyword_flags
from foodsafety.features.license_features import add_license_features


def _minimal_row(**overrides) -> dict:
    """Build one inspection row with sane defaults; overrides win."""
    base = {
        "license_id": "L1",
        "inspection_date": "2019-04-01",
        "results": "Pass",
        "violations": None,
        "facility_type": "Restaurant",
        "risk": "Risk 1 (High)",
        "zip": "60614",
        "latitude": 41.9000,
        "longitude": -87.6500,
        "is_burnin": False,
        "is_fail_or_priority": False,
    }
    base.update(overrides)
    return base


def _df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["inspection_date"] = pd.to_datetime(df["inspection_date"])
    return df


# ---------------------------------------------------------------------------
# Leak-freeness — the most important test in this file
# ---------------------------------------------------------------------------


def test_prior_features_do_not_leak_anchor():
    """The anchor row's own Fail must NOT appear in its own prior_fails.

    Setup: a single license with two inspections — first is Pass, second is
    Fail. If prior_fails is computed correctly:
      - row 1 (Pass): prior_fails == 0
      - row 2 (Fail): prior_fails == 0  (its own Fail must not count!)
    If the guard is broken (e.g. inclusive cumsum without subtraction):
      - row 2 (Fail): prior_fails == 1 (wrong — leaks the anchor)
    """
    df = _df(
        [
            _minimal_row(inspection_date="2019-04-01", results="Pass"),
            _minimal_row(inspection_date="2019-08-01", results="Fail",
                         is_fail_or_priority=True),
        ]
    )
    out = add_inspection_features(df)
    out = out.sort_values("inspection_date").reset_index(drop=True)

    # Critical assertions
    assert out.loc[0, "prior_fails"] == 0
    assert out.loc[1, "prior_fails"] == 0  # the Fail at row 1 must not count for itself
    assert out.loc[1, "prior_inspections"] == 1  # row 0 (Pass) is a prior inspection


def test_prior_features_count_earlier_events_correctly():
    """Three inspections at one license: Fail, Pass, Pass.
    By the third row, prior_fails should be 1 (the first row's Fail).
    """
    df = _df(
        [
            _minimal_row(inspection_date="2019-04-01", results="Fail",
                         is_fail_or_priority=True),
            _minimal_row(inspection_date="2019-08-01", results="Pass"),
            _minimal_row(inspection_date="2019-12-01", results="Pass"),
        ]
    )
    out = add_inspection_features(df).sort_values("inspection_date").reset_index(drop=True)
    assert list(out["prior_inspections"]) == [0, 1, 2]
    assert list(out["prior_fails"]) == [0, 1, 1]


def test_prior_features_do_not_leak_across_licenses():
    """A Fail at License A should NOT count towards License B's prior_fails."""
    df = _df(
        [
            _minimal_row(license_id="A", inspection_date="2019-04-01",
                         results="Fail", is_fail_or_priority=True),
            _minimal_row(license_id="B", inspection_date="2019-08-01",
                         results="Pass"),
        ]
    )
    out = add_inspection_features(df)
    assert out.loc[out["license_id"] == "B", "prior_fails"].iloc[0] == 0


def test_days_since_last_inspection():
    """Days delta between consecutive inspections at the same license.
    First inspection at the license must be NaN."""
    df = _df(
        [
            _minimal_row(inspection_date="2019-01-01"),
            _minimal_row(inspection_date="2019-07-01"),  # 181 days later
        ]
    )
    out = add_inspection_features(df).sort_values("inspection_date").reset_index(drop=True)
    assert pd.isna(out.loc[0, "days_since_last_inspection"])
    assert out.loc[1, "days_since_last_inspection"] == 181


def test_days_since_last_fail_is_strictly_before():
    """days_since_last_fail measures from the MOST RECENT PRIOR Fail.
    On the Fail row itself it must be NaN (no PRIOR Fail).
    On the row after the Fail it should equal the delta from that Fail.
    """
    df = _df(
        [
            _minimal_row(inspection_date="2019-01-01", results="Pass"),
            _minimal_row(inspection_date="2019-04-01", results="Fail",
                         is_fail_or_priority=True),
            _minimal_row(inspection_date="2019-07-01", results="Pass"),  # 91 days after the Fail
        ]
    )
    out = add_inspection_features(df).sort_values("inspection_date").reset_index(drop=True)
    assert pd.isna(out.loc[0, "days_since_last_fail"])  # no prior Fail at all
    assert pd.isna(out.loc[1, "days_since_last_fail"])  # the Fail anchor's OWN Fail isn't a prior
    assert out.loc[2, "days_since_last_fail"] == 91


def test_prior_rates_handle_zero_denominator():
    """First inspection at a license has 0 priors → prior_fail_rate must be NaN, not div-by-zero."""
    df = _df([_minimal_row()])
    out = add_inspection_features(df)
    assert pd.isna(out.loc[0, "prior_fail_rate"])
    assert out.loc[0, "prior_inspections"] == 0


# ---------------------------------------------------------------------------
# Violation-code rollups
# ---------------------------------------------------------------------------


def test_priority_violation_counts_picked_up():
    """A row with code 10 in violations should yield prior_priority_violations
    of 1 at the NEXT inspection (not at the anchor itself)."""
    df = _df(
        [
            _minimal_row(
                inspection_date="2019-04-01",
                results="Pass w/ Conditions",
                violations="10. ADEQUATE HANDWASHING SINKS - Comments: ...",
                is_fail_or_priority=True,
            ),
            _minimal_row(inspection_date="2019-09-01", results="Pass"),
        ]
    )
    out = add_inspection_features(df).sort_values("inspection_date").reset_index(drop=True)
    assert out.loc[0, "prior_priority_violations"] == 0  # the anchor's own code 10 doesn't count
    assert out.loc[1, "prior_priority_violations"] == 1


# ---------------------------------------------------------------------------
# Current-inspection own outcome (the mirror image of the prior_* leak tests:
# these features DO describe the anchor's own visit — that's correct, because
# the 180-day label window is strictly AFTER the anchor, so they don't leak).
# ---------------------------------------------------------------------------


def test_current_inspection_outcome_describes_the_anchor_itself():
    """was_fail / n_priority_this_inspection / n_core_this_inspection summarise
    THIS inspection — the opposite of the prior_* columns, which exclude it."""
    df = _df(
        [
            _minimal_row(
                inspection_date="2019-04-01",
                results="Fail",
                # one priority code (10) and one core code (45)
                violations="10. HANDWASHING - Comments: ... | 45. FLOORS - Comments: ...",
                is_fail_or_priority=True,
            ),
            _minimal_row(inspection_date="2019-09-01", results="Pass"),
        ]
    )
    out = add_inspection_features(df).sort_values("inspection_date").reset_index(drop=True)
    # Anchor row (the Fail) reflects ITS OWN outcome.
    assert out.loc[0, "was_fail"] == 1
    assert out.loc[0, "n_priority_this_inspection"] == 1
    assert out.loc[0, "n_core_this_inspection"] == 1
    # The later Pass reflects its own (clean) outcome — NOT the earlier Fail.
    assert out.loc[1, "was_fail"] == 0
    assert out.loc[1, "n_priority_this_inspection"] == 0
    assert out.loc[1, "n_core_this_inspection"] == 0
    # And the prior_* columns still EXCLUDE the anchor (leak guard intact):
    # the anchor's own Fail is not in its own prior_fails.
    assert out.loc[0, "prior_fails"] == 0
    assert out.loc[1, "prior_fails"] == 1


# ---------------------------------------------------------------------------
# Static features
# ---------------------------------------------------------------------------


def test_static_features_present_and_typed():
    df = _df(
        [
            _minimal_row(facility_type="Bakery", risk="Risk 2 (Medium)",
                         zip="60614"),
        ]
    )
    out = add_license_features(df)
    assert out.loc[0, "static_facility_type"] == "Bakery"
    assert out.loc[0, "static_risk_tier"] == "Risk 2 (Medium)"
    assert out.loc[0, "static_zip"] == "60614"
    assert out.loc[0, "static_zip3"] == "606"
    # Category dtype is what the model code expects.
    assert str(out["static_facility_type"].dtype) == "category"


def test_static_zip_cleans_decimals_and_short_codes():
    df = _df(
        [
            _minimal_row(zip="60614.0"),
            _minimal_row(zip="606"),       # too short
            _minimal_row(zip=None),
        ]
    )
    out = add_license_features(df)
    assert out["static_zip"].tolist() == ["60614", "", ""]


# ---------------------------------------------------------------------------
# Keyword flags
# ---------------------------------------------------------------------------


def test_keyword_flag_temperature_matches_common_phrasings():
    df = pd.DataFrame(
        {
            "violations": [
                "code 02 — cold-holding temperatures above 41 °F",
                "code 02 — improper hot-holding; chicken below 135 °F",
                "code 38 — physical facilities maintained clean",
                None,
            ]
        }
    )
    out = add_keyword_flags(df)
    assert out["flag_kw_temperature"].tolist() == [True, True, False, False]


def test_keyword_flag_rodent_matches_vermin_words():
    df = pd.DataFrame(
        {
            "violations": [
                "evidence of rodent droppings observed",
                "live mice in storage area",
                "general sanitation deficiencies",
                None,
            ]
        }
    )
    out = add_keyword_flags(df)
    assert out["flag_kw_rodent"].tolist() == [True, True, False, False]


# ---------------------------------------------------------------------------
# Orchestrator row filter
# ---------------------------------------------------------------------------


def test_build_features_drops_burnin_invalid_and_non_modelable():
    df = _df(
        [
            _minimal_row(license_id="L1", inspection_date="2018-06-01", is_burnin=True),
            _minimal_row(license_id="0",  inspection_date="2019-06-01"),
            _minimal_row(license_id="L1", inspection_date="2019-07-01",
                         results="Out of Business"),
            _minimal_row(license_id="L1", inspection_date="2019-08-01",
                         results="Pass"),
        ]
    )
    out = build_features(df, complaints=None)
    # Only the last row should survive.
    assert len(out) == 1
    assert out.loc[0, "inspection_date"] == pd.Timestamp("2019-08-01")


def test_build_features_uses_burnin_for_priors_before_dropping():
    """The whole point of burn-in is: include pre-2019 rows in `prior_*`
    calculations, but drop them from the output. Verify the post-2019 row
    sees the pre-2019 inspection in its prior_inspections.
    """
    df = _df(
        [
            _minimal_row(license_id="L1", inspection_date="2018-06-01",
                         results="Fail", is_burnin=True,
                         is_fail_or_priority=True),
            _minimal_row(license_id="L1", inspection_date="2019-08-01",
                         results="Pass"),
        ]
    )
    out = build_features(df, complaints=None)
    assert len(out) == 1
    assert out.loc[0, "prior_inspections"] == 1
    assert out.loc[0, "prior_fails"] == 1


# ---------------------------------------------------------------------------
# Complaint features — minimal smoke test
# ---------------------------------------------------------------------------


def test_complaint_features_count_recent_events_within_radius():
    """Spatial BallTree join: events at the SAME coordinate as the anchor,
    within the time window, must count for the right sr_type only.
    """
    from foodsafety.features.complaint_features import add_complaint_features

    # Anchor at a specific lat/lon; all events also at that lat/lon (so
    # spatial radius is satisfied) — varying only sr_type and date.
    inspections = _df(
        [
            _minimal_row(
                license_id="L1",
                inspection_date="2020-06-01",
                latitude=41.9000,
                longitude=-87.6500,
            )
        ]
    )
    complaints = pd.DataFrame(
        {
            "latitude":   [41.9000, 41.9000, 41.9000, 41.9000],
            "longitude":  [-87.6500, -87.6500, -87.6500, -87.6500],
            "sr_type": [
                "Rodent Baiting/Rat Complaint",  # 30 d prior — should count
                "Rodent Baiting/Rat Complaint",  # 95 d prior — outside 90d window
                "Rodent Baiting/Rat Complaint",  # 30 d prior, but at a FAR coord
                "Sanitation Code Violation",     # 30 d prior — counts for sanitation
            ],
            "created_date": pd.to_datetime(
                ["2020-05-02", "2020-02-26", "2020-05-02", "2020-05-02"]
            ),
        }
    )
    # Third row: move it far away (>1km).
    complaints.loc[2, "latitude"] = 41.9100
    out = add_complaint_features(inspections, complaints)
    assert out.loc[0, "n_311_rodent_300m_90d"] == 1
    assert out.loc[0, "n_311_sanitation_300m_90d"] == 1


def test_complaint_features_exclude_anchor_date():
    """An event filed ON the anchor's inspection day must NOT count.
    Anchor inspections often generate same-day 311 entries; counting them
    would leak the anchor into its own features."""
    from foodsafety.features.complaint_features import add_complaint_features

    inspections = _df(
        [
            _minimal_row(
                license_id="L1",
                inspection_date="2020-06-01",
                latitude=41.9,
                longitude=-87.65,
            )
        ]
    )
    complaints = pd.DataFrame(
        {
            "latitude": [41.9],
            "longitude": [-87.65],
            "sr_type": ["Rodent Baiting/Rat Complaint"],
            "created_date": pd.to_datetime(["2020-06-01"]),  # same day as anchor
        }
    )
    out = add_complaint_features(inspections, complaints)
    assert out.loc[0, "n_311_rodent_300m_90d"] == 0


def test_complaint_features_respects_radius():
    """An event outside the 300m radius must NOT count."""
    from foodsafety.features.complaint_features import add_complaint_features

    inspections = _df(
        [
            _minimal_row(
                license_id="L1",
                inspection_date="2020-06-01",
                latitude=41.9000,
                longitude=-87.6500,
            )
        ]
    )
    # Move the event ~1.5 km away (lat shift of 0.013° ≈ 1.4 km).
    complaints = pd.DataFrame(
        {
            "latitude": [41.913],
            "longitude": [-87.6500],
            "sr_type": ["Rodent Baiting/Rat Complaint"],
            "created_date": pd.to_datetime(["2020-05-02"]),
        }
    )
    out = add_complaint_features(inspections, complaints)
    assert out.loc[0, "n_311_rodent_300m_90d"] == 0
