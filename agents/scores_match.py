"""
Shared scores.json matching primitives — Food Safety Intelligence agent.
------------------------------------------------------------------------
The rules for deciding whether an OSM `name` / free-text name and a city
`dba_name` denote the same establishment, and for normalising addresses and
names before comparing, are subtle (store numbers, generic words, the
"Amarit" vs "AMARIT RESTAURANT" length mismatch). They must match identically
wherever the agent resolves a venue, so they live here once:

  * get_safety_score  — batch, OSM-driven (address + name, geo fallback)
  * look_up_establishment — name-only lookup for general chat

These are PURE functions over records the caller has already loaded: no file
IO and no cache. Each tool keeps its own (cached) loader and passes the index
or record list in, so this module stays trivially testable and never reaches
for a data file.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

# Address must be a close match AND the best name in that address bucket must
# clear its own bar before we attach a score. Name is the disambiguator at
# shared addresses, so it gets the stricter, independently-tuned cutoff.
ADDRESS_CUTOFF = 0.72
NAME_CUTOFF = 0.6

# Name + geographic-proximity fallback, used only when the address match fails.
# OSM very often carries no clean street address (just "Chicago, IL" or nothing),
# so address-only matching reports a venue that IS in the batch run as having no
# record (e.g. "Amarit" -> the real "AMARIT RESTAURANT"). lat/lon + name recovers
# it: OSM and the city geocode the same building to slightly different points, so
# any record within ~0.0025° (≈250 m) is a candidate, then the name must agree.
# Proximity alone is not enough — a dense block holds many venues — so the name
# is what identifies the establishment (ethics decision record 0005, principle 1:
# a confident wrong score is worse than a miss).
GEO_RADIUS_DEG = 0.0025
# SequenceMatcher ratio bar for the near-identical / typo case; the token-subset
# rule below handles the common "Amarit" vs "AMARIT RESTAURANT" length mismatch
# that ratio alone scores too low (~0.55) to accept.
GEO_NAME_RATIO_CUTOFF = 0.87

# Generic establishment words carry no identifying signal, so a name made only of
# them (e.g. a bare "Restaurant" OSM node) must never match by the token-subset
# rule — that would attach a neighbour's score on proximity alone.
GENERIC_NAME_TOKENS = frozenset(
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


def normalise_address(addr: str) -> str:
    """Uppercase, reduce to the street portion, expand abbreviations, collapse space.

    The two sides are written differently: OSM assembles a full postal address
    ("1115 North San Fernando Boulevard, Burbank, CA, 91504") while every city's
    scores.json stores a bare street line ("13736 AMAR RD") — measured at <0.05%
    commas across Chicago, NYC and LA. Comparing the two whole meant the address
    bucket essentially never hit outside Chicago, pushing every venue onto the
    ~250m geo fallback. Keeping only the text before the first comma puts both
    sides in the same shape; it is a no-op on the city records themselves.
    """
    addr = addr.split(",")[0].upper()
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


def normalise_name(name: str) -> str:
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


def fuzzy_lookup(address: str, name: str, index: dict[str, list[dict]]) -> dict | None:
    """Return the best score record for this (address, name), or None.

    Resolve the address to a bucket of records (exact key, then fuzzy over the
    keys), then pick the record in that bucket whose `dba_name` best matches
    `name`. BOTH the address and the best name must clear their cutoffs.

    A shared address (food court, airport terminal) holds many establishments,
    so address alone can attach the wrong business's score — a consumer-facing
    wrong-signal harm (ethics decision record 0005, principle 1). A missed
    match (None) is safer than a confident wrong one.
    """
    key = normalise_address(address)
    bucket = index.get(key)
    address_is_exact = bucket is not None
    if bucket is None:
        matches = difflib.get_close_matches(key, index.keys(), n=1, cutoff=ADDRESS_CUTOFF)
        if not matches:
            return None
        bucket = index[matches[0]]

    # A single-occupancy address used to return its record with no name check at all,
    # which attached the wrong business's score in two ways, both seen on live Los
    # Angeles data:
    #   * a fuzzy address hop lands in a different building's bucket — OSM
    #     "Taco Bell, 1115 N San Fernando Blvd" resolved to "STARBUCKS COFFEE #9746";
    #   * the address matches exactly but the city record on it is a different tenant
    #     — "Cafe Etc." resolved to "CAFFE HUB".
    # How hard to gate depends on how much the address already proved. An exact
    # address is strong evidence, so only rule out names with nothing in common;
    # demanding a full match there would drop honest rewrites like OSM "Amarit Thai"
    # vs the city's "AMARIT RESTAURANT". A fuzzy address proved much less, so it has
    # to clear the full bar.
    if len(bucket) == 1:
        dba = bucket[0].get("dba_name", "")
        gate = shares_distinctive_token if address_is_exact else names_match
        return bucket[0] if gate(name, dba) else None

    target = normalise_name(name)
    if not target:
        return None

    best: dict | None = None
    best_ratio = 0.0
    for record in bucket:
        ratio = difflib.SequenceMatcher(
            None, target, normalise_name(record.get("dba_name", ""))
        ).ratio()
        # Strict `>` keeps the first record on an exact tie, so a tie resolves to
        # scores.json order. This only bites when two venues share both an
        # address and an identical name (near-indistinguishable), and we have no
        # better signal (no license_id) to break it — so first-in-order is fine.
        if ratio > best_ratio:
            best_ratio = ratio
            best = record

    return best if best_ratio >= NAME_CUTOFF else None


def shares_distinctive_token(osm_name: str, dba_name: str) -> bool:
    """True if the two names share at least one non-generic word.

    A deliberately weaker bar than `names_match`, for the case where the ADDRESS
    already matched exactly and the only job is to catch a name that is obviously a
    different business. OSM and the city often write the same venue differently
    enough to fail `names_match` ("Amarit Thai" vs "AMARIT RESTAURANT" share no
    subset and score ~0.55), so demanding a full match there throws away real
    matches — but a genuinely different tenant shares no distinctive word at all
    ("Cafe Etc." vs "CAFFE HUB", "Taco Bell" vs "STARBUCKS COFFEE").
    """
    a = set(normalise_name(osm_name).split()) - GENERIC_NAME_TOKENS
    b = set(normalise_name(dba_name).split()) - GENERIC_NAME_TOKENS
    return bool(a & b)


def names_match(osm_name: str, dba_name: str) -> bool:
    """True if a free-text / OSM name and a city dba_name plausibly name the same venue.

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
    a = normalise_name(osm_name).split()
    b = normalise_name(dba_name).split()
    if not a or not b:
        return False

    short, long = (a, b) if len(a) <= len(b) else (b, a)
    short_set, long_set = set(short), set(long)
    if short_set <= long_set and any(t not in GENERIC_NAME_TOKENS for t in short_set):
        return True

    ratio = difflib.SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b))).ratio()
    return ratio >= GEO_NAME_RATIO_CUTOFF


