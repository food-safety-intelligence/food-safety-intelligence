"""
Lambda handler: find_restaurants
---------------------------------
Queries OpenStreetMap via the public Overpass API to find restaurants in the
active city (Chicago / NYC / LA — see the event's `city`) matching the agent's
parsed intent (neighborhood, cuisine, radius).

No API key required. Free public endpoint.
Endpoint: https://overpass-api.de/api/interpreter
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from typing import Any

import chicago_neighborhoods as chi
import la_neighborhoods as la
import nyc_neighborhoods as nyc

# Per-city geography: (neighborhood bbox table, neighborhood centroids, whole-city
# bbox, whole-city centroid, display label). The handler selects the active city's
# tables so a NYC/LA lookup resolves against that city rather than Chicago (DR 0016).
CITY_GEO: dict[str, tuple] = {
    "chicago": (chi.BBOX, chi.CENTROIDS, chi.CHICAGO_BBOX, chi.CHICAGO_CENTROID, "Chicago"),
    "nyc": (nyc.BBOX, nyc.CENTROIDS, nyc.NYC_BBOX, nyc.NYC_CENTROID, "New York City"),
    "la": (la.BBOX, la.CENTROIDS, la.LA_BBOX, la.LA_CENTROID, "Los Angeles"),
}

# Fallback city/state for an OSM venue whose addr:* tags omit them. Must follow the
# ACTIVE CITY: a hardcoded Chicago default labelled Los Angeles venues "Chicago, IL",
# which the agent then relayed to the user as that venue's address.
CITY_ADDRESS_DEFAULTS: dict[str, tuple[str, str]] = {
    "chicago": ("Chicago", "IL"),
    "nyc": ("New York", "NY"),
    "la": ("Los Angeles", "CA"),
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT_S = 18  # HTTP socket timeout; slightly above the QL timeout

# Maps agent-friendly cuisine names → OSM cuisine tag regex patterns.
# OSM uses semicolon-separated values (e.g. "sushi;japanese"), so we match
# with a case-insensitive substring regex rather than exact equality.
CUISINE_ALIASES: dict[str, str] = {
    "sushi": "sushi|japanese",
    "ramen": "ramen|japanese",
    "japanese": "japanese|sushi|ramen",
    "thai": "thai",
    "chinese": "chinese",
    "korean": "korean",
    "vietnamese": "vietnamese",
    "mexican": "mexican|taco|burrito",
    "pizza": "pizza|italian",
    "italian": "italian|pizza|pasta",
    "indian": "indian|curry",
    "mediterranean": "mediterranean|greek|middle_eastern|turkish|falafel",
    "american": "american|burger|barbecue|bbq",
    "burger": "burger|american",
    "barbecue": "barbecue|bbq",
    "bbq": "barbecue|bbq",
    "seafood": "seafood|fish",
    "sandwich": "sandwich|deli|sub",
    "breakfast": "breakfast|brunch|diner",
    "brunch": "brunch|breakfast",
    "coffee": "coffee|cafe|bakery",
    "bakery": "bakery|pastry",
    "vegan": "vegan|vegetarian",
    "vegetarian": "vegetarian|vegan",
    "fast_food": "fast_food|burger|pizza|sandwich",
    "fast food": "fast_food|burger|pizza|sandwich",
    "steakhouse": "steak|steakhouse|american",
    "steak": "steak|steakhouse",
    "french": "french",
    "spanish": "spanish|tapas",
    "tapas": "tapas|spanish",
    "peruvian": "peruvian|latin_american",
    "latin": "latin_american|mexican|peruvian",
    "ethiopian": "ethiopian|african",
    "african": "african|ethiopian",
    "middle eastern": "middle_eastern|falafel|mediterranean",
    "falafel": "falafel|middle_eastern",
    "greek": "greek|mediterranean",
    "polish": "polish",
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], _ctx: Any) -> list[dict[str, Any]] | dict[str, Any]:
    """
    Lambda entry point.

    Input event schema:
    {
        "neighborhood": str | None,   # e.g. "Wicker Park"
        "lat":          float | None, # explicit coordinates (overrides neighborhood)
        "lon":          float | None,
        "radius_km":    float,        # default 1.0
        "cuisine":      str | None,   # e.g. "sushi", "ramen"
        "limit":        int,          # default 20, max 50
        "city":         str           # "chicago" (default) | "nyc" | "la"
    }

    Returns list[RestaurantStub] sorted by distance from query centroid, or a
    top-level {"error": ..., "reason": ...} object when the requested location is
    not a recognised area of the active city or the Overpass directory is unreachable.
    """
    neighborhood: str | None = event.get("neighborhood")
    lat: float | None = event.get("lat")
    lon: float | None = event.get("lon")
    radius_km: float = float(event.get("radius_km", 1.0))
    cuisine: str | None = event.get("cuisine")
    limit: int = min(int(event.get("limit", 20)), 50)

    # Resolve the active city's geography (default Chicago). Bbox validation, the
    # neighborhood table, and the whole-city fallback are all scoped to it.
    city = str(event.get("city", "chicago")).lower()
    bbox_table, centroids, city_bbox, city_centroid, city_label = CITY_GEO.get(
        city, CITY_GEO["chicago"]
    )

    # Keep the explicit-coordinate path city-scoped too (the neighborhood path
    # already is). Out-of-area coordinates would otherwise return results outside
    # the city the agent is meant to cover.
    if lat is not None and lon is not None and not _within_bbox(lat, lon, city_bbox):
        return {
            "error": (
                f"Coordinates ({lat}, {lon}) are outside the {city_label} area "
                "this assistant covers."
            ),
            "reason": "location_not_recognized",
        }

    geometry = _resolve_geometry(
        neighborhood, lat, lon, radius_km, bbox_table, centroids, city_bbox, city_centroid
    )
    if geometry is None:
        # The neighborhood table covers only the major named areas, so a real
        # place can still miss. Returning a whole-city fallback would silently
        # answer a different question, so surface it instead — but the message
        # must not claim the place isn't in the city (it might be); ask for a
        # major neighborhood name or coordinates rather than asserting.
        return {
            "error": (
                f"Couldn't pinpoint '{neighborhood}'. Try a major {city_label} "
                "neighborhood name or latitude/longitude."
            ),
            "reason": "location_not_recognized",
        }
    bbox, centroid = geometry
    cuisine_filter = _cuisine_filter(cuisine)

    query = _build_overpass_query(bbox, cuisine_filter, limit)

    try:
        raw = _fetch_overpass(query)
    except urllib.error.URLError as exc:
        # Surface a top-level error object (not a list with a fake restaurant)
        # so a downstream tool never reads osm_id off a malformed element and
        # the agent can degrade gracefully on an upstream outage.
        return {"error": f"Overpass API unavailable: {exc}", "reason": "directory_unavailable"}

    elements: list[dict] = raw.get("elements", [])
    results = _parse_elements(
        elements, centroid, CITY_ADDRESS_DEFAULTS.get(city, ("Chicago", "IL"))
    )
    results.sort(key=lambda r: r["dist_km"])
    return results[:limit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _within_bbox(lat: float, lon: float, bbox: dict[str, float]) -> bool:
    """Return True when the coordinate falls inside the given bounding box."""
    return bbox["south"] <= lat <= bbox["north"] and bbox["west"] <= lon <= bbox["east"]


def _resolve_geometry(
    neighborhood: str | None,
    lat: float | None,
    lon: float | None,
    radius_km: float,
    bbox_table: dict[str, dict[str, float]],
    centroids: dict[str, tuple[float, float]],
    city_bbox: dict[str, float],
    city_centroid: tuple[float, float],
) -> tuple[dict[str, float], tuple[float, float]] | None:
    """Return (bbox dict, centroid tuple) for the query in the given city's tables.

    Returns ``None`` when a neighborhood was given but is not a recognised area of
    the city (and no explicit coordinates were supplied) so the caller can report
    it rather than silently falling back to a whole-city search.
    """
    # Explicit coordinates take priority.
    if lat is not None and lon is not None:
        d = radius_km / 111.0  # 1 degree ≈ 111 km
        return (
            {"south": lat - d, "west": lon - d, "north": lat + d, "east": lon + d},
            (lat, lon),
        )

    if neighborhood:
        # Try exact match first, then case-insensitive.
        key = neighborhood.strip().title()
        entry = bbox_table.get(key)
        if not entry:
            key_lower = neighborhood.strip().lower()
            for k, v in bbox_table.items():
                if k.lower() == key_lower:
                    entry = v
                    key = k
                    break
        if entry:
            return entry, centroids[key]
        # Neighborhood given but unrecognised — signal the caller, don't fall back
        # to a whole-city search (that would answer a different question).
        return None

    # Nothing specified — default to a whole-city search.
    return city_bbox, city_centroid


def _cuisine_filter(cuisine: str | None) -> str:
    """Build an Overpass tag filter string for the cuisine, or empty string."""
    if not cuisine:
        return ""
    pattern = CUISINE_ALIASES.get(cuisine.lower().strip(), cuisine.strip())
    # Escape characters that have special meaning in Overpass regex.
    return f'["cuisine"~"{pattern}",i]'


def _build_overpass_query(bbox: dict[str, float], cuisine_filter: str, limit: int) -> str:
    """
    Build an Overpass QL query that returns restaurant nodes and ways within
    the bounding box.

    We request `out center tags <limit>` so that way elements also return a
    single centre coordinate rather than a full polygon.
    """
    s, w, n, e = bbox["south"], bbox["west"], bbox["north"], bbox["east"]
    bbox_str = f"({s},{w},{n},{e})"

    return f"""
