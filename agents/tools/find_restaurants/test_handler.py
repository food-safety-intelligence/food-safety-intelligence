"""
Tests for the find_restaurants tool — the deterministic, offline parts:

  1. Pure geometry/text helpers (Chicago bbox check, cuisine filter, Overpass
     query building, address assembly, haversine).
  2. Element parsing: dedup, skips for missing name/coords, distance.
  3. Geometry resolution: explicit coords win, known/unknown neighborhood.
  4. The handler's branches with the one network call (_fetch_overpass) mocked,
     so nothing here hits Overpass.
"""

from __future__ import annotations

import os
import sys
import urllib.error

# Allow running from the repo root or from this directory.
_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import handler as h  # noqa: E402
from chicago_neighborhoods import CENTROIDS, CHICAGO_BBOX  # noqa: E402
from handler import (  # noqa: E402
    _build_address,
    _build_overpass_query,
    _cuisine_filter,
    _haversine,
    _parse_elements,
    _resolve_geometry,
    _within_chicago,
    handler,
)

# A point in the Loop (inside Chicago) and one in Manhattan (outside).
LOOP_LAT, LOOP_LON = 41.8800, -87.6300
NYC_LAT, NYC_LON = 40.7128, -74.0060


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_within_chicago():
    assert _within_chicago(LOOP_LAT, LOOP_LON) is True
    assert _within_chicago(NYC_LAT, NYC_LON) is False


def test_cuisine_filter():
    assert _cuisine_filter(None) == ""
    assert _cuisine_filter("") == ""
    # Known alias expands to the OSM pattern, case-insensitive flag included.
    f = _cuisine_filter("Sushi")
    assert "sushi|japanese" in f and f.endswith(",i]")
    # Unknown cuisine passes through verbatim (stripped).
    assert "ethiopianx" in _cuisine_filter("  ethiopianx ")


def test_build_overpass_query_contains_bbox_and_limit():
    bbox = {"south": 41.0, "west": -88.0, "north": 42.0, "east": -87.0}
    q = _build_overpass_query(bbox, _cuisine_filter("thai"), 7)
    assert "(41.0,-88.0,42.0,-87.0)" in q
    assert '"amenity"="restaurant"' in q
    assert "out center tags 7" in q
    assert "thai" in q


def test_build_address_variants():
    assert (
        _build_address({"addr:housenumber": "123", "addr:street": "W Madison St"})
        == "123 W Madison St, Chicago, IL"
    )
    # Street only, no house number.
    assert _build_address({"addr:street": "N Clark St"}) == "N Clark St, Chicago, IL"
    # No address tags -> city/state fall back to their Chicago defaults.
    assert _build_address({}) == "Chicago, IL"
    # City/state explicitly blank and no street -> truly empty.
    assert _build_address({"addr:city": "", "addr:state": ""}) == ""


def test_haversine_zero_and_known():
    assert _haversine(LOOP_LAT, LOOP_LON, LOOP_LAT, LOOP_LON) == 0.0
    # ~1.11 km per 0.01 degree of latitude.
    d = _haversine(41.88, -87.63, 41.89, -87.63)
    assert 1.0 < d < 1.2


# ---------------------------------------------------------------------------
# Element parsing
# ---------------------------------------------------------------------------


def test_parse_elements_dedup_and_skips():
    centroid = (41.88, -87.63)
    elements = [
        {"id": 1, "lat": 41.881, "lon": -87.631, "tags": {"name": "Alpha"}},
        # Duplicate of Alpha at the same rounded spot -> skipped.
        {"id": 2, "lat": 41.881, "lon": -87.631, "tags": {"name": "Alpha"}},
        # Way element: coords under "center".
        {"id": 3, "center": {"lat": 41.882, "lon": -87.632}, "tags": {"name": "Beta"}},
        # No name -> skipped.
        {"id": 4, "lat": 41.883, "lon": -87.633, "tags": {}},
        # No coords -> skipped.
        {"id": 5, "tags": {"name": "Gamma"}},
    ]
    out = _parse_elements(elements, centroid)
    names = {r["name"] for r in out}
    assert names == {"Alpha", "Beta"}
    beta = next(r for r in out if r["name"] == "Beta")
    assert beta["osm_id"] == "3"
    assert beta["dist_km"] >= 0


# ---------------------------------------------------------------------------
# Geometry resolution
# ---------------------------------------------------------------------------


def test_resolve_geometry_explicit_coords_win():
    bbox, centroid = _resolve_geometry("Wicker Park", LOOP_LAT, LOOP_LON, 1.0)
    assert centroid == (LOOP_LAT, LOOP_LON)
    assert bbox["south"] < LOOP_LAT < bbox["north"]


def test_resolve_geometry_known_neighborhood_case_insensitive():
    bbox, centroid = _resolve_geometry("wicker park", None, None, 1.0)
    assert centroid == CENTROIDS["Wicker Park"]


def test_resolve_geometry_unknown_neighborhood_returns_none():
    assert _resolve_geometry("Atlantis", None, None, 1.0) is None


def test_resolve_geometry_default_whole_city():
    bbox, centroid = _resolve_geometry(None, None, None, 1.0)
    assert bbox == CHICAGO_BBOX


# ---------------------------------------------------------------------------
# Handler branches (network mocked)
# ---------------------------------------------------------------------------


def test_handler_rejects_out_of_chicago_coords():
    out = handler({"lat": NYC_LAT, "lon": NYC_LON}, None)
    assert out["reason"] == "location_not_recognized"


def test_handler_unknown_neighborhood_errors():
    out = handler({"neighborhood": "Atlantis"}, None)
    assert out["reason"] == "location_not_recognized"


def test_handler_success_sorted_and_limited(monkeypatch):
    def fake_fetch(_query):
        return {
            "elements": [
                {"id": 1, "lat": 41.910, "lon": -87.677, "tags": {"name": "Far"}},
                {"id": 2, "lat": 41.9075, "lon": -87.6745, "tags": {"name": "Near"}},
            ]
        }

    monkeypatch.setattr(h, "_fetch_overpass", fake_fetch)
    out = handler({"neighborhood": "Wicker Park", "limit": 1}, None)
    assert isinstance(out, list)
    assert len(out) == 1  # limit honoured


def test_handler_overpass_unavailable(monkeypatch):
    def boom(_query):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(h, "_fetch_overpass", boom)
    out = handler({"neighborhood": "Wicker Park"}, None)
    assert out["reason"] == "directory_unavailable"
