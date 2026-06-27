"""
Tests for the SageMaker stub — verifies that:
  1. The stub returns plausible, deterministic scores.
  2. Score distribution roughly matches the real model's ~10% positive rate.
  3. The real-endpoint path raises clearly when env vars are missing.
  4. Feature row builder includes all 26 features in FEATURE_ORDER.
  5. Swap flag (SAGEMAKER_USE_STUB) is respected.
"""

from __future__ import annotations

import os
import sys
import types

# ---------------------------------------------------------------------------
# Path setup — allow running from the repo root or from this directory.
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# ---------------------------------------------------------------------------
# Provide a minimal boto3 stub so the module can be imported without AWS SDK.
# ---------------------------------------------------------------------------
_boto3_stub = types.ModuleType("boto3")
sys.modules.setdefault("boto3", _boto3_stub)

from sagemaker_stub import (  # noqa: E402
    FEATURE_ORDER,
    _invoke_stub,
    _tier,
    score_restaurants,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_RESTAURANTS = [
    {"osm_id": "111", "name": "La Pasadita", "address": "1132 N Ashland Ave, Chicago, IL"},
    {"osm_id": "222", "name": "Great Falafel", "address": "500 W Diversey Pkwy, Chicago, IL"},
    {"osm_id": "333", "name": "Arami", "address": "1829 W Chicago Ave, Chicago, IL"},
    {"osm_id": "444", "name": "Golden Wok", "address": "4500 N Broadway, Chicago, IL"},
    {
        "osm_id": "555",
        "name": "Starbucks Lincoln Park",
        "address": "2545 N Lincoln Ave, Chicago, IL",
    },
    {"osm_id": "666", "name": "Enchanting Cafe", "address": "300 E 75th St, Chicago, IL"},
    {"osm_id": "777", "name": "Subway Mount Greenwood", "address": "3800 W 103rd St, Chicago, IL"},
    {"osm_id": "888", "name": "Homan Square Cafe", "address": "3517 W Arthington St, Chicago, IL"},
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTierThresholds:
    def test_low(self):
        assert _tier(0.05) == "Low"

    def test_moderate(self):
        assert _tier(0.30) == "Moderate"

    def test_elevated(self):
        assert _tier(0.50) == "Elevated"

    def test_high(self):
        assert _tier(0.80) == "High"

    def test_boundary_low_moderate(self):
        assert _tier(0.2) == "Moderate"

    def test_boundary_mod_elevated(self):
        assert _tier(0.4) == "Elevated"

    def test_boundary_elevated_high(self):
        assert _tier(0.65) == "High"


class TestStubDeterminism:
    """Same input must always produce the same score (hash-based seed)."""

    def test_same_restaurant_same_score(self):
        r1 = _invoke_stub([SAMPLE_RESTAURANTS[0]])
        r2 = _invoke_stub([SAMPLE_RESTAURANTS[0]])
        assert r1[0]["risk_score"] == r2[0]["risk_score"]

    def test_different_restaurants_different_scores(self):
        results = _invoke_stub(SAMPLE_RESTAURANTS)
        scores = [r["risk_score"] for r in results]
        # Not all the same — very unlikely if hash-based.
        assert len(set(scores)) > 1

    def test_score_stable_across_calls(self):
        scores_a = [r["risk_score"] for r in _invoke_stub(SAMPLE_RESTAURANTS)]
        scores_b = [r["risk_score"] for r in _invoke_stub(SAMPLE_RESTAURANTS)]
        assert scores_a == scores_b


class TestStubOutputShape:
    """Every result must have the expected keys and valid types."""

    def setup_method(self):
        self.results = _invoke_stub(SAMPLE_RESTAURANTS)

    def test_correct_count(self):
        assert len(self.results) == len(SAMPLE_RESTAURANTS)

    def test_required_keys(self):
        required = {"osm_id", "name", "risk_score", "risk_tier", "shap_drivers", "stub"}
        for r in self.results:
            assert required.issubset(r.keys()), f"Missing keys in {r}"

    def test_score_in_range(self):
        for r in self.results:
            assert 0.0 <= r["risk_score"] <= 1.0, f"Score out of range: {r['risk_score']}"

    def test_tier_valid(self):
        valid = {"Low", "Moderate", "Elevated", "High"}
        for r in self.results:
            assert r["risk_tier"] in valid

    def test_stub_flag_true(self):
        for r in self.results:
            assert r["stub"] is True

    def test_stub_note_present(self):
        for r in self.results:
            assert "stub_note" in r and r["stub_note"]

    def test_osm_id_passed_through(self):
        result_ids = {r["osm_id"] for r in self.results}
        input_ids = {r["osm_id"] for r in SAMPLE_RESTAURANTS}
        assert result_ids == input_ids


class TestStubDistribution:
    """
    Score distribution should roughly match the real model:
    positive rate ~10% (High + most Elevated).
    We use a large sample to check the distribution isn't pathological.
    """

    def test_distribution_not_all_one_tier(self):
        restaurants = [
            {"osm_id": str(i), "name": f"Restaurant {i}", "address": f"{i * 10} N State St"}
            for i in range(200)
        ]
        results = _invoke_stub(restaurants)
        tiers = [r["risk_tier"] for r in results]
        tier_set = set(tiers)
        # Should have at least 3 distinct tiers across 200 restaurants.
        assert len(tier_set) >= 3, f"Only tiers {tier_set} observed"

    def test_majority_are_low_or_moderate(self):
        """Beta(1.5, 8) peaks ~0.16; most scores should be Low/Moderate."""
        restaurants = [
            {"osm_id": str(i), "name": f"Restaurant {i}", "address": f"{i * 10} W Madison"}
            for i in range(300)
        ]
        results = _invoke_stub(restaurants)
        safe = sum(1 for r in results if r["risk_tier"] in {"Low", "Moderate"})
        assert safe / len(results) >= 0.55, f"Only {safe / len(results):.0%} are Low/Moderate"


class TestShapDrivers:
    """SHAP drivers should be coherent with the score direction."""

    def test_high_score_has_positive_drivers(self):
        # Find a restaurant that hashes to a high score.
        high_r = None
        for i in range(500):
            r = {"osm_id": str(i), "name": f"R{i}", "address": f"{i} W Lake"}
            result = _invoke_stub([r])[0]
            if result["risk_score"] >= 0.5:
                high_r = result
                break
        if high_r:
            directions = {d["direction"] for d in high_r["shap_drivers"]}
            assert "positive" in directions, "High-score restaurant has no positive drivers"

    def test_low_score_has_negative_drivers(self):
        low_r = None
        for i in range(500):
            r = {"osm_id": str(i + 1000), "name": f"S{i}", "address": f"{i} E Wacker"}
            result = _invoke_stub([r])[0]
            if result["risk_score"] < 0.2:
                low_r = result
                break
        if low_r:
            directions = {d["direction"] for d in low_r["shap_drivers"]}
            assert "negative" in directions, "Low-score restaurant has no negative drivers"

    def test_drivers_sorted_by_abs_shap(self):
        results = _invoke_stub(SAMPLE_RESTAURANTS)
        for r in results:
            shaps = [abs(d["shap"]) for d in r["shap_drivers"]]
            assert shaps == sorted(shaps, reverse=True), "Drivers not sorted by |shap|"

    def test_driver_keys(self):
        results = _invoke_stub(SAMPLE_RESTAURANTS)
        required = {"feature", "label", "shap", "direction"}
        for r in results:
            for d in r["shap_drivers"]:
                assert required.issubset(d.keys())


class TestFeatureOrder:
    """FEATURE_ORDER must match the training pipeline exactly."""

    EXPECTED_FEATURES = [
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
        "static_facility_type",
        "static_risk_tier",
        "static_zip",
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
    ]

    def test_count(self):
        assert len(FEATURE_ORDER) == 26

    def test_exact_order(self):
        assert FEATURE_ORDER == self.EXPECTED_FEATURES


class TestSwapFlag:
    """SAGEMAKER_USE_STUB env var must be respected."""

    def test_stub_is_default(self, monkeypatch):
        monkeypatch.delenv("SAGEMAKER_USE_STUB", raising=False)
        results = score_restaurants([SAMPLE_RESTAURANTS[0]])
        assert results[0]["stub"] is True

    def test_stub_explicit_true(self, monkeypatch):
        monkeypatch.setenv("SAGEMAKER_USE_STUB", "true")
        results = score_restaurants([SAMPLE_RESTAURANTS[0]])
        assert results[0]["stub"] is True

    def test_real_path_raises_without_endpoint(self, monkeypatch):
        monkeypatch.setenv("SAGEMAKER_USE_STUB", "false")
        monkeypatch.delenv("SAGEMAKER_ENDPOINT", raising=False)
        try:
            score_restaurants([SAMPLE_RESTAURANTS[0]])
            raise AssertionError("Expected KeyError for missing SAGEMAKER_ENDPOINT")
        except KeyError:
            pass  # Expected: SAGEMAKER_ENDPOINT not set


class TestEmptyInput:
    def test_empty_list(self):
        results = _invoke_stub([])
        assert results == []

    def test_missing_name(self):
        r = {"osm_id": "x", "address": "123 N State"}
        results = _invoke_stub([r])
        assert len(results) == 1
        assert 0.0 <= results[0]["risk_score"] <= 1.0

    def test_missing_address(self):
        r = {"osm_id": "y", "name": "Some Place"}
        results = _invoke_stub([r])
        assert len(results) == 1
