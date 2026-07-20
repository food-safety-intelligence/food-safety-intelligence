"""
Tests for the scores.json matcher in handler.py.

Covers the address-and-name disambiguation fix:
  1. Two establishments at the same normalised address map to the right
     license each (the shared-address bug — food courts, airports).
  2. A name that matches nothing in the address bucket returns None
     (no confident-wrong match).
  3. Store-number / punctuation normalisation ("Dunkin'" vs "DUNKIN #305").
  4. The index keeps every record at a shared address (no last-writer-wins).
"""

from __future__ import annotations

import json
import os
import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Path setup — allow running from the repo root or from this directory.
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)
# handler imports the shared matcher (agents/scores_match.py), so the agents/
# dir must be importable too — same dir the deployed runtime and run_eval add.
_AGENTS_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
if _AGENTS_DIR not in sys.path:
    sys.path.insert(0, _AGENTS_DIR)

# handler imports sagemaker_stub, which imports boto3. Provide a minimal stub
# so the module imports without the AWS SDK installed.
_boto3_stub = types.ModuleType("boto3")
sys.modules.setdefault("boto3", _boto3_stub)

import handler  # noqa: E402
from handler import (  # noqa: E402
    _fuzzy_lookup,
    _load_scores_index,
    _normalise_name,
    _trend_label,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Two distinct establishments sharing one airport-terminal address.
SHARED_ADDRESS = "11601 W TOUHY AVE"
RECORD_A = {"license_id": "LIC_A", "dba_name": "STARBUCKS #1138", "address": SHARED_ADDRESS}
RECORD_B = {"license_id": "LIC_B", "dba_name": "MCDONALD'S", "address": SHARED_ADDRESS}


def _index(*records: dict) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for r in records:
        # mirror the loader's keying without touching the lru_cache
        from handler import _normalise_address

        index.setdefault(_normalise_address(r["address"]), []).append(r)
    return index


# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------


def test_normalise_name_strips_store_number_and_punctuation():
    assert _normalise_name("Dunkin'") == "DUNKIN"
    assert _normalise_name("DUNKIN #305") == "DUNKIN"
    assert _normalise_name("McDonald's #1234") == "MCDONALDS"
    assert _normalise_name("  Joe & Sons,  Inc. ") == "JOE SONS INC"
    assert _normalise_name("") == ""


# ---------------------------------------------------------------------------
# Shared-address disambiguation (the core bug)
# ---------------------------------------------------------------------------


def test_shared_address_maps_each_name_to_correct_license():
    index = _index(RECORD_A, RECORD_B)

    starbucks = _fuzzy_lookup(SHARED_ADDRESS, "Starbucks", index)
    mcdonalds = _fuzzy_lookup(SHARED_ADDRESS, "McDonalds", index)

    assert starbucks is not None and starbucks["license_id"] == "LIC_A"
    assert mcdonalds is not None and mcdonalds["license_id"] == "LIC_B"


def test_name_not_in_bucket_returns_none():
    index = _index(RECORD_A, RECORD_B)
    # A completely different business at the same address must not borrow a score.
    assert _fuzzy_lookup(SHARED_ADDRESS, "Pizza Palace", index) is None


def test_empty_name_returns_none():
    index = _index(RECORD_A, RECORD_B)
    assert _fuzzy_lookup(SHARED_ADDRESS, "", index) is None


def test_store_number_does_not_block_match():
    index = _index(RECORD_A)
    # OSM "Starbucks" vs city "STARBUCKS #1138" should still match.
    match = _fuzzy_lookup(SHARED_ADDRESS, "Starbucks Coffee", index)
    assert match is not None and match["license_id"] == "LIC_A"


# ---------------------------------------------------------------------------
# Fuzzy address fall-through still works, then disambiguates by name
# ---------------------------------------------------------------------------


def test_fuzzy_address_then_name():
    index = _index(RECORD_A, RECORD_B)
    # A typo that survives normalisation ("TUOHY" vs "TOUHY") is NOT an exact
    # key, so it must fall through to get_close_matches; the shared bucket then
    # holds 2 records, so name disambiguation picks McDonald's.
    match = _fuzzy_lookup("11601 W TUOHY AVE", "McDonald's", index)
    assert match is not None and match["license_id"] == "LIC_B"


# ---------------------------------------------------------------------------
# A single-occupancy address must still clear a name check
# ---------------------------------------------------------------------------


def test_fuzzy_address_to_lone_record_rejects_a_different_business():
    """The live Los Angeles failure: an OSM address fuzzily resolved into a bucket
    holding one unrelated record, and the name gate was skipped for single-occupancy
    buckets — so "Taco Bell" was handed STARBUCKS COFFEE #9746's risk score. A
    confident wrong score is worse than a miss (ethics decision record 0005)."""
    index = _index(RECORD_A)  # lone STARBUCKS record at SHARED_ADDRESS
    assert _fuzzy_lookup("11601 W TUOHY AVE", "Taco Bell", index) is None


def test_exact_address_to_lone_record_rejects_a_different_tenant():
    """Second live failure: the address matched exactly but the record on it was a
    different business ("Cafe Etc." -> "CAFFE HUB"). Sharing no distinctive word is
    enough to rule it out."""
    index = _index({"license_id": "LIC_C", "dba_name": "CAFFE HUB", "address": SHARED_ADDRESS})
    assert _fuzzy_lookup(SHARED_ADDRESS, "Cafe Etc.", index) is None


def test_exact_hit_on_a_street_without_a_house_number_uses_the_strict_gate():
    """New York City publishes 52 addresses with no house number, several of them
    bare street names. "BROADWAY" is thirteen miles long, so an exact hit on it is
    NOT evidence that two venues are the same place — without this, every venue on
    Broadway sharing one word with a deli inherited that deli's published score."""
    index = _index({"license_id": "LIC_D", "dba_name": "MAMA'S TOO!", "address": "BROADWAY"})
    # Shares the distinctive word "MAMA'S", but only the weak gate would accept it.
    assert _fuzzy_lookup("Broadway, New York, NY", "Mama's Pizza", index) is None
    # The genuine venue still resolves, because it clears the full name match.
    assert _fuzzy_lookup("Broadway, New York, NY", "Mama's Too", index) is not None


def test_a_street_less_address_never_fuzzy_matches():
    """An OSM venue with no street tag yields just the city ("Los Angeles, CA" ->
    "LOS ANGELES"), which difflib scores as 0.72-similar to "435 LOS ANGELES ST"
    while naming nothing in common with it. A key with no house number must not be
    fuzzed at all."""
    index = _index(
        {"license_id": "LIC_E", "dba_name": "ANTOJITOS PUEBLA", "address": "435 LOS ANGELES ST"}
    )
    assert _fuzzy_lookup("Los Angeles, CA", "Antojitos", index) is None
    assert _fuzzy_lookup("Chicago, IL", "Sweet Vegan Bakes", index) is None


def test_exact_address_to_lone_record_keeps_an_honest_rewrite():
    """An exact address is strong evidence, so a venue the two sources merely spell
    differently must still match — one shared distinctive word is enough. Gating this
    on a full name match would have thrown away real coverage."""
    index = _index(RECORD_A)
    match = _fuzzy_lookup(SHARED_ADDRESS, "Starbucks Reserve Roastery", index)
    assert match is not None and match["license_id"] == "LIC_A"


# ---------------------------------------------------------------------------
# Index keeps every shared-address record (no last-writer-wins)
# ---------------------------------------------------------------------------


def test_loader_retains_all_shared_address_records(tmp_path, monkeypatch):
    payload = {"scores": [RECORD_A, RECORD_B]}
    p = tmp_path / "scores.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("SCORES_JSON_PATH", str(p))
    _load_scores_index.cache_clear()

    index = _load_scores_index()
    try:
        buckets = list(index.values())
        assert len(buckets) == 1  # one shared address
        assert len(buckets[0]) == 2  # both records retained
    finally:
        _load_scores_index.cache_clear()


# ---------------------------------------------------------------------------
# Name + geographic-proximity fallback (the Thai-search "no record" bug)
# ---------------------------------------------------------------------------

# A small batch run with real-ish Chicago coordinates. CHINA CAFE is the only
# record near 100 W Randolph, used to check that a different nearby business does
# not borrow its score.
_GEO_SCORES = {
    "scores": [
        {
            "license_id": "1801618",
            "dba_name": "AMARIT RESTAURANT",
            "address": "600 S DEARBORN ST",
            "lat": 41.87448,
            "lon": -87.62935,
            "risk_score": 0.0352,
            "risk_tier": "Low",
            "trend_slope": 0.0,
            "neighborhood": "Loop",
            "top_drivers": [],
        },
        {
            "license_id": "555",
            "dba_name": "LOU MALNATIS PIZZERIA",
            "address": "439 N WELLS ST",
            "lat": 41.89030,
            "lon": -87.63410,
            "risk_score": 0.11,
            "risk_tier": "Moderate",
            "trend_slope": 0.0,
            "neighborhood": "River North",
            "top_drivers": [],
        },
        {
            "license_id": "222",
            "dba_name": "CHINA CAFE",
            "address": "100 W RANDOLPH ST",
            "lat": 41.88400,
            "lon": -87.63100,
            "risk_score": 0.20,
            "risk_tier": "Moderate",
            "trend_slope": 0.0,
            "neighborhood": "Loop",
            "top_drivers": [],
            # Closed venue (scores schema 0.6.0, decision 0014).
            "is_out_of_business": True,
            "closed_since": "2020-06-01",
        },
    ]
}


@pytest.fixture
def _geo_scores(tmp_path, monkeypatch):
    """Point the handler at the geo fixture and reset both caches."""
    path = tmp_path / "scores.json"
    path.write_text(json.dumps(_GEO_SCORES), encoding="utf-8")
    monkeypatch.setenv("SCORES_JSON_PATH", str(path))
    handler._load_scores_index.cache_clear()
    handler._load_scores_records.cache_clear()
    yield
    handler._load_scores_index.cache_clear()
    handler._load_scores_records.cache_clear()


def _score_one(osm: dict) -> dict:
    return handler.handler({"restaurants": [osm]}, None)[0]


def test_geo_fallback_recovers_venue_with_no_osm_address(_geo_scores):
    # "Amarit" (OSM) vs "AMARIT RESTAURANT" (city) at the same corner, with the
    # placeholder address OSM usually returns. The address match fails; geo +
    # name must recover the real record. This is the reported Thai-search bug.
    out = _score_one(
        {
            "osm_id": "1",
            "name": "Amarit",
            "address": "Chicago, IL",
            "lat": 41.87450,
            "lon": -87.62930,
            "cuisine": "thai",
        }
    )
    assert out["matched_scores_json"] is True
    assert out["status"] == "scored"
    assert out["license_id"] == "1801618"
    assert out["risk_tier"] == "Low"
    # Guards the field name: the fixture record carries trend_slope (0.0 ->
    # "stable"). Reading the wrong key would silently yield None ->
    # "not enough inspection history" — the exact prod bug from decision 0011's
    # trend_slope_90d -> trend_slope rename half-landing.
    assert out["trend"] == "stable"


def test_trend_label_maps_slope_including_null():
    assert _trend_label(0.0) == "stable"
    assert _trend_label(0.5) == "worsening"
    assert _trend_label(-0.5) == "improving"
    # Null slope = <2 scored inspections under scores schema 0.5.0: reported as
    # "we can't say", not a confident flat trend (see decision 0011).
    assert _trend_label(None) == "not enough inspection history"


def test_closed_venue_flag_passes_through(_geo_scores):
    # A closed record (CHINA CAFE) must surface is_out_of_business + closed_since
    # so the agent can frame its score as historical (decision 0014). An active
    # venue must report the flag as False, not omit it.
    closed = _score_one(
        {"osm_id": "9", "name": "China Cafe", "address": "", "lat": 41.88401, "lon": -87.63099}
    )
    assert closed["matched_scores_json"] is True
    assert closed["is_out_of_business"] is True
    assert closed["closed_since"] == "2020-06-01"

    active = _score_one(
        {"osm_id": "10", "name": "Amarit", "address": "", "lat": 41.87450, "lon": -87.62930}
    )
    assert active["is_out_of_business"] is False
    assert active["closed_since"] is None


def test_no_record_reports_not_closed(_geo_scores):
    # An unmatched venue carries the closure keys too (no record either way).
    out = _score_one(
        {"osm_id": "11", "name": "Nowhere Diner", "address": "", "lat": 41.95, "lon": -87.70}
    )
    assert out["status"] == "no_inspection_record"
    assert out["is_out_of_business"] is False
    assert out["closed_since"] is None


def test_geo_fallback_token_subset_name(_geo_scores):
    # OSM short name is a token-subset of the longer city name ("Lou Malnati's"
    # vs "LOU MALNATIS PIZZERIA"); SequenceMatcher alone scores this too low.
    out = _score_one(
        {"osm_id": "2", "name": "Lou Malnati's", "address": "", "lat": 41.89028, "lon": -87.63412}
    )
    assert out["matched_scores_json"] is True
    assert out["license_id"] == "555"


def test_geo_fallback_rejects_nearby_different_name(_geo_scores):
    # A different establishment ~15 m from CHINA CAFE must NOT inherit its score
    # just because it is close — the name has to agree (ethics DR 0005).
    out = _score_one(
        {"osm_id": "3", "name": "China Grill", "address": "", "lat": 41.88401, "lon": -87.63099}
    )
    assert out["matched_scores_json"] is False
    assert out["status"] == "no_inspection_record"


def test_geo_fallback_respects_proximity(_geo_scores):
    # Same name as a dataset venue but kilometres away -> not the same place.
    out = _score_one(
        {"osm_id": "4", "name": "Amarit", "address": "", "lat": 41.95000, "lon": -87.70000}
    )
    assert out["matched_scores_json"] is False


def test_absent_venue_returns_no_record(_geo_scores):
    out = _score_one(
        {
            "osm_id": "5",
            "name": "Totally Made Up Thai Place",
            "address": "",
            "lat": 41.88000,
            "lon": -87.63000,
        }
    )
    assert out["matched_scores_json"] is False
    assert out["risk_score"] is None


def test_address_path_still_matches(_geo_scores):
    # A clean street address still matches via the original address path.
    out = _score_one(
        {
            "osm_id": "6",
            "name": "Amarit Thai",
            "address": "600 S Dearborn Street",
            "lat": 41.87448,
            "lon": -87.62935,
        }
    )
    assert out["matched_scores_json"] is True
    assert out["license_id"] == "1801618"


@pytest.mark.parametrize(
    ("osm", "dba", "expected"),
    [
        ("Amarit", "AMARIT RESTAURANT", True),
        ("Lou Malnati's", "LOU MALNATIS PIZZERIA", True),
        ("Star of Siam", "STAR OF SIAM INC", True),
        ("China Grill", "CHINA CAFE", False),
        # A name made only of generic words must never match by token-subset.
        ("Restaurant", "AMARIT RESTAURANT", False),
        ("", "AMARIT RESTAURANT", False),
    ],
)
def test_names_match(osm, dba, expected):
    assert handler._names_match(osm, dba) is expected
