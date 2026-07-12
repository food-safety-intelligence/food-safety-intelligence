"""
Lambda handler: look_up_establishment
-------------------------------------
Resolve one or more establishment NAMES to their authoritative city inspection
records, straight from the published scores.json (+ inspection_history.json).

This is the general-chat counterpart to the find_restaurants -> get_safety_score
sequence. When the user names a place directly ("what's the address of Lou
Malnati's?", "compare Giordano's and Pequod's"), there is no OpenStreetMap
directory step and no coordinates — just a name. This tool matches the name to
the city's own record so every fact the agent then states (address, ZIP,
facility type, last inspection, risk score) comes from the data, not from the
model's memory. That is the anti-hallucination guarantee: a name we can't match
returns an explicit no-record result, never an invented address or score.

On a scoped detail page the app already supplies the exact license_id, so the
agent should use explain_restaurant there instead — this tool is for when the
establishment's identity is not yet known.

Data source: scores.json + inspection_history.json (the same files get_safety_score
and explain_restaurant read; the model is never called at request time).
"""

from __future__ import annotations

import functools
import json
import os
from datetime import date
from typing import Any

from scores_match import name_search, trend_label

# A name can legitimately match several records — a chain (many "Subway"s) or two
# unrelated venues with the same name. We return up to this many as disambiguation
# candidates rather than silently guess one (ethics decision record 0005: a
# confident wrong answer is worse than asking which one).
_CANDIDATE_LIMIT = 8
# Backstop against an oversized batch or a single absurdly long name.
_MAX_NAMES = 10
_MAX_NAME_CHARS = 120


# ---------------------------------------------------------------------------
# Data loaders (cached for the Lambda process lifetime, per city)
# ---------------------------------------------------------------------------


def _scores_path(city: str) -> str:
    if city == "nyc":
        return os.environ.get("SCORES_JSON_PATH_NYC", "/opt/nyc_scores.json")
    if city == "la":
        return os.environ.get("SCORES_JSON_PATH_LA", "/opt/la_scores.json")
    return os.environ.get("SCORES_JSON_PATH", "/opt/scores.json")


def _history_path(city: str) -> str:
    if city == "nyc":
        return os.environ.get("HISTORY_JSON_PATH_NYC", "/opt/nyc_inspection_history.json")
    if city == "la":
        return os.environ.get("HISTORY_JSON_PATH_LA", "/opt/la_inspection_history.json")
    return os.environ.get("HISTORY_JSON_PATH", "/opt/inspection_history.json")


@functools.lru_cache(maxsize=3)
def _load_records(city: str = "chicago") -> list[dict]:
    """Flat list of every score record for a city, for the name search."""
    try:
        with open(_scores_path(city), encoding="utf-8") as f:
            return json.load(f).get("scores", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


@functools.lru_cache(maxsize=3)
def _load_history(city: str = "chicago") -> dict[str, list[dict]]:
    """Inspection history indexed by license_id for a city."""
    try:
        with open(_history_path(city), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], _ctx: Any) -> list[dict[str, Any]]:
    """
    Lambda entry point.

    Input event schema:
    {
        "names": [str, ...],   # establishment names to resolve (preferred)
        "name":  str,          # single-name convenience (folded into `names`)
        "city":  str           # "chicago" (default) | "nyc" | "la"
    }

    Returns one result per queried name (order preserved):
    [
        {
            "query":  str,          # the name asked about, echoed back
            "status": str,          # "matched" | "ambiguous" | "no_inspection_record"
            "match":  {...} | null, # the authoritative record when exactly one matched
            "candidates": [ ... ],  # brief records to disambiguate when >1 matched
            "truncated": bool       # true if more candidates existed than we returned
        },
        ...
    ]

    The agent uses the shape to decide: `matched` -> state its facts from `match`;
    `ambiguous` -> ask the user which candidate (by address / neighborhood);
    `no_inspection_record` -> say there is no city record and invent nothing.
    """
    city = str(event.get("city", "chicago"))
    names = _clean_names(event)
    if not names:
        return []

    records = _load_records(city)
    history = _load_history(city)

    return [_resolve_one(name, records, history) for name in names]


