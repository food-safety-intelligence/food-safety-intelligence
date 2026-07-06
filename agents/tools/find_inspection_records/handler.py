"""
Lambda handler: find_inspection_records
---------------------------------------
Builds a deep link to the ACTIVE CITY's AUTHORITATIVE food-inspection records for a
SET of establishments the agent is discussing — a comparison, a short list, or an
area. This is the city's own inspection data (the source the risk model is built
from), so unlike find_reviews it carries no disclaimer: it is provenance the user
can verify, not third-party opinion.

Same posture as find_reviews — we only BUILD a URL to the city's open-data query
view. No fetch, no credentials, nothing stored; the user clicks through. The link
opens the portal's query grid, filtered one of three ways by whichever input the
agent supplies:
  * license_ids           -> each establishment's full inspection history
  * zip                   -> every inspection in that ZIP
  * lat + lon + radius_m  -> every inspection within that radius

The agent has license_ids for anything it has scored (its universal key — it holds
each city's native id: Chicago license number, NYC CAMIS); it has no inspection_id
(no tool exposes one) and dba_name matching is unreliable, so those are NOT inputs.

City coverage: Chicago and NYC publish on Socrata, so a filtered query link works
for both. LA left Socrata for a bulk CSV with no queryable API, so there is no
filtered grid to link to — for LA the tool returns LA County Public Health's
inspections page (a lookup landing page), not a pre-filtered link.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

# Per-city open-data portal config. Each city's Socrata query grid uses the same
# {base}/{percent-encoded SoQL}/page/filter shape, but the dataset, the id column
# the agent filters on (the native id the scores carry), the ZIP column, and the
# SELECT list differ. All column lists were validated against the live SODA API.
_CITY_PORTALS: dict[str, dict[str, Any]] = {
    "chicago": {
        # Chicago Food Inspections (Socrata 4ijn-s7e5). See docs/data_dictionary.md.
        "base": "https://data.cityofchicago.org/Health-Human-Services/Food-Inspections/4ijn-s7e5/explore/query",
        "portal_name": "Chicago Food Inspections",
        "id_col": "license_",  # Chicago license number = the scores' license_id
        "zip_col": "zip",
        "geo_col": "location",
        "columns": (
            "inspection_id",
            "dba_name",
            "aka_name",
            "license_",
            "facility_type",
            "risk",
            "address",
            "city",
            "state",
            "zip",
            "inspection_date",
            "inspection_type",
            "results",
            "violations",
            "latitude",
            "longitude",
            "location",
        ),
    },
    "nyc": {
        # DOHMH NYC Restaurant Inspection Results (Socrata 43nn-pn8j).
        "base": "https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j/explore/query",
        "portal_name": "NYC restaurant inspection",
        "id_col": "camis",  # NYC CAMIS = the scores' license_id
        "zip_col": "zipcode",
        "geo_col": "location",
        "columns": (
            "camis",
            "dba",
            "boro",
            "building",
            "street",
            "zipcode",
            "cuisine_description",
            "inspection_date",
            "action",
            "violation_code",
            "violation_description",
            "critical_flag",
            "score",
            "grade",
            "grade_date",
            "inspection_type",
            "latitude",
            "longitude",
        ),
    },
}

# LA has no queryable portal (bulk CSV on ArcGIS Hub). Point the user to LA County
# Public Health's inspections landing page instead of a filtered grid.
_LA_INSPECTIONS_URL = (
    "https://publichealth.lacounty.gov/eh/inspection-and-reports/"
    "restaurant-and-market-inspections.htm"
)

# Cap on an enumerated id list. Each id adds ~15 chars to the URL; past this a
# long URL risks silently hitting proxy/server length limits. Larger sets should
# use the zip / geo modes, whose WHERE clause stays short at any count.
MAX_IDS = 25


def handler(event: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    """
    Input event — exactly ONE filter mode:
        {"license_ids": list[str]}                       # compare / list named places
        {"zip": str}                                     # area by ZIP
        {"lat": float, "lon": float, "radius_m": float}  # area by radius

    Returns {url, mode, truncated, note} — or {error, reason} if no mode is given.
    license_ids takes precedence if more than one mode is supplied. `city` (from
    the entrypoint) selects the portal; defaults to Chicago.
    """
    city = (event.get("city") or "chicago").strip().lower()
    portal = _CITY_PORTALS.get(city)
    if portal is None:
        # LA (and any future non-Socrata city): no queryable grid to filter. Hand
        # back the city's inspections landing page so the user still gets a real,
        # authoritative link to look records up themselves.
        if city == "la":
            return {
                "url": _LA_INSPECTIONS_URL,
                "mode": "city_page",
                "truncated": False,
                "note": (
                    "LA County's inspection data isn't a filtered link, so this opens "
                    "LA County Public Health's restaurant & market inspections page, "
                    "where the user can look a place up."
                ),
            }
        return {
            "error": f"find_inspection_records does not cover {city!r}.",
            "reason": "unsupported_city",
        }

    license_ids = _dedupe_ids(event.get("license_ids"))
    zip_code = str(event.get("zip") or "").strip()
    lat, lon, radius_m = event.get("lat"), event.get("lon"), event.get("radius_m")

    truncated = False
    if license_ids:
        shown = license_ids[:MAX_IDS]
        truncated = len(license_ids) > MAX_IDS
        where = _in_clause(portal["id_col"], shown)
        mode = "license_ids"
    elif zip_code:
        where = f"`{portal['zip_col']}`='{_soql_literal(zip_code)}'"
        mode = "zip"
    elif _is_number(lat) and _is_number(lon) and _is_number(radius_m):
        coords = f"{_fmt_num(lat)}, {_fmt_num(lon)}, {_fmt_num(radius_m)}"
        where = f"within_circle(`{portal['geo_col']}`, {coords})"
        mode = "geo"
    else:
        return {
            "error": (
                "find_inspection_records needs one filter: license_ids, zip, or lat+lon+radius_m."
            ),
            "reason": "missing_filter",
        }

    note = (
        f"Opens the {portal['portal_name']} portal filtered to these records — the "
        "city's own data behind the risk score. It can take a few seconds to load."
    )
    if truncated:
        note += f" Shows the first {MAX_IDS} of {len(license_ids)} establishments."

    return {"url": _build_url(where, portal), "mode": mode, "truncated": truncated, "note": note}


def _dedupe_ids(raw: Any) -> list[str]:
    """Normalise ids to a de-duplicated list of non-empty strings; order preserved.

    A bare scalar (the model emitting one id as a number/string instead of a list)
    is treated as a single id, not iterated — so a malformed float can't crash the
    tool; None / a mapping yields no ids so the caller degrades to a filter error.
    """
    if raw is None or isinstance(raw, dict):
        return []
    if not isinstance(raw, (list, tuple)):
        raw = [raw]
    seen: list[str] = []
    for item in raw:
        s = str(item).strip()
        if s and s not in seen:
            seen.append(s)
    return seen


def _is_number(x: Any) -> bool:
    # bool is an int subclass — exclude it so True/False can't act as coordinates.
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _fmt_num(x: float) -> str:
    """Compact numeric literal — drop a trailing '.0' so an integer radius reads
    as `300`, not `300.0` (matches the portal query-builder's own form)."""
    f = float(x)
    return str(int(f)) if f.is_integer() else repr(f)


def _soql_literal(s: str) -> str:
    """Escape a SoQL single-quoted string literal ('' escapes an embedded quote)."""
    return s.replace("'", "''")


def _in_clause(column: str, ids: list[str]) -> str:
    # The portal's query builder quotes IN values with double quotes; match that
    # form (verified to render). Ids are license numbers; strip any stray double
    # quote or backslash defensively so a value can't break out of the string
    # regardless of how the SoQL parser treats escapes.
    values = ", ".join(f'"{i.replace(chr(34), "").replace(chr(92), "")}"' for i in ids)
    return f"`{column}` IN ({values})"


def _build_url(where: str, portal: dict[str, Any]) -> str:
    # Mirror the portal query-builder's own URL shape: an explicit newline-joined
    # column SELECT, the WHERE, then ORDER BY, percent-encoded into the path.
    select = "SELECT\n  " + ",\n  ".join(f"`{c}`" for c in portal["columns"])
    soql = f"{select}\nWHERE {where}\nORDER BY `inspection_date` DESC NULL FIRST"
    return f"{portal['base']}/{urllib.parse.quote(soql, safe='')}/page/filter"
