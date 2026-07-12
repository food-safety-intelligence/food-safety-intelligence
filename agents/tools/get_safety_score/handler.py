"""
Lambda handler: get_safety_score
----------------------------------
Enriches a list of OSM restaurants with Chicago food-safety risk scores.

Score source:
  Pre-computed scores.json — the published batch run is the single source of a
  calibrated score. A venue that matches by address and name returns that score,
  tier and drivers straight from scores.json; the model is never called at
  request time. This is the project's permanent batch-score-to-JSON design — the
  batch run is the source of truth for every venue it covers.

  A venue NOT covered by the batch run has no Chicago inspection record we can
  speak to. It returns an explicit no-record result (null score), not a
  request-time estimate: with no inspection history the only available features
  are all zero, so a model score would be a near-constant value with no
  per-venue meaning — and request-time model scoring is outside the
  batch-score-to-JSON design. The agent reports "no inspection record found"
  for these venues rather than inventing a number.
"""

from __future__ import annotations

import functools
import json
import os
from typing import Any

# The name/address normalisation and fuzzy-match rules live in scores_match so
# this handler (batch, OSM-driven) and look_up_establishment (name lookup)
# resolve a venue identically. This handler keeps only its own cached loader and
# the OSM-stub -> response glue below. Aliased to the leading-underscore names
# the rest of the module (and the tests) already use.
from scores_match import fuzzy_lookup as _fuzzy_lookup
from scores_match import geo_lookup as _geo_lookup
from scores_match import names_match as _names_match  # noqa: F401 — re-exported for tests
from scores_match import normalise_address as _normalise_address
from scores_match import normalise_name as _normalise_name  # noqa: F401 — re-exported for tests
from scores_match import trend_label as _trend_label

# ---------------------------------------------------------------------------
# Scores.json loader
# ---------------------------------------------------------------------------


# Per-city scores.json path (multi-city, DR 0016). The entrypoint warms each
# city's file to a separate /tmp path; default to Chicago.
def _scores_path(city: str) -> str:
    if city == "nyc":
        return os.environ.get("SCORES_JSON_PATH_NYC", "/opt/nyc_scores.json")
    if city == "la":
        return os.environ.get("SCORES_JSON_PATH_LA", "/opt/la_scores.json")
    return os.environ.get("SCORES_JSON_PATH", "/opt/scores.json")


@functools.lru_cache(maxsize=3)
def _load_scores_index(city: str = "chicago") -> dict[str, list[dict]]:
    """
    Load a city's scores.json and index it by normalised address for fuzzy
    matching. Returns empty dict if the file is unavailable.

    Each address maps to a LIST of records: many establishments share one street
    address (food courts, malls, airports), so collapsing to a single record per
    address would silently drop all but the last and let the wrong business's
    score attach. The name disambiguates within the bucket.
    """
    scores_path = _scores_path(city)
    index: dict[str, list[dict]] = {}
    try:
        with open(scores_path, encoding="utf-8") as f:
            payload = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    for r in payload.get("scores", []):
        index.setdefault(_normalise_address(r["address"]), []).append(r)
    return index


