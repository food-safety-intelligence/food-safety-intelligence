"""
Lambda handler: find_reviews
----------------------------
Surfaces THIRD-PARTY restaurant reviews (Yelp, Google, web) for a single
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

# Diner-facing safety topics → human labels used in the agent-facing link text.
# This dict is also the registry of valid topic keys.
TOPIC_LABELS: dict[str, str] = {
    "cleanliness": "cleanliness",
    "pests": "rodents / pests / droppings",
    "food_quality": "food quality",
    "illness": "illness reports",
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
        "review_links": _build_review_links(name, address, topics),
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


def _topic_terms(topics: list[str]) -> str:
    """Short free-text term for the search query, e.g. 'cleanliness pests'."""
    return " ".join(TOPIC_LABELS[t].replace(" / ", " ") for t in topics)


# ---------------------------------------------------------------------------
# Deep links (no network, no storage — always available)
# ---------------------------------------------------------------------------


def _build_review_links(name: str, address: str, topics: list[str]) -> list[dict[str, str]]:
    """
    Build attributed deep links to each source's review search for this
    business + topics. These are URLs the user clicks through to; we never
    fetch them.
    """
    where = f"{name} {address}".strip()
    terms = _topic_terms(topics)
    topic_label = ", ".join(TOPIC_LABELS[t] for t in topics)

    yelp = "https://www.yelp.com/search?" + urllib.parse.urlencode(
        {"find_desc": name, "find_loc": address or "Chicago, IL"}
    )
    # safe="" so a "/" in the name (e.g. "Sweet/Savory") is percent-encoded
    # rather than becoming an extra path segment in the Maps search URL.
    google = "https://www.google.com/maps/search/" + urllib.parse.quote(where, safe="")
    web = "https://duckduckgo.com/?" + urllib.parse.urlencode(
        {"q": f"{where} reviews {terms}".strip()}
    )

    return [
        {"source": "Yelp", "label": f"Yelp reviews ({topic_label})", "url": yelp},
        {"source": "Google", "label": f"Google reviews ({topic_label})", "url": google},
        {"source": "Web", "label": f"Web search ({topic_label})", "url": web},
    ]