[out:json][timeout:15];
(
  node["amenity"="restaurant"]{cuisine_filter}{bbox_str};
  way ["amenity"="restaurant"]{cuisine_filter}{bbox_str};
  node["amenity"="cafe"]{cuisine_filter}{bbox_str};
  node["amenity"="fast_food"]{cuisine_filter}{bbox_str};
);
out center tags {limit};
""".strip()


def _fetch_overpass(query: str) -> dict:
    """POST the Overpass QL query and return the parsed JSON response."""
    req = urllib.request.Request(
        OVERPASS_URL,
        data=query.encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            # Overpass public endpoint requires a non-empty User-Agent.
            "User-Agent": "FoodSafetyIntelligence/1.0 (capstone; contact: github.com/deepak)",
        },
    )
    with urllib.request.urlopen(req, timeout=OVERPASS_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_elements(
    elements: list[dict],
    centroid: tuple[float, float],
    city_default: tuple[str, str],
) -> list[dict[str, Any]]:
    """Convert raw Overpass elements to clean restaurant stubs."""
    results: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for el in elements:
        tags: dict[str, str] = el.get("tags", {})

        name = tags.get("name") or tags.get("name:en", "")
        if not name:
            continue

        # Deduplicate chains with the same name at the same approximate spot.
        el_lat: float | None = el.get("lat") or el.get("center", {}).get("lat")
        el_lon: float | None = el.get("lon") or el.get("center", {}).get("lon")
        if el_lat is None or el_lon is None:
            continue

        dedup_key = f"{name.lower()}_{round(el_lat, 3)}_{round(el_lon, 3)}"
        if dedup_key in seen_names:
            continue
        seen_names.add(dedup_key)

        results.append(
            {
                "osm_id": str(el["id"]),
                "name": name,
                "address": _build_address(tags, city_default),
                "lat": el_lat,
                "lon": el_lon,
                "cuisine": tags.get("cuisine", ""),
                "opening_hours": tags.get("opening_hours", ""),
                "phone": tags.get("phone") or tags.get("contact:phone", ""),
                "website": tags.get("website") or tags.get("contact:website", ""),
                "dist_km": _haversine(centroid[0], centroid[1], el_lat, el_lon),
            }
        )

    return results


def _build_address(tags: dict[str, str], city_default: tuple[str, str]) -> str:
    """Assemble a human-readable address from OSM addr:* tags."""
    parts: list[str] = []
    housenumber = tags.get("addr:housenumber", "")
    street = tags.get("addr:street", "")
    default_city, default_state = city_default
    city = tags.get("addr:city", default_city)
    state = tags.get("addr:state", default_state)
    postcode = tags.get("addr:postcode", "")

    if housenumber and street:
        parts.append(f"{housenumber} {street}")
    elif street:
        parts.append(street)

    if city:
        parts.append(city)
    if state:
        parts.append(state)
    if postcode:
        parts.append(postcode)

    return ", ".join(parts) if parts else ""


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in kilometres."""
    R = 6_371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))
