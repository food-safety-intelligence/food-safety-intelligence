"""Per-city framing + scope prefix shared by the deployed runtime (entrypoint.py)
and the local runner / eval (run_local.py), so a request is framed in the active
city's terms IDENTICALLY in both. Kept dependency-free (no AWS imports) so the
eval can import it without the AgentCore runtime deps.

The prefix does two jobs, prepended to the system prompt each request:
  1. States how THIS city grades inspections (letter grades vs Chicago pass/fail;
     LA's 0-100 scale runs the opposite way to NYC), so the model explains a score
     in the active city's terms without a tool round-trip.
  2. Scopes the request to the active city and forbids using another city's places.
"""

from __future__ import annotations

_CITY_LABELS = {"chicago": "Chicago", "nyc": "New York City", "la": "Los Angeles"}

# One line per city on how its inspections are graded. Chicago is the default.
_CITY_GRADING = {
    "chicago": (
        "Chicago inspections are recorded as Pass, Pass with Conditions, or Fail "
        "with cited violation codes (there is no letter grade)."
    ),
    "nyc": (
        "NYC inspections get a letter grade A/B/C from a points score where FEWER "
        "points is cleaner (A is best); a higher risk score means a likelier B or C."
    ),
    "la": (
        "LA County inspections get a letter grade A/B/C from a 0-100 score where a "
        "HIGHER score is cleaner (A is 90-100, the opposite direction to NYC); a "
        "higher risk score means a likelier B or C."
    ),
}


def city_label(city: str) -> str:
    """Human-readable name for a city key; unknown keys fall back to Chicago."""
    return _CITY_LABELS.get(city, "Chicago")


def city_prefix(city: str) -> str:
    """The ACTIVE CITY block prepended to the system prompt for a request."""
    label = city_label(city)
    grading = _CITY_GRADING.get(city, _CITY_GRADING["chicago"])
    return (
        f"ACTIVE CITY: {label}. {grading} Scope every NEW restaurant lookup and "
        f"'no record' statement to {label}, and never present another city's "
        f"establishment as if it is in {label}. If an earlier turn in this "
        f"conversation discussed a place in a DIFFERENT city, name that city and "
        f"suggest the user switch back to it (via the city selector) to continue with "
        f"that place — do not re-look-it-up or present it as a {label} result.\n\n"
    )
