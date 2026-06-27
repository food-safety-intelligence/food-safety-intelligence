"""
Lambda handler: get_safety_score
----------------------------------
Enriches a list of OSM restaurants with Chicago food-safety risk scores.

Score source (in priority order):
  1. SageMaker XGBoost endpoint  — live model inference (real or stub)
  2. Pre-computed scores.json    — fallback when features unavailable

The SageMaker path is always tried first; scores.json is used as an
address-fuzzy-match fallback so that restaurants not in the live feature
pipeline still get a score when one is available from the batch run.

Stub mode
----------
  SAGEMAKER_USE_STUB=true (default)  → sagemaker_stub._invoke_stub()
  SAGEMAKER_USE_STUB=false           → sagemaker_stub._invoke_real()

See sagemaker_stub.py for the full swap procedure.
"""

from __future__ import annotations

import difflib
import functools
import json
import os
import re
from datetime import date
from typing import Any

from sagemaker_stub import score_restaurants

# ---------------------------------------------------------------------------
# Scores.json fallback loader
# ---------------------------------------------------------------------------


# Address must be a close match AND the best name in that address bucket must
# clear its own bar before we attach a score. Name is the disambiguator at
# shared addresses, so it gets the stricter, independently-tuned cutoff.
_ADDRESS_CUTOFF = 0.72
_NAME_CUTOFF = 0.6


@functools.lru_cache(maxsize=1)
def _load_scores_index() -> dict[str, list[dict]]:
    """
    Load scores.json and index it by normalised address for fuzzy matching.
    Returns empty dict if the file is unavailable.

    Each address maps to a LIST of records: many Chicago establishments share
    one street address (food courts, malls, O'Hare/Midway), so collapsing to a
    single record per address would silently drop all but the last and let the
    wrong business's score attach. The name disambiguates within the bucket.
    """
    scores_path = os.environ.get("SCORES_JSON_PATH", "/opt/scores.json")
    index: dict[str, list[dict]] = {}
    try:
        with open(scores_path, encoding="utf-8") as f:
            payload = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    for r in payload.get("scores", []):
        index.setdefault(_normalise_address(r["address"]), []).append(r)
    return index


def _normalise_address(addr: str) -> str:
    """Uppercase, expand common abbreviations, collapse whitespace."""
    addr = addr.upper()
    replacements = {
        "STREET": "ST",
        "AVENUE": "AVE",
        "BOULEVARD": "BLVD",
        "DRIVE": "DR",
        "COURT": "CT",
        "PLACE": "PL",
        "ROAD": "RD",
        "NORTH": "N",
        "SOUTH": "S",
        "EAST": "E",
        "WEST": "W",
    }
    for long, short in replacements.items():
        addr = re.sub(rf"\b{long}\b", short, addr)
    return re.sub(r"\s+", " ", addr).strip()


def _normalise_name(name: str) -> str:
    """Uppercase, drop store numbers, strip punctuation, collapse whitespace.

    OSM `name` and city `dba_name` are formatted very differently
    ("Dunkin'" vs "DUNKIN #305"), so fold both hard before comparing: remove
    "#1234"-style store numbers, turn any run of non-alphanumerics into a
    single space, and trim.
    """
    name = name.upper()
    name = re.sub(r"#\s*\d+", " ", name)  # store / franchise numbers
    name = name.replace("'", "").replace("’", "")  # join contractions ("McDonald's")
    name = re.sub(r"[^A-Z0-9]+", " ", name)  # remaining punctuation -> space
    return re.sub(r"\s+", " ", name).strip()


def _fuzzy_lookup(address: str, name: str, index: dict[str, list[dict]]) -> dict | None:
    """Return the best score record for this (address, name), or None.

    Resolve the address to a bucket of records (exact key, then fuzzy over the
    keys), then pick the record in that bucket whose `dba_name` best matches
    `name`. BOTH the address and the best name must clear their cutoffs.

    A shared address (food court, airport terminal) holds many establishments,
    so address alone can attach the wrong business's score — a consumer-facing
    wrong-signal harm (ethics decision record 0005, principle 1). A missed
    match (None) is safer than a confident wrong one.
    """
    key = _normalise_address(address)
    bucket = index.get(key)
    if bucket is None:
        matches = difflib.get_close_matches(key, index.keys(), n=1, cutoff=_ADDRESS_CUTOFF)
        if not matches:
            return None
        bucket = index[matches[0]]

    target = _normalise_name(name)
    if not target:
        return None

    best: dict | None = None
    best_ratio = 0.0
    for record in bucket:
        ratio = difflib.SequenceMatcher(
            None, target, _normalise_name(record.get("dba_name", ""))
        ).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = record

    return best if best_ratio >= _NAME_CUTOFF else None


# ---------------------------------------------------------------------------
# Feature builder (used when calling SageMaker directly)
# ---------------------------------------------------------------------------


