"""
Lambda handler: find_reviews
----------------------------
Surfaces THIRD-PARTY restaurant reviews (Yelp, Google) for a single
establishment, focused on the food-safety topics a diner cares about:
cleanliness, rodents/pests, food quality, and illness reports.

This is a chatbot convenience — an *option the agent offers* when the user asks
what reviewers say. It is deliberately kept separate from the risk model.

LEGAL POSTURE — read before changing this file:
  * We do NOT scrape or store Yelp / Google web pages. Their Terms of Service
    prohibit automated access to their pages, so this tool never fetches and
    parses them.
  * Default behaviour builds attributed DEEP LINKS to each source's review
    search for "<business> <topic>". The agent presents these as "view reviews"
    options and the USER clicks through to the source. Building a URL is not
    scraping and stores nothing.
  * If a Yelp Fusion API key is configured (YELP_API_KEY), the tool ALSO
    returns up to a few official review EXCERPTS — the only excerpts Yelp's API
    exposes — each with the required attribution and a link back to the source.
    Excerpts are returned to the user, never persisted.
  * Reviews are unverified user opinion and are NOT an input to the risk model.
    Every response carries that disclaimer so reviews never get read as a score.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

YELP_FUSION_BASE = "https://api.yelp.com/v3"
YELP_TIMEOUT_S = 12

# Disclaimer attached to every response — keeps third-party opinion visibly
# distinct from the model's risk score so neither the agent nor the user
# conflates them.
DISCLAIMER = (
    "Third-party reviews are unverified diner opinions, not inspection results. "
    "They are NOT part of the food-safety risk score."
)

# Diner-facing safety topics → the words we scan review text for. Mirrors the
# spirit of the model's keyword flags but lives here independently because this
# is presentation copy, not a model feature.
TOPIC_KEYWORDS: dict[str, list[str]] = {
    "cleanliness": [
        "dirty",
        "filthy",
        "unclean",
        "unsanitary",
        "grimy",
        "grease",
        "sticky",
        "mold",
        "mould",
        "smell",
        "smelly",
    ],
    "pests": [
        "rodent",
        "rat",
        "rats",
        "mice",
        "mouse",
        "roach",
        "roaches",
        "cockroach",
        "pest",
        "bug",
        "bugs",
        "fly",
        "flies",
        "vermin",
        "infest",
    ],
    "food_quality": [
        "undercooked",
        "raw",
        "spoiled",
        "stale",
        "expired",
        "old food",
        "frozen",
        "soggy",
        "bland",
    ],
    "illness": [
        "sick",
        "food poisoning",
        "poisoned",
        "ill",
        "nausea",
        "nauseous",
        "vomit",
        "vomiting",
        "diarrhea",
        "diarrhoea",
        "stomach",
    ],
}

# Human labels for each topic key (used in the agent-facing link text).
TOPIC_LABELS: dict[str, str] = {
    "cleanliness": "cleanliness",
    "pests": "rodents / pests",
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
        "address": str | None,     # street address, improves link/match quality
        "topics":  list[str]       # subset of TOPIC_KEYWORDS keys; empty = all
    }

    Returns:
    {
        "name": str,
        "topics": list[str],
        "review_links": list[{source, label, url}],
        "excerpts": list[{source, rating, text, matched_topics, url, attribution}],
        "excerpts_available": bool,   # true only when a review API is configured
        "disclaimer": str
    }
    """
    name: str = (event.get("name") or "").strip()
    address: str = (event.get("address") or "").strip()
    topics: list[str] = _resolve_topics(event.get("topics"))

    if not name:
        return {"error": "find_reviews requires a restaurant 'name'."}

    result: dict[str, Any] = {
        "name": name,
        "topics": topics,
        # Deep links always work — no credentials, no network call, nothing stored.
        "review_links": _build_review_links(name, address, topics),
        "excerpts": [],
        "excerpts_available": False,
        "disclaimer": DISCLAIMER,
    }

    # Optional enrichment: official Yelp Fusion excerpts when a key is present.
    excerpts = _yelp_excerpts(name, address, topics)
    if excerpts is not None:
        result["excerpts"] = excerpts
        result["excerpts_available"] = True

    return result


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


