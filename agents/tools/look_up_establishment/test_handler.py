"""
Tests for the look_up_establishment tool — deterministic, offline.

Covers the anti-hallucination contract: a name that matches the city data
returns its authoritative record (never the model's memory); a name that
matches nothing returns an explicit no-record result with no invented address
or score; a name shared by several venues returns disambiguation candidates
rather than a guess.

scores.json / inspection_history.json are read from temp files via the
SCORES_JSON_PATH / HISTORY_JSON_PATH env vars, with the lru_caches cleared so
each test sees its own fixture. Nothing here hits the network or AWS.
"""

from __future__ import annotations

import json
import os
import sys

# Allow running from the repo root or from this directory; the handler imports
# the shared matcher (agents/scores_match.py), so agents/ must be importable too.
_THIS_DIR = os.path.dirname(__file__)
_AGENTS_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
for _p in (_THIS_DIR, _AGENTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import handler as h  # noqa: E402
from handler import _clean_names, handler  # noqa: E402


def _wire_data(tmp_path, monkeypatch, scores, history=None):
    """Write fixtures and point the loaders at them, clearing their caches."""
    scores_path = tmp_path / "scores.json"
    history_path = tmp_path / "history.json"
    scores_path.write_text(json.dumps({"scores": scores}), encoding="utf-8")
    history_path.write_text(json.dumps(history or {}), encoding="utf-8")
    monkeypatch.setenv("SCORES_JSON_PATH", str(scores_path))
    monkeypatch.setenv("HISTORY_JSON_PATH", str(history_path))
    h._load_records.cache_clear()
    h._load_history.cache_clear()


# ---------------------------------------------------------------------------
# _clean_names
# ---------------------------------------------------------------------------


def test_clean_names_collects_trims_dedups():
    ev = {"names": ["  Lou Malnati's ", "lou malnati's", ""], "name": "Pequod's"}
    assert _clean_names(ev) == ["Lou Malnati's", "Pequod's"]


def test_clean_names_caps_batch_and_length():
    ev = {"names": [f"Place {i}" for i in range(50)]}
    out = _clean_names(ev)
    assert len(out) == h._MAX_NAMES
    long_name = "x" * 500
    assert len(_clean_names({"name": long_name})[0]) == h._MAX_NAME_CHARS


def test_no_names_returns_empty(tmp_path, monkeypatch):
    _wire_data(tmp_path, monkeypatch, scores=[])
    assert handler({"names": []}, None) == []
    assert handler({}, None) == []


# ---------------------------------------------------------------------------
# Matching branches
# ---------------------------------------------------------------------------


def test_matched_returns_authoritative_record(tmp_path, monkeypatch):
    record = {
        "license_id": "L1",
        "dba_name": "LOU MALNATIS PIZZERIA",
        "address": "805 S State St",
        "neighborhood": "Loop",
        "zip": "60605",
        "facility_type": "Restaurant",
        "lat": 41.8,
        "lon": -87.6,
        "risk_score": 0.12,
        "risk_tier": "Low",
        "percentile_rank": 20.0,
        "trend_slope": -0.5,
        "top_drivers": [{"feature": "prior_fail_rate", "shap": -0.2, "label": "Prior fails"}],
    }
    history = {
        "L1": [{"date": "2024-06-01", "result": "Pass"}, {"date": "2023-01-01", "result": "Fail"}]
    }
    _wire_data(tmp_path, monkeypatch, scores=[record], history=history)

    out = handler({"names": ["Lou Malnati's"]}, None)
    assert len(out) == 1
    r = out[0]
    assert r["status"] == "matched"
    assert r["candidates"] == []
    m = r["match"]
    # Every establishment fact comes from the city record, flagged authoritative.
    assert m["address"] == "805 S State St"
    assert m["address_source"] == "city_inspection_record"
    assert m["dba_name"] == "LOU MALNATIS PIZZERIA"
    assert m["zip"] == "60605"
    assert m["facility_type"] == "Restaurant"
    assert m["risk_tier"] == "Low"
    assert m["trend"] == "improving"
    # Most recent inspection surfaced (newest-first), plus a total count.
    assert m["last_inspection"] == {"date": "2024-06-01", "result": "Pass"}
    assert m["inspection_count"] == 2
    assert m["top_drivers"][0]["direction"] == "negative"


def test_no_match_invents_nothing(tmp_path, monkeypatch):
    _wire_data(
        tmp_path, monkeypatch, scores=[{"license_id": "L1", "dba_name": "AMARIT RESTAURANT"}]
    )
    out = handler({"names": ["Totally Made Up Diner"]}, None)
    assert out[0]["status"] == "no_inspection_record"
    assert out[0]["match"] is None
    assert out[0]["candidates"] == []


def test_ambiguous_returns_candidates_not_a_guess(tmp_path, monkeypatch):
    scores = [
        {
            "license_id": "S1",
            "dba_name": "SUBWAY",
            "address": "1 N Clark St",
            "neighborhood": "Loop",
            "risk_tier": "Low",
        },
        {
            "license_id": "S2",
            "dba_name": "SUBWAY",
            "address": "500 W Madison St",
            "neighborhood": "West Loop",
            "risk_tier": "Moderate",
        },
    ]
    _wire_data(tmp_path, monkeypatch, scores=scores)
    out = handler({"names": ["Subway"]}, None)
    assert out[0]["status"] == "ambiguous"
    assert out[0]["match"] is None
    assert out[0]["truncated"] is False
    got = {c["license_id"] for c in out[0]["candidates"]}
    assert got == {"S1", "S2"}
    # Candidates carry enough to disambiguate by address / neighborhood.
    assert all(c["address"] and c["neighborhood"] for c in out[0]["candidates"])


def test_ambiguous_truncates_and_flags(tmp_path, monkeypatch):
    scores = [
        {"license_id": f"S{i}", "dba_name": "SUBWAY", "address": f"{i} Clark St"}
        for i in range(h._CANDIDATE_LIMIT + 3)
    ]
    _wire_data(tmp_path, monkeypatch, scores=scores)
    out = handler({"names": ["Subway"]}, None)
    assert out[0]["status"] == "ambiguous"
    assert len(out[0]["candidates"]) == h._CANDIDATE_LIMIT
    assert out[0]["truncated"] is True


def test_batch_preserves_order_and_mixes_statuses(tmp_path, monkeypatch):
    scores = [{"license_id": "L1", "dba_name": "PEQUODS PIZZA", "address": "2207 N Clybourn Ave"}]
    _wire_data(tmp_path, monkeypatch, scores=scores)
    out = handler({"names": ["Pequod's", "Nonexistent Place"]}, None)
    assert [r["query"] for r in out] == ["Pequod's", "Nonexistent Place"]
    assert out[0]["status"] == "matched"
    assert out[1]["status"] == "no_inspection_record"
