"""
Tests for find_inspection_records — the deterministic, offline URL builder.
No network: it only assembles a Chicago Data Portal query link from ids/filters.
"""

from __future__ import annotations

import os
import sys
import urllib.parse

_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from handler import (  # noqa: E402
    MAX_IDS,
    handler,
)


def _decoded_query(url: str) -> str:
    # The SoQL sits url-encoded between '/explore/query/' and '/page/filter'.
    encoded = url.split("/explore/query/", 1)[1].rsplit("/page/filter", 1)[0]
    return urllib.parse.unquote(encoded)


def test_license_ids_mode():
    out = handler({"license_ids": ["1334073", "2163775"]}, None)
    assert out["mode"] == "license_ids"
    assert out["truncated"] is False
    soql = _decoded_query(out["url"])
    # Full WHERE clause — the keyword must be present or the portal grid errors.
    assert 'WHERE `license_` IN ("1334073", "2163775")' in soql
    assert "ORDER BY `inspection_date` DESC" in soql
    assert out["url"].endswith("/page/filter")


def test_zip_mode():
    out = handler({"zip": "60657"}, None)
    assert out["mode"] == "zip"
    assert "WHERE `zip`='60657'" in _decoded_query(out["url"])


def test_geo_mode():
    out = handler({"lat": 41.9401, "lon": -87.6537, "radius_m": 300}, None)
    assert out["mode"] == "geo"
    # Integer radius reads as `300`, not `300.0`.
    assert "WHERE within_circle(`location`, 41.9401, -87.6537, 300)" in _decoded_query(out["url"])


def test_license_ids_precedence_over_zip():
    out = handler({"license_ids": ["1"], "zip": "60657"}, None)
    assert out["mode"] == "license_ids"


def test_dedupe_and_stringify_ids():
    out = handler({"license_ids": [1334073, "1334073", " 2163775 "]}, None)
    assert 'WHERE `license_` IN ("1334073", "2163775")' in _decoded_query(out["url"])


def test_truncates_long_id_list():
    ids = [str(i) for i in range(MAX_IDS + 10)]
    out = handler({"license_ids": ids}, None)
    assert out["truncated"] is True
    soql = _decoded_query(out["url"])
    # Exactly MAX_IDS ids survive (each double-quoted -> two quote chars).
    assert soql.count('"') == MAX_IDS * 2
    assert '"24"' in soql and '"25"' not in soql
    assert f"first {MAX_IDS} of {len(ids)}" in out["note"]


def test_missing_filter_errors():
    out = handler({}, None)
    assert out["reason"] == "missing_filter"
    assert "url" not in out


def test_geo_rejects_bool_coordinates():
    # bool is an int subclass; it must not be accepted as a coordinate.
    out = handler({"lat": True, "lon": False, "radius_m": 300}, None)
    assert out.get("reason") == "missing_filter"


def test_url_is_percent_encoded():
    out = handler({"zip": "60657"}, None)
    # The path segment carrying the query must not contain raw spaces/newlines.
    between = out["url"].split("/explore/query/", 1)[1]
    assert " " not in between
    assert "\n" not in between
