"""
Lambda handler: find_reviews
----------------------------
Surfaces THIRD-PARTY restaurant reviews (Yelp, Google, TripAdvisor) for a single
establishment, focused on the food-safety topics a diner cares about:
cleanliness, rodents/pests, food quality, and illness reports.

This is a chatbot convenience — an *option the agent offers* when the user asks
what reviewers say. It is deliberately kept separate from the risk model.

LEGAL POSTURE — read before changing this file:
  * We do NOT scrape or store Yelp / Google web pages. Their Terms of Service
    prohibit automated access to their pages, so this tool never fetches and
    parses them.
  * The tool only builds attributed DEEP LINKS to each source's review search
    for "<business> <topic>". The agent presents these as "view reviews" options
    and the USER clicks through to the source. Building a URL is not scraping,
    needs no credentials, and stores nothing.
  * Reviews are unverified user opinion and are NOT an input to the risk model.
    Every response carries that disclaimer so reviews never get read as a score.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Disclaimer attached to every response — keeps third-party opinion visibly
# distinct from the model's risk score so neither the agent nor the user
# conflates them.
DISCLAIMER = (
    "Third-party reviews are unverified diner opinions, not inspection results. "
    "They are NOT part of the food-safety risk score."
)

# Registry of valid topic keys → a diner-language description of each food-safety
# category. The keys are the accepted `topics` inputs (see _resolve_topics); the
# descriptions are documentary. Topics record what the user cares about but do NOT
# scope the review links — those go directly to each source's page for the
# business (no source exposes a keyless per-topic review filter).
TOPIC_LABELS: dict[str, str] = {
    "cleanliness": "cleanliness / sewage",
    "pests": "rodents / pests / droppings",
    "food_quality": "food quality / raw / spoiled",
    "illness": "illness / food poisoning",
}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    """
    Lambda entry point.

    Input event schema:
    {
        "name":    str,            # business name (required)
        "address": str | None,     # street address, improves link quality
        "topics":  list[str]       # subset of TOPIC_LABELS keys; empty = all
    }

    Returns:
    {
        "name": str,
        "topics": list[str],
        "review_links": list[{source, label, url}],
        "disclaimer": str
    }
    """
    name: str = (event.get("name") or "").strip()
    address: str = (event.get("address") or "").strip()
    topics: list[str] = _resolve_topics(event.get("topics"))

    if not name:
        return {"error": "find_reviews requires a restaurant 'name'.", "reason": "missing_name"}

    return {
        "name": name,
        "topics": topics,
        # Deep links always work — no credentials, no network call, nothing stored.
        "review_links": _build_review_links(name, address),
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


def _resolve_topics(raw: Any) -> list[str]:
    """Normalise the requested topics to known keys; empty/unknown → all topics."""
    if not raw:
        return list(TOPIC_LABELS)
    if isinstance(raw, str):
        raw = [raw]
    keep = [t.strip().lower() for t in raw if t.strip().lower() in TOPIC_LABELS]
    return keep or list(TOPIC_LABELS)


# ---------------------------------------------------------------------------
# Deep links (no network, no storage — always available)
# ---------------------------------------------------------------------------


def _build_review_links(name: str, address: str) -> list[dict[str, str]]:
    """
    Build attributed deep links to each source's reviews for this business.

    Each link goes DIRECTLY to its named source's own site (a "Yelp" link is a
    yelp.com URL, not a search-engine detour), using that site's keyless search
    endpoint. We only ever build the URL — no fetch, no credentials, nothing
    stored (see the LEGAL POSTURE note at the top).

    Why a per-site search and not a review permalink: reaching one business's
    reviews page needs that site's business id (Yelp alias / Google place_id /
    TripAdvisor location id), which name+address alone can't yield without an API
    or scraping. So each link lands ON the business via the site's own search —
    for a specific name + full address this surfaces that exact place (Google Maps
    typically opens its place card with reviews inline), one click from reviews.

    Links are general (the business's full reviews), not scoped to the requested
    food-safety topics — no source exposes a keyless per-topic review filter, and
    landing on the real reviews matters more than pre-filtering. The user can
    keyword-search within the source once there.
    """
    where = f"{name} {address}".strip()

    yelp = "https://www.yelp.com/search?" + urllib.parse.urlencode(
        # find_loc defaults to the city so an address-less lookup still scopes to Chicago.
        {"find_desc": name, "find_loc": address or "Chicago, IL"}
    )
    # Google Maps URLs scheme — a documented, keyless link format (NOT the paid
    # Maps API): opens the place on Maps, where its reviews live.
    google = "https://www.google.com/maps/search/?" + urllib.parse.urlencode(
        {"api": "1", "query": where}
    )
    tripadvisor = "https://www.tripadvisor.com/Search?" + urllib.parse.urlencode({"q": where})

    return [
        {"source": "Yelp", "label": "Yelp reviews", "url": yelp},
        {"source": "Google", "label": "Google Maps reviews", "url": google},
        {"source": "TripAdvisor", "label": "TripAdvisor reviews", "url": tripadvisor},
    ]