def _resolve_topics(raw: Any) -> list[str]:
    """Normalise the requested topics to known keys; empty/unknown → all topics."""
    if not raw:
        return list(TOPIC_KEYWORDS)
    if isinstance(raw, str):
        raw = [raw]
    keep = [t.strip().lower() for t in raw if t.strip().lower() in TOPIC_KEYWORDS]
    return keep or list(TOPIC_KEYWORDS)


def _topic_terms(topics: list[str]) -> str:
    """Short free-text term for the search query, e.g. 'cleanliness pests'."""
    return " ".join(TOPIC_LABELS[t].replace(" / ", " ") for t in topics)


def matched_topics(text: str, topics: list[str]) -> list[str]:
    """Return which of `topics` have a keyword present in `text` (case-insensitive)."""
    low = text.lower()
    hits: list[str] = []
    for topic in topics:
        if any(kw in low for kw in TOPIC_KEYWORDS[topic]):
            hits.append(topic)
    return hits


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
    google = "https://www.google.com/maps/search/" + urllib.parse.quote(where)
    web = "https://duckduckgo.com/?" + urllib.parse.urlencode(
        {"q": f"{where} reviews {terms}".strip()}
    )

    return [
        {"source": "Yelp", "label": f"Yelp reviews ({topic_label})", "url": yelp},
        {"source": "Google", "label": f"Google reviews ({topic_label})", "url": google},
        {"source": "Web", "label": f"Web search ({topic_label})", "url": web},
    ]


# ---------------------------------------------------------------------------
# Optional Yelp Fusion excerpts (official API, attributed, not stored)
# ---------------------------------------------------------------------------


def _yelp_excerpts(name: str, address: str, topics: list[str]) -> list[dict[str, Any]] | None:
    """
    Return up to a few official Yelp review excerpts for the business, each
    tagged with which requested topics it mentions. Returns None when no API
    key is configured (so the caller can mark excerpts unavailable rather than
    silently scraping). Network/credential errors degrade to None.
    """
    import os

    api_key = os.environ.get("YELP_API_KEY", "").strip()
    if not api_key:
        return None

    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        business_id = _yelp_match_business(name, address, headers)
        if not business_id:
            return []
        reviews = _yelp_get_reviews(business_id, headers)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        # The agent still has the deep links; treat enrichment as best-effort.
        return None

    excerpts: list[dict[str, Any]] = []
    for rv in reviews:
        text = rv.get("text", "")
        excerpts.append(
            {
                "source": "Yelp",
                "rating": rv.get("rating"),
                "text": text,
                "matched_topics": matched_topics(text, topics),
                "url": rv.get("url", ""),
                "attribution": "Review excerpt via Yelp Fusion API",
            }
        )
    return excerpts


def _yelp_match_business(name: str, address: str, headers: dict[str, str]) -> str | None:
    """Resolve a business id via Yelp's business-match endpoint (Chicago, IL)."""
    params = urllib.parse.urlencode(
        {
            "name": name,
            "address1": address,
            "city": "Chicago",
            "state": "IL",
            "country": "US",
            "limit": 1,
        }
    )
    data = _yelp_get(f"{YELP_FUSION_BASE}/businesses/matches?{params}", headers)
    businesses = data.get("businesses", [])
    return businesses[0]["id"] if businesses else None


def _yelp_get_reviews(business_id: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    """Fetch the review excerpts Yelp exposes for a business."""
    quoted = urllib.parse.quote(business_id)
    data = _yelp_get(f"{YELP_FUSION_BASE}/businesses/{quoted}/reviews?limit=3", headers)
    return data.get("reviews", [])


def _yelp_get(url: str, headers: dict[str, str]) -> dict[str, Any]:
    """GET a Yelp Fusion endpoint and return parsed JSON."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=YELP_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))
