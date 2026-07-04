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

import difflib
import functools
import json
import os
import re
from typing import Any

# ---------------------------------------------------------------------------
# Scores.json loader
# ---------------------------------------------------------------------------


# Address must be a close match AND the best name in that address bucket must
# clear its own bar before we attach a score. Name is the disambiguator at
# shared addresses, so it gets the stricter, independently-tuned cutoff.
_ADDRESS_CUTOFF = 0.72
_NAME_CUTOFF = 0.6

# Name + geographic-proximity fallback, used only when the address match fails.
# OSM very often carries no clean street address (just "Chicago, IL" or nothing),
# so address-only matching reports a venue that IS in the batch run as having no
# record (e.g. "Amarit" -> the real "AMARIT RESTAURANT"). lat/lon + name recovers
# it: OSM and the city geocode the same building to slightly different points, so
# any record within ~0.0025° (≈250 m) is a candidate, then the name must agree.
# Proximity alone is not enough — a dense block holds many venues — so the name
# is what identifies the establishment (ethics decision record 0005, principle 1:
# a confident wrong score is worse than a miss).
_GEO_RADIUS_DEG = 0.0025
# SequenceMatcher ratio bar for the near-identical / typo case; the token-subset
# rule below handles the common "Amarit" vs "AMARIT RESTAURANT" length mismatch
# that ratio alone scores too low (~0.55) to accept.
_GEO_NAME_RATIO_CUTOFF = 0.87

# Generic establishment words carry no identifying signal, so a name made only of
# them (e.g. a bare "Restaurant" OSM node) must never match by the token-subset
# rule — that would attach a neighbour's score on proximity alone.
_GENERIC_NAME_TOKENS = frozenset(
    {
        "RESTAURANT",
        "CAFE",
        "GRILL",
        "BAR",
        "KITCHEN",
        "INC",
        "LLC",
        "LTD",
        "CO",
        "CORP",
        "THE",
        "AND",
        "OF",
        "CHICAGO",
        "FOOD",
        "FOODS",
        "CUISINE",
        "EATERY",
        "DINER",
    }
)


# Per-city scores.json path (multi-city, DR 0016). The entrypoint warms each
# city's file to a separate /tmp path; default to Chicago.
def _scores_path(city: str) -> str:
    if city == "nyc":
        return os.environ.get("SCORES_JSON_PATH_NYC", "/opt/nyc_scores.json")
    return os.environ.get("SCORES_JSON_PATH", "/opt/scores.json")


@functools.lru_cache(maxsize=2)
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


@functools.lru_cache(maxsize=2)
def _load_scores_records(city: str = "chicago") -> list[dict]:
    """Flat list of every score record, for the name + proximity fallback.

    Derived from the cached address index so scores.json is read only once.
    """
    return [r for bucket in _load_scores_index(city).values() for r in bucket]


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
    # A scores.json record may carry an explicit null name; coerce so .upper()
    # never crashes on None.
    name = (name or "").upper()
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

    # A single-occupancy address already uniquely identifies the establishment,
    # so skip the name gate here — applying it would regress recall when OSM
    # `name` and city `dba_name` disagree. Name disambiguation is only needed
    # when 2+ records share the address.
    if len(bucket) == 1:
        return bucket[0]

    target = _normalise_name(name)
    if not target:
        return None

    best: dict | None = None
    best_ratio = 0.0
    for record in bucket:
        ratio = difflib.SequenceMatcher(
            None, target, _normalise_name(record.get("dba_name", ""))
        ).ratio()
        # Strict `>` keeps the first record on an exact tie, so a tie resolves to
        # scores.json order. This only bites when two venues share both an
        # address and an identical name (near-indistinguishable), and we have no
        # better signal (no license_id) to break it — so first-in-order is fine.
        if ratio > best_ratio:
            best_ratio = ratio
            best = record

    return best if best_ratio >= _NAME_CUTOFF else None


def _names_match(osm_name: str, dba_name: str) -> bool:
    """True if an OSM name and a city dba_name plausibly name the same venue.

    Two complementary rules, because OSM and the city write names very
    differently:

    * Token-subset: every word of the shorter name appears in the longer one,
      and the shorter name has at least one distinctive (non-generic) word.
      This accepts "Amarit" vs "AMARIT RESTAURANT" (a pure length mismatch that
      SequenceMatcher scores far too low) while rejecting "China Cafe" vs
      "China Grill" (neither is a subset of the other).
    * High SequenceMatcher ratio: catches near-identical spellings / word order
      that the subset rule misses.
    """
    a = _normalise_name(osm_name).split()
    b = _normalise_name(dba_name).split()
    if not a or not b:
        return False

    short, long = (a, b) if len(a) <= len(b) else (b, a)
    short_set, long_set = set(short), set(long)
    if short_set <= long_set and any(t not in _GENERIC_NAME_TOKENS for t in short_set):
        return True

    ratio = difflib.SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b))).ratio()
    return ratio >= _GEO_NAME_RATIO_CUTOFF


def _geo_lookup(
    name: str, lat: float | None, lon: float | None, records: list[dict]
) -> dict | None:
    """Find a score record by name within ~250 m of (lat, lon), or None.

    The address-first path misses any venue whose OSM record lacks a clean
    street address; this recovers it from coordinates + name. Among all records
    inside the proximity box whose name matches, return the one with the highest
    name-similarity ratio (ties resolve to scores.json order).
    """
    if lat is None or lon is None or not _normalise_name(name):
        return None

    target = " ".join(sorted(_normalise_name(name).split()))
    best: dict | None = None
    best_ratio = -1.0
    for record in records:
        rlat, rlon = record.get("lat"), record.get("lon")
        if rlat is None or rlon is None:
            continue
        # Cheap bounding-box reject before the (relatively costly) name compare.
        if abs(rlat - lat) > _GEO_RADIUS_DEG or abs(rlon - lon) > _GEO_RADIUS_DEG:
            continue
        if not _names_match(name, record.get("dba_name", "")):
            continue
        ratio = difflib.SequenceMatcher(
            None, target, " ".join(sorted(_normalise_name(record.get("dba_name", "")).split()))
        ).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = record
    return best


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
            "name":         str,
            "address":      str,
            "license_id":   str | null,
            "risk_score":   float | null,  # calibrated probability 0–1, or null
            "risk_tier":    str | null,    # "Low" | "Moderate" | "Elevated" | "High"
            "trend":        str | null,    # "improving" | "stable" | "worsening"
                                           #   | "not enough inspection history"
            "percentile_rank": float | null,
            "shap_drivers": list,
            "matched_scores_json": bool,
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
    return {
        # Identity
        "osm_id": restaurant["osm_id"],
        "name": restaurant["name"],
        "address": restaurant.get("address", ""),
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
        # Identity
        "osm_id": restaurant["osm_id"],
        "name": restaurant["name"],
        "address": restaurant.get("address", ""),
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


def _trend_label(slope: float | None) -> str:
    # Under scores schema 0.5.0 a null trend_slope means the venue has fewer
    # than 2 scored inspections, so no forward slope can be fit — that is "we
    # can't say", not a flat trend. Reporting it as "stable" is what let the
    # trend_slope_90d->trend_slope rename miss (decision 0011) go silent in the
    # deployed agent, so say so explicitly instead.
    if slope is None:
        return "not enough inspection history"
    if slope > 0.001:
        return "worsening"
    if slope < -0.001:
        return "improving"
    return "stable"
