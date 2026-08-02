"""Tests for the agent tool handlers (``agents/tools/*/handler.py``).

These guard the two handler bugs fixed alongside this file:

  - ``explain_restaurant._summarise`` used a catch-all ``else`` that counted
    non-outcome results (Out of Business / No Entry / Not Ready / Business Not
    Located) as **passes**, and trusted the upstream JSON to be newest-first.
  - ``find_restaurants`` returned a list with a fake ``{"error": ...}`` element
    on an Overpass outage, which crashed ``get_safety_score`` with a KeyError on
    the missing ``osm_id``.

The handlers live outside the importable package and pull in sibling modules
(``chicago_neighborhoods``, ``sagemaker_stub``), so we load each by file path
with its own tool directory on ``sys.path`` — the same approach as
``agents/run_local.py``.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import urllib.error
import urllib.parse

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AGENTS_DIR = os.path.join(_REPO_ROOT, "agents")
_TOOLS_DIR = os.path.join(_AGENTS_DIR, "tools")

# A handler may import a shared module from agents/ (e.g. scores_match), so keep
# the agents dir importable — the same way run_local.py / entrypoint.py do.
if _AGENTS_DIR not in sys.path:
    sys.path.insert(0, _AGENTS_DIR)


def _load_handler(tool_name: str):
    """Load a tool's handler.py by absolute path with its dir on sys.path."""
    tool_dir = os.path.join(_TOOLS_DIR, tool_name)
    if tool_dir not in sys.path:
        sys.path.insert(0, tool_dir)
    path = os.path.join(tool_dir, "handler.py")
    spec = importlib.util.spec_from_file_location(f"_{tool_name}_handler", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


explain = _load_handler("explain_restaurant")
find_restaurants = _load_handler("find_restaurants")
get_safety_score = _load_handler("get_safety_score")
records = _load_handler("find_inspection_records")
info = _load_handler("food_safety_info")


# ---------------------------------------------------------------------------
# Bug 1 — explain_restaurant._summarise
# ---------------------------------------------------------------------------

# The exact result strings present in the real inspection feed.
_REAL_RESULTS = [
    "Pass",
    "Fail",
    "Pass w/ Conditions",
    "Out of Business",
    "No Entry",
    "Not Ready",
    "Business Not Located",
]


def test_summarise_does_not_count_non_outcomes_as_pass():
    """Out of Business / No Entry / Not Ready / Business Not Located -> `other`."""
    events = [{"result": r, "date": "2024-01-01"} for r in _REAL_RESULTS]
    summary = explain._summarise(events)

    assert summary["pass"] == 1  # only the literal "Pass"
    assert summary["fail"] == 1
    assert summary["pass_w_conditions"] == 1
    assert summary["other"] == 4  # the four non-outcome results
    assert summary["total"] == len(_REAL_RESULTS)


def test_summarise_buckets_sum_to_total():
    """No event escapes a bucket; the four buckets always sum to total."""
    events = [{"result": r, "date": "2024-01-01"} for r in _REAL_RESULTS * 3]
    s = explain._summarise(events)
    assert s["pass"] + s["fail"] + s["pass_w_conditions"] + s["other"] == s["total"]


def test_summarise_last_date_is_true_most_recent_when_sorted():
    """After the handler sorts newest-first, last_date is the real maximum."""
    events = [
        {"result": "Pass", "date": "2021-05-01"},
        {"result": "Fail", "date": "2023-09-15"},
        {"result": "Pass", "date": "2022-01-01"},
    ]
    ordered = explain._sort_events_desc(events)
    assert ordered[0]["date"] == "2023-09-15"
    assert explain._summarise(ordered)["last_date"] == "2023-09-15"


def test_sort_events_tolerates_missing_and_bad_dates():
    """Undated / malformed-date events sort last, not crash."""
    events = [
        {"result": "Pass"},  # no date
        {"result": "Fail", "date": "not-a-date"},
        {"result": "Pass", "date": "2023-09-15"},
    ]
    ordered = explain._sort_events_desc(events)
    assert ordered[0]["date"] == "2023-09-15"
    assert len(ordered) == 3


def test_summarise_empty_history_has_other_bucket():
    s = explain._summarise([])
    assert s == {
        "total": 0,
        "pass": 0,
        "fail": 0,
        "pass_w_conditions": 0,
        "other": 0,
        "last_date": None,
        "days_since_last": None,
    }


# ---------------------------------------------------------------------------
# Bug 2 — find_restaurants error shape + get_safety_score robustness
# ---------------------------------------------------------------------------


def test_find_restaurants_returns_error_object_on_outage(monkeypatch):
    """An Overpass outage returns a top-level dict, not a list of fakes."""

    def _boom(_query):
        raise urllib.error.URLError("simulated outage")

    monkeypatch.setattr(find_restaurants, "_fetch_overpass", _boom)
    result = find_restaurants.handler({"neighborhood": "Wicker Park"}, None)

    assert isinstance(result, dict)
    assert "error" in result
    assert "osm_id" not in result


def test_get_safety_score_handles_error_object_without_raising():
    """Feeding the outage error object straight in must not crash."""
    error_obj = {"error": "Overpass API unavailable: simulated outage"}
    assert get_safety_score.handler({"restaurants": error_obj}, None) == []


def test_get_safety_score_skips_malformed_elements():
    """A bad element (no osm_id) is dropped; well-formed ones still score."""
    event = {
        "restaurants": [
            {"error": "some upstream problem"},  # no osm_id
            {"osm_id": "123", "name": "Test Diner", "address": "1 N Main St"},
        ]
    }
    out = get_safety_score.handler(event, None)
    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0]["osm_id"] == "123"