def geo_lookup(name: str, lat: float | None, lon: float | None, records: list[dict]) -> dict | None:
    """Find a score record by name within ~250 m of (lat, lon), or None.

    The address-first path misses any venue whose OSM record lacks a clean
    street address; this recovers it from coordinates + name. Among all records
    inside the proximity box whose name matches, return the one with the highest
    name-similarity ratio (ties resolve to scores.json order).
    """
    if lat is None or lon is None or not normalise_name(name):
        return None

    target = " ".join(sorted(normalise_name(name).split()))
    best: dict | None = None
    best_ratio = -1.0
    for record in records:
        rlat, rlon = record.get("lat"), record.get("lon")
        if rlat is None or rlon is None:
            continue
        # Cheap bounding-box reject before the (relatively costly) name compare.
        if abs(rlat - lat) > GEO_RADIUS_DEG or abs(rlon - lon) > GEO_RADIUS_DEG:
            continue
        if not names_match(name, record.get("dba_name", "")):
            continue
        ratio = difflib.SequenceMatcher(
            None, target, " ".join(sorted(normalise_name(record.get("dba_name", "")).split()))
        ).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = record
    return best


def name_search(query: str, records: list[dict], limit: int = 8) -> list[dict[str, Any]]:
    """Rank score records whose `dba_name` denotes the establishment `query` names.

    A name-only resolver for the general-chat lookup: no address, no
    coordinates, just a name the user typed. Keeps every record that clears the
    same `names_match` identity rule the geo path uses, ranked by
    name-similarity (best first). Returns at most `limit` candidates.

    The caller decides what to do with the shape of the result:
      * exactly one candidate  -> a confident match,
      * several candidates     -> a common name (a chain, or two venues with the
                                  same name) to disambiguate by address,
      * empty                  -> no city inspection record for that name (the
                                  caller must NOT invent one).

    A blank / whitespace query, or one that normalises to nothing, returns []
    rather than matching everything.
    """
    if not normalise_name(query):
        return []

    target = " ".join(sorted(normalise_name(query).split()))
    scored: list[tuple[float, dict]] = []
    for record in records:
        dba = record.get("dba_name", "")
        if not names_match(query, dba):
            continue
        ratio = difflib.SequenceMatcher(
            None, target, " ".join(sorted(normalise_name(dba).split()))
        ).ratio()
        scored.append((ratio, record))

    # Best match first; a stable sort keeps scores.json order among equal ratios
    # (same tie-break the address/geo paths use).
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [record for _ratio, record in scored[:limit]]


def trend_label(slope: float | None) -> str:
    """Map a forecast trend slope to a plain-English direction label.

    A null slope means the venue has fewer than 2 scored inspections, so no
    forward slope can be fit — that is "we can't say", not a flat trend.
    Reporting it as "stable" is what let the trend_slope_90d -> trend_slope
    rename miss (decision 0011) go silent in the deployed agent, so say so
    explicitly instead.
    """
    if slope is None:
        return "not enough inspection history"
    if slope > 0.001:
        return "worsening"
    if slope < -0.001:
        return "improving"
    return "stable"
