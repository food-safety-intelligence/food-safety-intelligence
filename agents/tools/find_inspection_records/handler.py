"""
Lambda handler: find_inspection_records
---------------------------------------
Builds a deep link to the AUTHORITATIVE Chicago Food Inspections records for a
SET of establishments the agent is discussing — a comparison, a short list, or an
area. This is the city's own inspection data (the source the risk model is built
from), so unlike find_reviews it carries no disclaimer: it is provenance the user
can verify, not third-party opinion.

Same posture as find_reviews — we only BUILD a URL to the Chicago Data Portal's
filtered query view. No fetch, no credentials, nothing stored; the user clicks
through. The link opens the portal's query grid, filtered one of three ways by
whichever input the agent supplies:
  * license_ids           -> each establishment's full inspection history
  * zip                   -> every inspection in that ZIP
  * lat + lon + radius_m  -> every inspection within that radius

The agent has license_ids for anything it has scored (its universal key); it has
no inspection_id (no tool exposes one) and city dba_name matching is unreliable,
so those are deliberately NOT accepted as inputs.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

# Chicago Food Inspections dataset (Socrata 4x4) — the city record the risk model
# is built from. See docs/data_dictionary.md.
DATASET_ID = "4ijn-s7e5"
_QUERY_BASE = (
    "https://data.cityofchicago.org/Health-Human-Services/Food-Inspections/"
    f"{DATASET_ID}/explore/query"
)

# The columns the portal's own query builder emits, in order. An explicit SELECT
# is deliberate: the grid renders this form reliably, where `SELECT *` stalls it.
_SELECT_COLUMNS = (
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
    license_ids takes precedence if more than one mode is supplied.
    """
    license_ids = _dedupe_ids(event.get("license_ids"))
    zip_code = str(event.get("zip") or "").strip()
    lat, lon, radius_m = event.get("lat"), event.get("lon"), event.get("radius_m")

    truncated = False
    if license_ids:
        shown = license_ids[:MAX_IDS]
        truncated = len(license_ids) > MAX_IDS
        where = _in_clause("license_", shown)
        mode = "license_ids"
    elif zip_code:
        where = f"`zip`='{_soql_literal(zip_code)}'"
        mode = "zip"
    elif _is_number(lat) and _is_number(lon) and _is_number(radius_m):
        coords = f"{_fmt_num(lat)}, {_fmt_num(lon)}, {_fmt_num(radius_m)}"
        where = f"within_circle(`location`, {coords})"
        mode = "geo"
    else:
        return {
            "error": (
                "find_inspection_records needs one filter: license_ids, zip, or lat+lon+radius_m."
            ),
            "reason": "missing_filter",
        }

    note = (
        "Opens the Chicago Food Inspections portal filtered to these records — the "
        "city's own data behind the risk score. It can take a few seconds to load."
    )
    if truncated:
        note += f" Shows the first {MAX_IDS} of {len(license_ids)} establishments."

    return {"url": _build_url(where), "mode": mode, "truncated": truncated, "note": note}


def _dedupe_ids(raw: Any) -> list[str]:
    """Normalise ids to a de-duplicated list of non-empty strings; order preserved."""
    if raw is None or isinstance(raw, dict):
        return []
    if isinstance(raw, (str, int)):
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
    # form (verified to render). Ids are license numbers, but drop any stray
    # double quote defensively so a value can't break out of the string.
    values = ", ".join(f'"{i.replace(chr(34), "")}"' for i in ids)
    return f"`{column}` IN ({values})"


def _build_url(where: str) -> str:
    # Mirror the portal query-builder's own URL shape: an explicit newline-joined
    # column SELECT, the WHERE, then ORDER BY, percent-encoded into the path.
    select = "SELECT\n  " + ",\n  ".join(f"`{c}`" for c in _SELECT_COLUMNS)
    soql = f"{select}\nWHERE {where}\nORDER BY `inspection_date` DESC NULL FIRST"
    return f"{_QUERY_BASE}/{urllib.parse.quote(soql, safe='')}/page/filter"