# ---------------------------------------------------------------------------
# Item 3 — find_restaurants location scope (Chicago only)
# ---------------------------------------------------------------------------


def test_unrecognised_neighborhood_returns_location_error(monkeypatch):
    """A neighborhood that isn't a Chicago area returns an error object and does
    NOT silently fall back to a whole-Chicago search."""

    def _must_not_call(_query):
        raise AssertionError("Overpass must not be queried for an unknown area")

    monkeypatch.setattr(find_restaurants, "_fetch_overpass", _must_not_call)
    result = find_restaurants.handler({"neighborhood": "Brooklyn"}, None)

    assert isinstance(result, dict)
    assert result["reason"] == "location_not_recognized"
    assert "osm_id" not in result


# Chicago geometry tables for the now city-parameterised _resolve_geometry
# (bbox_table, centroids, city_bbox, city_centroid) — DR 0016 made it per-city.
_CHI_TABLES = find_restaurants.CITY_GEO["chicago"][:4]


def test_no_location_still_searches_whole_chicago():
    """No neighborhood and no coordinates → a whole-Chicago search, not an error."""
    geom = find_restaurants._resolve_geometry(None, None, None, 1.0, *_CHI_TABLES)
    assert geom is not None  # falls back to Chicago, does not short-circuit


def test_unrecognised_neighborhood_resolves_to_none():
    """An unknown area resolves to None so the handler can report it."""
    assert find_restaurants._resolve_geometry("Atlantis", None, None, 1.0, *_CHI_TABLES) is None


# ---------------------------------------------------------------------------
# Multi-city: each tool must scope to the ACTIVE CITY (no cross-city leakage).
# Deterministic — no data files, no network — so these run in CI.
# ---------------------------------------------------------------------------


def test_records_link_is_city_scoped():
    """Chicago and NYC each build their OWN portal's grid; neither leaks the other."""
    chi = records.handler({"license_ids": ["12345"], "city": "chicago"}, None)
    assert "data.cityofchicago.org" in chi["url"] and "cityofnewyork" not in chi["url"]
    nyc = records.handler({"license_ids": ["30075445"], "city": "nyc"}, None)
    assert "data.cityofnewyork.us" in nyc["url"] and "cityofchicago" not in nyc["url"]


def test_records_use_each_citys_native_columns():
    """The id + zip columns differ per city (Chicago license_/zip, NYC camis/zipcode)."""
    chi = urllib.parse.unquote(records.handler({"zip": "60657", "city": "chicago"}, None)["url"])
    assert "`zip`='60657'" in chi
    nyc_id = urllib.parse.unquote(
        records.handler({"license_ids": ["30075445"], "city": "nyc"}, None)["url"]
    )
    assert "`camis` IN" in nyc_id and "license_" not in nyc_id
    nyc_zip = urllib.parse.unquote(records.handler({"zip": "10002", "city": "nyc"}, None)["url"])
    assert "`zipcode`='10002'" in nyc_zip


def test_records_la_has_no_filtered_grid():
    """LA has no queryable API, so the tool returns the LA County inspections page."""
    la = records.handler({"license_ids": ["1"], "city": "la"}, None)
    assert la["mode"] == "city_page"
    assert "lacounty.gov" in la["url"] and "explore/query" not in la["url"]


def test_food_safety_info_local_source_is_city_scoped():
    """The 'local' topic surfaces only the ACTIVE CITY's health source (allow-listed)."""
    for city, host, other in [
        ("nyc", "nyc.gov", "cityofchicago"),
        ("la", "lacounty.gov", "cityofchicago"),
        ("chicago", "chicago", "nyc.gov"),
    ]:
        out = info.handler({"query": "letter grade", "city": city}, None)
        local = [e for e in out["info"] if e["topic"] == "local"]
        assert local, f"{city}: no local topic surfaced"
        urls = [s["url"] for e in local for s in e["sources"]]
        assert any(host in u for u in urls), f"{city}: expected {host} in {urls}"
        assert not any(other in u for u in urls), f"{city}: leaked {other}"
        assert all(info.is_allowed_url(u) for u in urls)


def test_food_safety_info_national_facts_are_city_independent():
    """A general (non-local) question returns the same national sources for any city."""

    def _urls(city):
        out = info.handler({"query": "salmonella", "city": city}, None)
        return {s["url"] for e in out["info"] for s in e["sources"]}

    assert _urls("chicago") == _urls("nyc") == _urls("la")


def test_get_safety_score_reads_the_active_citys_scores_file(monkeypatch):
    """Score lookups route to the per-city scores.json, not always Chicago's."""
    monkeypatch.setenv("SCORES_JSON_PATH", "/x/chi.json")
    monkeypatch.setenv("SCORES_JSON_PATH_NYC", "/x/nyc.json")
    monkeypatch.setenv("SCORES_JSON_PATH_LA", "/x/la.json")
    assert get_safety_score._scores_path("chicago") == "/x/chi.json"
    assert get_safety_score._scores_path("nyc") == "/x/nyc.json"
    assert get_safety_score._scores_path("la") == "/x/la.json"