@functools.lru_cache(maxsize=3)
def _load_scores_records(city: str = "chicago") -> list[dict]:
    """Flat list of every score record, for the name + proximity fallback.

    Derived from the cached address index so scores.json is read only once.
    """
    return [r for bucket in _load_scores_index(city).values() for r in bucket]


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

    Returns list ordered by predicted risk ascending (lowest first); venues with
    no inspection record sort last:
    [
        {
            "osm_id":       str,
            "name":         str,           # OSM display name (friendlier casing)
            "dba_name":     str,           # official city-registered name ("" if no record)
            "address":      str,           # authoritative city address on a match, else OSM's
            "address_source": str,         # "city_inspection_record" | "openstreetmap"
            "zip":          str,           # city record ZIP ("" if no record)
            "facility_type": str,          # city record facility type ("" if no record)
            "license_id":   str | null,
            "risk_score":   float | null,  # calibrated probability 0–1, or null
            "risk_tier":    str | null,    # "Low" | "Moderate" | "Elevated" | "High"
            "trend":        str | null,    # "improving" | "stable" | "worsening"
                                           #   | "not enough inspection history"
            "percentile_rank": float | null,
            "shap_drivers": list,
            "matched_scores_json": bool,
            "is_out_of_business": bool,    # latest inspection event was a closure
            "closed_since": str | null,    # ISO date of that closure, if known
            "status":       str            # "scored" | "no_inspection_record"
        },
        ...
    ]
    """
    city: str = str(event.get("city", "chicago"))
    restaurants: Any = event.get("restaurants", [])
    # A non-list input (e.g. an upstream {"error": ...} from find_restaurants
    # when Overpass is down) means there is nothing to score — degrade
    # gracefully instead of crashing.
    if not isinstance(restaurants, list):
        return []
    # Drop any malformed element (no osm_id) so one bad input can never crash
    # the batch on a missing key downstream.
    restaurants = [r for r in restaurants if isinstance(r, dict) and r.get("osm_id")]
    if not restaurants:
        return []

    scores_index = _load_scores_index(city)
    scores_records = _load_scores_records(city)

    # A venue matched in scores.json returns its published batch score directly;
    # an unmatched venue has no record on file and returns no number. The model
    # is never called at request time (batch-score-to-JSON design). Match on both
    # address and name so a shared address can't attach the wrong score.
    output: list[dict[str, Any]] = []
    for r in restaurants:
        match = _fuzzy_lookup(r.get("address", ""), r.get("name", ""), scores_index)
        if match is None:
            # Address path failed — OSM often has no usable street address, which
            # wrongly reports a covered venue as "no record". Fall back to name +
            # geographic proximity to recover it.
            match = _geo_lookup(r.get("name", ""), r.get("lat"), r.get("lon"), scores_records)
        if match is not None:
            output.append(_output_from_scores(r, match))
        else:
            output.append(_output_no_record(r))

    # Lowest predicted risk first; venues with no real score sort last. A null
    # score (no record) and the -1.0 mock-data sentinel both lack a meaningful
    # ranking, so treat both as unknown — otherwise -1.0 < 0 would rank a
    # placeholder record as the #1 safest pick.
    def _rank_key(x: dict[str, Any]) -> tuple[bool, float]:
        score = x["risk_score"]
        unknown = score is None or score == -1.0
        return (unknown, 0.0 if unknown else score)

    return sorted(output, key=_rank_key)


def _output_from_scores(restaurant: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    """Build the response for a venue matched in the precomputed scores.json.

    Uses the published batch score/tier/drivers directly — no model call.
    """
    # A matched record missing its score or tier is malformed; fall through to
    # the no-record path rather than emit a partial result, consistent with the
    # defensive no-record handling for unmatched venues.
    score = record.get("risk_score")
    tier = record.get("risk_tier")
    if score is None or tier is None:
        return _output_no_record(restaurant)
    # Once a venue is matched to a city inspection record, that record — not the
    # OpenStreetMap stub — is the source of truth for the establishment's own
    # facts. OSM addresses are frequently blank or partial (the directory even
    # defaults to a bare "Chicago, IL"), so relaying the OSM address let the
    # agent state a wrong or missing address for a venue we can identify exactly.
    # Relay the record's authoritative address, and flag which source it came
    # from so the agent can label an OSM-only address as unverified. The OSM name
    # stays as the friendlier display `name`; the official `dba_name` rides
    # alongside for when the user asks for the registered name.
    record_address = record.get("address") or ""
    address = record_address or restaurant.get("address", "")
    address_source = "city_inspection_record" if record_address else "openstreetmap"
    return {
        # Identity
        "osm_id": restaurant["osm_id"],
        "name": restaurant["name"],
        "dba_name": record.get("dba_name", ""),
        "address": address,
        "address_source": address_source,
        "zip": record.get("zip", ""),
        "facility_type": record.get("facility_type", ""),
        "lat": restaurant.get("lat"),
        "lon": restaurant.get("lon"),
        "cuisine": restaurant.get("cuisine", ""),
        # Score (precomputed by the batch run)
        "risk_score": score,
        "risk_tier": tier,
        "shap_drivers": _drivers_from_top_drivers(record.get("top_drivers", [])),
        # A published batch score is not preliminary; -1.0 is the mock-data
        # sentinel for a placeholder scores.json (e.g. a dev build with no real
        # batch run), which the agent should flag as a preliminary estimate.
        "stub": score == -1.0,
        "stub_note": None,
        # Metadata from the matched record
        "license_id": record.get("license_id"),
        "matched_scores_json": True,
        "percentile_rank": record.get("percentile_rank"),
        "trend": _trend_label(record.get("trend_slope")),
        "neighborhood": record.get("neighborhood"),
        # Closure flag (scores schema 0.6.0, decision 0014). A closed venue's
        # forward-window score is historical, not a live signal; the prompt
        # directs the agent to disclose closure and frame the score that way.
        "is_out_of_business": bool(record.get("is_out_of_business")),
        "closed_since": record.get("closed_since"),
        "status": "scored",
    }


def _output_no_record(restaurant: dict[str, Any]) -> dict[str, Any]:
    """Build the response for a venue with no precomputed score.

    The batch run is the only source of a calibrated score, so a venue it does
    not cover has no inspection record we can speak to. We return an explicit
    no-record result with no number rather than scoring an all-zero feature
    vector at request time (see the module docstring).
    """
    return {
        # Identity. There is no matched city record, so any address here is the
        # OpenStreetMap directory's, not the authoritative city one — flag it so
        # the agent presents it as an unverified location, never as the city record.
        "osm_id": restaurant["osm_id"],
        "name": restaurant["name"],
        "dba_name": "",
        "address": restaurant.get("address", ""),
        "address_source": "openstreetmap",
        "zip": "",
        "facility_type": "",
        "lat": restaurant.get("lat"),
        "lon": restaurant.get("lon"),
        "cuisine": restaurant.get("cuisine", ""),
        # No score: this venue is not in the published batch run.
        "risk_score": None,
        "risk_tier": None,
        "shap_drivers": [],
        "stub": False,
        "stub_note": None,
        # No batch-run metadata for an unrecorded venue.
        "license_id": None,
        "matched_scores_json": False,
        "percentile_rank": None,
        "trend": None,
        "neighborhood": None,
        # No matched record, so no closure signal either way.
        "is_out_of_business": False,
        "closed_since": None,
        "status": "no_inspection_record",
    }


def _drivers_from_top_drivers(top_drivers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map scores.json ``top_drivers`` structs to the agent's shap_drivers shape."""
    drivers: list[dict[str, Any]] = []
    for d in top_drivers:
        shap = d.get("shap", 0.0)
        drivers.append(
            {
                "feature": d.get("feature", ""),
                # Keep the human-readable feature value from scores.json so the
                # agent can quote it in driver summaries.
                "value": d.get("value"),
                "label": d.get("label", ""),
                "detail": d.get("detail", ""),
                "shap": shap,
                "direction": "positive" if shap > 0 else "negative",
            }
        )
    return drivers