def _clean_names(event: dict[str, Any]) -> list[str]:
    """Collect, coerce, trim, and cap the requested names.

    Accepts a `names` list and/or a single `name`, drops blanks, length-caps each
    name and the batch, and de-duplicates while preserving order.
    """
    raw: list[Any] = []
    if isinstance(event.get("names"), list):
        raw.extend(event["names"])
    if event.get("name"):
        raw.append(event["name"])

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = str(item).strip()[:_MAX_NAME_CHARS]
        if name and name.lower() not in seen:
            seen.add(name.lower())
            cleaned.append(name)
    return cleaned[:_MAX_NAMES]


def _resolve_one(name: str, records: list[dict], history: dict[str, list[dict]]) -> dict[str, Any]:
    """Resolve a single name to matched / ambiguous / no-record."""
    # Ask for one more than the cap so we can tell "exactly the cap" from "more
    # than the cap" and report truncation honestly.
    hits = name_search(name, records, limit=_CANDIDATE_LIMIT + 1)

    if not hits:
        return {
            "query": name,
            "status": "no_inspection_record",
            "match": None,
            "candidates": [],
            "truncated": False,
        }

    if len(hits) == 1:
        return {
            "query": name,
            "status": "matched",
            "match": _full_record(hits[0], history),
            "candidates": [],
            "truncated": False,
        }

    # More than one plausible match: never guess. Return brief candidates for the
    # agent to disambiguate by address / neighborhood.
    return {
        "query": name,
        "status": "ambiguous",
        "match": None,
        "candidates": [_brief_record(r) for r in hits[:_CANDIDATE_LIMIT]],
        "truncated": len(hits) > _CANDIDATE_LIMIT,
    }


def _brief_record(record: dict[str, Any]) -> dict[str, Any]:
    """The few fields a user needs to pick the right venue from several."""
    return {
        "license_id": record.get("license_id"),
        "dba_name": record.get("dba_name", ""),
        "address": record.get("address", ""),
        "neighborhood": record.get("neighborhood", ""),
        "zip": record.get("zip", ""),
        "risk_tier": record.get("risk_tier"),
    }


def _full_record(record: dict[str, Any], history: dict[str, list[dict]]) -> dict[str, Any]:
    """Authoritative record for a confidently-matched establishment.

    Every field is the city's own data. `address_source` is always the city
    inspection record here (a name match resolves to a real record), so the agent
    may state the address as authoritative — unlike an OpenStreetMap-only address.
    """
    license_id = str(record.get("license_id", ""))
    events = _sort_events_desc(history.get(license_id, []))
    last = events[0] if events else None

    return {
        # Identity — all authoritative city data.
        "license_id": record.get("license_id"),
        "dba_name": record.get("dba_name", ""),
        "address": record.get("address", ""),
        "address_source": "city_inspection_record",
        "neighborhood": record.get("neighborhood", ""),
        "zip": record.get("zip", ""),
        "facility_type": record.get("facility_type", ""),
        "lat": record.get("lat"),
        "lon": record.get("lon"),
        # Risk signal (precomputed batch run).
        "risk_score": record.get("risk_score"),
        "risk_tier": record.get("risk_tier"),
        "percentile_rank": record.get("percentile_rank"),
        "trend": trend_label(record.get("trend_slope")),
        "trend_slope": record.get("trend_slope"),
        "top_drivers": _brief_drivers(record.get("top_drivers", [])),
        # Closure flag (scores schema 0.6.0, decision 0014).
        "is_out_of_business": bool(record.get("is_out_of_business")),
        "closed_since": record.get("closed_since"),
        # Most recent inspection on file, so the agent can say how current the
        # signal is and what the last outcome was (full history: explain_restaurant).
        "last_inspection": {"date": last.get("date"), "result": last.get("result")}
        if last
        else None,
        "inspection_count": len(events),
        "status": "matched",
    }


def _brief_drivers(top_drivers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Top 3 SHAP drivers in the agent's shape (feature/label/value/shap/direction)."""
    drivers: list[dict[str, Any]] = []
    for d in top_drivers[:3]:
        shap = d.get("shap", 0.0)
        drivers.append(
            {
                "feature": d.get("feature", ""),
                "label": d.get("label", ""),
                "detail": d.get("detail", ""),
                "value": d.get("value"),
                "shap": shap,
                "direction": "positive" if shap > 0 else "negative",
            }
        )
    return drivers


def _event_sort_key(ev: dict) -> date:
    """Parse an event's date for sorting; undated / malformed events sort oldest."""
    raw = ev.get("date")
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return date.min


def _sort_events_desc(events: list[dict]) -> list[dict]:
    """Return events newest-first, tolerating missing or malformed dates."""
    return sorted(events, key=_event_sort_key, reverse=True)
