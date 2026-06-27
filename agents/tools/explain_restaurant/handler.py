"""
Lambda handler: explain_restaurant
------------------------------------
Returns the full SHAP driver breakdown and inspection history for a single
restaurant, identified by either license_id (from scores.json) or osm_id.

Data source: scores.json + inspection_history.json (same files the Next.js
app reads — no separate database needed for the agent).
"""

from __future__ import annotations

import functools
import json
import os
from datetime import date
from typing import Any

# ---------------------------------------------------------------------------
# Data loaders (cached for the Lambda process lifetime)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _load_scores() -> dict[str, dict]:
    """Load scores.json indexed by license_id."""
    path = os.environ.get("SCORES_JSON_PATH", "/opt/scores.json")
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        return {r["license_id"]: r for r in payload.get("scores", [])}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


@functools.lru_cache(maxsize=1)
def _load_history() -> dict[str, list[dict]]:
    """Load inspection_history.json indexed by license_id."""
    path = os.environ.get("HISTORY_JSON_PATH", "/opt/inspection_history.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    """
    Lambda entry point.

    Input event schema:
    {
        "license_id": str     # preferred — direct lookup
    }

    Returns:
    {
        "license_id":   str,
        "dba_name":     str,
        "address":      str,
        "neighborhood": str,
        "facility_type": str,
        "risk_score":   float,
        "risk_tier":    str,
        "trend":        str,
        "percentile_rank": float | null,
        "top_drivers":  list[DriverDetail],
        "inspection_summary": {
            "total":       int,
            "pass":        int,
            "fail":        int,
            "pass_w_conditions": int,
            "other":       int,   # Out of Business / No Entry / Not Ready / etc.
            "last_date":   str | null,
            "days_since_last": int | null
        },
        "inspection_history": list[InspectionEvent],  # most recent first, max 10
        "found": bool
    }
    """
    license_id: str | None = event.get("license_id")

    if not license_id:
        return {"found": False, "error": "license_id is required"}

    scores = _load_scores()
    history = _load_history()

    record = scores.get(str(license_id))
    if not record:
        return {
            "found": False,
            "license_id": license_id,
            "error": f"No score record found for license_id={license_id}",
        }

    # Sort newest-first here so the "last inspection" and the displayed history
    # are correct regardless of the upstream JSON's ordering.
    events: list[dict] = _sort_events_desc(history.get(str(license_id), []))

    return {
        "found": True,
        "license_id": record["license_id"],
        "dba_name": record.get("dba_name", ""),
        "address": record.get("address", ""),
        "neighborhood": record.get("neighborhood", ""),
        "facility_type": record.get("facility_type", ""),
        "zip": record.get("zip", ""),
        "lat": record.get("lat"),
        "lon": record.get("lon"),
        # Score
        "risk_score": record.get("risk_score"),
        "risk_tier": record.get("risk_tier"),
        "percentile_rank": record.get("percentile_rank"),
        "trend": _trend_label(record.get("trend_slope_90d")),
        "trend_slope_90d": record.get("trend_slope_90d"),
        # SHAP drivers — full detail
        "top_drivers": _format_drivers(record.get("top_drivers", [])),
        # Inspection summary + history
        "inspection_summary": _summarise(events),
        "inspection_history": events[:10],  # most recent 10
        # Model context
        "model_note": (
            "Risk score is a 180-day forward prediction "
            "(probability of a failed inspection or priority violation), "
            "not a real-time safety verdict."
        ),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _trend_label(slope: float | None) -> str:
    if slope is None:
        return "stable"
    if slope > 0.001:
        return "worsening"
    if slope < -0.001:
        return "improving"
    return "stable"


def _format_drivers(drivers: list[dict]) -> list[dict]:
    """Ensure each driver has direction + magnitude label for the agent."""
    formatted = []
    for d in drivers:
        shap = d.get("shap", 0.0)
        formatted.append(
            {
                "feature": d.get("feature", ""),
                "label": d.get("label", d.get("feature", "").replace("_", " ").title()),
                "detail": d.get("detail", ""),
                "value": d.get("value", ""),
                "shap": round(shap, 4),
                "direction": "positive" if shap >= 0 else "negative",
                "magnitude": "high"
                if abs(shap) > 0.10
                else ("medium" if abs(shap) > 0.05 else "low"),
            }
        )
    return sorted(formatted, key=lambda d: abs(d["shap"]), reverse=True)


def _event_sort_key(ev: dict) -> date:
    """Parse an event's date for sorting; undated/bad events sort oldest."""
    raw = ev.get("date")
    try:
        return date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return date.min


def _sort_events_desc(events: list[dict]) -> list[dict]:
    """Return events newest-first, tolerating missing or malformed dates."""
    return sorted(events, key=_event_sort_key, reverse=True)


def _classify_result(result: str) -> str:
    """Map a Chicago inspection `result` string to a summary bucket.

    The feed is not just Pass / Fail / Pass w/ Conditions: it also carries
    "Out of Business", "No Entry", "Not Ready" and "Business Not Located",
    which are not inspection outcomes. They go to `other` so they are never
    miscounted as passes (the old catch-all `else` inflated the pass count).
    """
    r = result.strip().lower()
    if "fail" in r:
        return "fail"
    if "conditions" in r:  # "Pass w/ Conditions"
        return "pass_w_conditions"
    if r == "pass":
        return "pass"
    return "other"


def _summarise(events: list[dict]) -> dict[str, Any]:
    """Compute aggregate stats over inspection history (expects newest-first)."""
    if not events:
        return {
            "total": 0,
            "pass": 0,
            "fail": 0,
            "pass_w_conditions": 0,
            "other": 0,
            "last_date": None,
            "days_since_last": None,
        }

    counts = {"pass": 0, "fail": 0, "pass_w_conditions": 0, "other": 0}
    for ev in events:
        counts[_classify_result(ev.get("result", ""))] += 1

    last_date: str | None = events[0].get("date")
    days_since: int | None = None
    if last_date:
        try:
            days_since = (date.today() - date.fromisoformat(last_date[:10])).days
        except ValueError:
            pass

    return {
        "total": len(events),
        "pass": counts["pass"],
        "fail": counts["fail"],
        "pass_w_conditions": counts["pass_w_conditions"],
        "other": counts["other"],
        "last_date": last_date,
        "days_since_last": days_since,
    }
