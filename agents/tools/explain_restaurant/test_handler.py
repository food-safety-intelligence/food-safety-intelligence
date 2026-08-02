"""
Tests for the explain_restaurant tool — the deterministic, offline parts:

  1. Pure helpers (trend label, driver formatting, result classification,
     date-tolerant sorting, history summary).
  2. The handler's branches, with scores.json / inspection_history.json read
     from temp files via the SCORES_JSON_PATH / HISTORY_JSON_PATH env vars
     (the lru_cache is cleared so each test sees its own fixture).

Nothing here hits the network or AWS.
"""

from __future__ import annotations

import json
import os
import sys

# Allow running from the repo root or from this directory.
_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import handler as h  # noqa: E402
from handler import (  # noqa: E402
    _classify_result,
    _event_sort_key,
    _format_drivers,
    _sort_events_desc,
    _summarise,
    _trend_label,
    handler,
)

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_trend_label():
    # Null slope = <2 scored inspections under scores schema 0.5.0, reported as
    # "we can't say" rather than a confident flat trend (see decision 0011).
    assert _trend_label(None) == "not enough inspection history"
    assert _trend_label(0.0) == "stable"
    assert _trend_label(0.5) == "worsening"
    assert _trend_label(-0.5) == "improving"


def test_format_drivers_sorts_and_labels():
    drivers = [
        {"feature": "a", "shap": 0.02},
        {"feature": "prior_fail_rate", "shap": -0.20},
        {"feature": "b", "shap": 0.07},
    ]
    out = _format_drivers(drivers)
    # Sorted by absolute SHAP, largest first.
    assert [d["feature"] for d in out] == ["prior_fail_rate", "b", "a"]
    biggest = out[0]
    assert biggest["direction"] == "negative"
    assert biggest["magnitude"] == "high"
    # Label falls back to a title-cased feature name.
    assert biggest["label"] == "Prior Fail Rate"
    assert out[2]["magnitude"] == "low"
    assert out[1]["magnitude"] == "medium"


def test_classify_result_buckets():
    assert _classify_result("Fail") == "fail"
    assert _classify_result("Pass w/ Conditions") == "pass_w_conditions"
    assert _classify_result("Pass") == "pass"
    assert _classify_result("Out of Business") == "other"
    # None must not crash (the feed can carry an explicit null).
    assert _classify_result(None) == "other"


def test_event_sort_key_tolerates_bad_dates():
    from datetime import date

    assert _event_sort_key({"date": "2024-05-01"}) == date(2024, 5, 1)
    assert _event_sort_key({"date": None}) == date.min
    assert _event_sort_key({}) == date.min


def test_sort_events_desc():
    events = [
        {"date": "2023-01-01", "result": "Pass"},
        {"date": "2024-06-01", "result": "Fail"},
        {"date": "bad", "result": "Pass"},
    ]
    out = _sort_events_desc(events)
    assert out[0]["date"] == "2024-06-01"  # newest first
    assert out[-1]["date"] == "bad"  # unparseable sorts oldest


def test_summarise_empty():
    s = _summarise([])
    assert s["total"] == 0
    assert s["last_date"] is None
    assert s["days_since_last"] is None


def test_summarise_counts():
    events = [
        {"date": "2024-06-01", "result": "Fail"},
        {"date": "2024-01-01", "result": "Pass"},
        {"date": "2023-06-01", "result": "Pass w/ Conditions"},
        {"date": "2023-01-01", "result": "No Entry"},
    ]
    s = _summarise(events)
    assert s["total"] == 4
    assert s["fail"] == 1
    assert s["pass"] == 1
    assert s["pass_w_conditions"] == 1
    assert s["other"] == 1
    assert s["last_date"] == "2024-06-01"
    assert s["days_since_last"] is not None and s["days_since_last"] > 0


# ---------------------------------------------------------------------------
# Handler branches (data from temp JSON via env vars)
# ---------------------------------------------------------------------------


def _wire_data(tmp_path, monkeypatch, scores, history):
    """Write fixtures and point the loaders at them, clearing their caches."""
    scores_path = tmp_path / "scores.json"
    history_path = tmp_path / "history.json"
    scores_path.write_text(json.dumps({"scores": scores}), encoding="utf-8")
    history_path.write_text(json.dumps(history), encoding="utf-8")
    monkeypatch.setenv("SCORES_JSON_PATH", str(scores_path))
    monkeypatch.setenv("HISTORY_JSON_PATH", str(history_path))
    h._load_scores.cache_clear()
    h._load_history.cache_clear()


def test_handler_requires_license_id():
    out = handler({}, None)
    assert out["found"] is False


def test_handler_unknown_license(tmp_path, monkeypatch):
    _wire_data(tmp_path, monkeypatch, scores=[], history={})
    out = handler({"license_id": "NOPE"}, None)
    assert out["found"] is False
    assert out["license_id"] == "NOPE"


def test_handler_success(tmp_path, monkeypatch):
    record = {
        "license_id": "L1",
        "dba_name": "Joe's Diner",
        "address": "1 Main St",
        "risk_score": 0.7,
        "risk_tier": "elevated",
        "trend_slope": 0.5,
        "top_drivers": [{"feature": "prior_fail_rate", "shap": 0.2}],
    }
    history = {"L1": [{"date": "2024-06-01", "result": "Fail"}]}
    _wire_data(tmp_path, monkeypatch, scores=[record], history=history)

    out = handler({"license_id": "L1"}, None)
    assert out["found"] is True
    assert out["dba_name"] == "Joe's Diner"
    assert out["trend"] == "worsening"
    assert out["inspection_summary"]["fail"] == 1
    assert out["top_drivers"][0]["feature"] == "prior_fail_rate"
    # Active venue: closure keys present and false (decision 0014).
    assert out["is_out_of_business"] is False
    assert out["closed_since"] is None


def test_handler_surfaces_closure(tmp_path, monkeypatch):
    # A closed venue must pass its closure flag + date through so the agent can
    # frame the score as historical (decision 0014).
    record = {
        "license_id": "L2",
        "dba_name": "Gone Grill",
        "risk_score": 0.7,
        "risk_tier": "elevated",
        "trend_slope": 0.5,
        "is_out_of_business": True,
        "closed_since": "2021-03-15",
        "top_drivers": [],
    }
    _wire_data(tmp_path, monkeypatch, scores=[record], history={})

    out = handler({"license_id": "L2"}, None)
    assert out["found"] is True
    assert out["is_out_of_business"] is True
    assert out["closed_since"] == "2021-03-15"
