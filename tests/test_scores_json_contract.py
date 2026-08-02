"""Data-contract tests over the REAL committed ``scores.json`` for every city.

Why this file exists
--------------------
``neighborhood`` / ``zip`` / ``facility_type`` shipped EMPTY in all three cities for
months while the chat agent's chart tool advertised them as filters. Every filter the
model wrote matched nothing, so it received a valid empty frame with no error and
told users the city had no such places.

Nothing caught it, because every existing test used synthetic fixtures. The chart
tool's fixture sets ``"neighborhood": "N"``; the real data had it blank in all 89,719
rows. A test suite that only ever sees invented data cannot discover that the real
data is empty — so these tests read the actual committed artifacts.

The assertions are deliberately about POPULATION, not values: which fields a city
publishes is a contract, but the specific ZIPs and areas change on every republish.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "app" / "public" / "data"

# Per city: the published file, and which display columns that city's FEED can fill.
# Coverage differs by feed and that is expected — see
# ``foodsafety.serve.predict_batch.add_display_geography``:
#   * zip           — every city.
#   * neighborhood  — NYC (borough) and LA (incorporated / postal city). Chicago's
#                     feed has no area signal (its `city` column reads CHICAGO on
#                     99.6% of rows), so empty there is CORRECT, not a regression.
#   * facility_type — Chicago only.
CITIES = {
    "chicago": {
        "path": DATA / "scores.json",
        "populated": {"zip", "facility_type"},
        "empty": {"neighborhood"},
    },
    "nyc": {
        "path": DATA / "nyc" / "scores.json",
        "populated": {"zip", "neighborhood"},
        "empty": {"facility_type"},
    },
    "la": {
        "path": DATA / "la" / "scores.json",
        "populated": {"zip", "neighborhood"},
        "empty": {"facility_type"},
    },
}

# A published column counts as live only if it is broadly filled. A few blank rows are
# normal feed noise (NYC's zip is ~98.7%); a column that is 3% filled is broken and
# would still pass a naive "any non-empty value" check.
MIN_COVERAGE = 0.90


@cache
def _rows(city: str) -> tuple[dict, ...]:
    path = CITIES[city]["path"]
    if not path.exists():
        pytest.skip(f"{path} not present in this checkout")
    return tuple(json.loads(path.read_text())["scores"])


def _coverage(city: str, column: str) -> float:
    rows = _rows(city)
    return sum(1 for r in rows if str(r.get(column, "")).strip()) / len(rows)


@pytest.mark.parametrize("city", sorted(CITIES))
def test_advertised_columns_are_actually_populated(city):
    """The regression itself: a column this city publishes must not be all-empty."""
    for column in sorted(CITIES[city]["populated"]):
        coverage = _coverage(city, column)
        assert coverage >= MIN_COVERAGE, (
            f"{city}: {column!r} is only {coverage:.1%} populated in the published "
            f"scores.json. The chart tool offers it as a filter, so an empty column "
            f"makes every filtered chart silently return no rows."
        )


@pytest.mark.parametrize("city", sorted(CITIES))
def test_columns_this_feed_cannot_fill_stay_empty(city):
    """The other direction: a column with no source must stay blank rather than be
    faked. Chicago has no neighborhood signal, and inventing one (e.g. from a
    hand-drawn bounding box) would put unverifiable geography in front of users."""
    for column in sorted(CITIES[city]["empty"]):
        coverage = _coverage(city, column)
        assert coverage == 0.0, (
            f"{city}: {column!r} is {coverage:.1%} populated, but this city's feed "
            f"has no source for it. Populating it means it came from somewhere "
            f"undocumented."
        )


@pytest.mark.parametrize("city", sorted(CITIES))
def test_display_columns_are_always_present_and_are_strings(city):
    """Never null and never missing, so a consumer can call .strip() unconditionally.
    The web app does exactly that on the detail page."""
    for row in _rows(city)[:2000]:
        for column in ("neighborhood", "zip", "facility_type"):
            assert column in row, f"{city}: {column!r} missing from a score row"
            assert isinstance(row[column], str), f"{city}: {column!r} is not a string"


def test_a_known_area_resolves_to_a_non_empty_slice():
    """The user-facing symptom that started this: asking for a chart of West
    Hollywood returned nothing. It is a separate incorporated city in LA County, so
    the LA feed's own `city` column names it exactly."""
    la = _rows("la")
    weho = [r for r in la if r["neighborhood"] == "West Hollywood"]
    assert weho, "no LA establishments in West Hollywood — the filter is dead again"

    nyc = _rows("nyc")
    manhattan = [r for r in nyc if r["neighborhood"] == "Manhattan"]
    assert manhattan, "no NYC establishments in Manhattan"


def test_zip_values_are_five_digits():
    """ZIP+4 and stray whitespace would break an equality filter the model writes."""
    for city in sorted(CITIES):
        bad = [
            r["zip"]
            for r in _rows(city)
            if r["zip"] and not (r["zip"].isdigit() and len(r["zip"]) == 5)
        ]
        assert not bad, f"{city}: non 5-digit ZIPs published, e.g. {bad[:5]}"