def _build_feature_row(restaurant: dict[str, Any]) -> dict[str, Any]:
    """
    Build a feature row for the SageMaker endpoint.

    In Phase 2a (stub mode) this is a best-effort construction from whatever
    data the agent has available (OSM tags + scores.json record if found).
    When the real feature pipeline runs server-side, this will be replaced by
    a lookup into the pre-computed features.parquet.

    All missing values default to 0 / safe defaults so the model degrades
    gracefully rather than crashing.
    """
    # Pull any pre-computed features from a scores.json match if available.
    fallback = restaurant.get("_scores_record", {}) or {}

    today = date.today()
    last_inspection_date = restaurant.get("last_inspection_date")

    # Days-since features.
    days_since_inspection = 365  # default: assume old if unknown
    if last_inspection_date:
        try:
            delta = (today - date.fromisoformat(last_inspection_date[:10])).days
            days_since_inspection = max(delta, 0)
        except ValueError:
            pass

    return {
        # Passthrough identifiers (not sent to model, used for bookkeeping).
        "osm_id": restaurant.get("osm_id", ""),
        "name": restaurant.get("name", ""),
        "address": restaurant.get("address", ""),
        # Prior-history features — from scores.json fallback or 0.
        "prior_inspections": fallback.get("prior_inspections", 0),
        "prior_fails": fallback.get("prior_fails", 0),
        "prior_priority_violations": fallback.get("prior_priority_violations", 0),
        "prior_core_violations": fallback.get("prior_core_violations", 0),
        "prior_fail_or_priority_events": fallback.get("prior_fail_or_priority_events", 0),
        # Recency features.
        "days_since_last_inspection": days_since_inspection,
        "days_since_last_fail": fallback.get("days_since_last_fail", 730),
        # Calendar features.
        "temporal_month": today.month,
        "temporal_quarter": (today.month - 1) // 3 + 1,
        # License features.
        "license_age_days": fallback.get("license_age_days", 0),
        "license_n_history_rows": fallback.get("license_n_history_rows", 0),
        # Static/categorical (label-encoded integers; 0 = unknown).
        "static_facility_type": fallback.get("static_facility_type", 0),
        "static_risk_tier": fallback.get("static_risk_tier", 0),
        "static_zip": fallback.get("static_zip", 0),
        # Keyword flags — binary (0/1).
        "flag_kw_temperature": fallback.get("flag_kw_temperature", 0),
        "flag_kw_cooling": fallback.get("flag_kw_cooling", 0),
        "flag_kw_raw_food": fallback.get("flag_kw_raw_food", 0),
        "flag_kw_cross_contamination": fallback.get("flag_kw_cross_contamination", 0),
        "flag_kw_expired": fallback.get("flag_kw_expired", 0),
        "flag_kw_rodent": fallback.get("flag_kw_rodent", 0),
        "flag_kw_pest": fallback.get("flag_kw_pest", 0),
        "flag_kw_no_soap": fallback.get("flag_kw_no_soap", 0),
        "flag_kw_no_paper_towels": fallback.get("flag_kw_no_paper_towels", 0),
        "flag_kw_handwash_sink": fallback.get("flag_kw_handwash_sink", 0),
        "flag_kw_sewage": fallback.get("flag_kw_sewage", 0),
        "flag_kw_certified_manager": fallback.get("flag_kw_certified_manager", 0),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], _ctx: Any) -> list[dict[str, Any]]:
    """
    Lambda entry point.

    Input event schema:
    {
        "restaurants": [
            {
                "osm_id":   str,
                "name":     str,
                "address":  str,
                "lat":      float,
                "lon":      float,
                "cuisine":  str    (optional)
            },
            ...
        ]
    }

    Returns list sorted by risk_score ascending (safest first):
    [
        {
            "osm_id":       str,
            "name":         str,
            "address":      str,
            "license_id":   str | null,
            "risk_score":   float,    # calibrated probability 0–1
            "risk_tier":    str,      # "Low" | "Moderate" | "Elevated" | "High"
            "trend":        str,      # "improving" | "stable" | "worsening"
            "percentile_rank": float | null,
            "shap_drivers": list,
            "matched_scores_json": bool,
            "stub":         bool      # true while SageMaker endpoint is a stub
        },
        ...
    ]
    """
    restaurants: list[dict[str, Any]] = event.get("restaurants", [])
    if not restaurants:
        return []

    scores_index = _load_scores_index()

    # Enrich each restaurant with any pre-computed data from scores.json.
    feature_rows: list[dict[str, Any]] = []
    scores_json_matches: dict[str, dict] = {}

    for r in restaurants:
        match = _fuzzy_lookup(r.get("address", ""), r.get("name", ""), scores_index)
        r["_scores_record"] = match  # attach for feature builder; stripped later
        if match:
            scores_json_matches[r["osm_id"]] = match
        feature_rows.append(_build_feature_row(r))

    # Call SageMaker (stub or real) for risk scores + SHAP.
    sm_results: list[dict[str, Any]] = score_restaurants(feature_rows)

    # Merge SageMaker output with scores.json metadata.
    output: list[dict[str, Any]] = []
    for r, sm in zip(restaurants, sm_results, strict=True):
        scores_match = scores_json_matches.get(r["osm_id"])

        output.append(
            {
                # Identity
                "osm_id": r["osm_id"],
                "name": r["name"],
                "address": r.get("address", ""),
                "lat": r.get("lat"),
                "lon": r.get("lon"),
                "cuisine": r.get("cuisine", ""),
                # Score (from SageMaker — stub or real)
                "risk_score": sm["risk_score"],
                "risk_tier": sm["risk_tier"],
                "shap_drivers": sm["shap_drivers"],
                "stub": sm.get("stub", False),
                "stub_note": sm.get("stub_note"),
                # Metadata from scores.json match (if any)
                "license_id": scores_match["license_id"] if scores_match else None,
                "matched_scores_json": scores_match is not None,
                "percentile_rank": scores_match.get("percentile_rank") if scores_match else None,
                "trend": _trend_label(
                    scores_match.get("trend_slope_90d") if scores_match else None
                ),
                "neighborhood": scores_match.get("neighborhood") if scores_match else None,
            }
        )

    # Return safest first.
    return sorted(output, key=lambda r: r["risk_score"])


def _trend_label(slope: float | None) -> str:
    if slope is None:
        return "stable"
    if slope > 0.001:
        return "worsening"
    if slope < -0.001:
        return "improving"
    return "stable"
