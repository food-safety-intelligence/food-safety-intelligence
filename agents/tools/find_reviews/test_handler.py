"""
Tests for the find_reviews tool — verifies the deterministic, offline parts:
  1. Deep links are always built (no network, no credentials needed).
  2. Topic resolution normalises / defaults correctly.
  3. Every response carries the not-part-of-the-score disclaimer.

These never hit the network: link building is pure string work.
"""

from __future__ import annotations

import os
import sys

# Allow running from the repo root or from this directory.
_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from handler import (  # noqa: E402
    DISCLAIMER,
    TOPIC_LABELS,
    _resolve_topics,
    handler,
)


def test_resolve_topics_defaults_to_all():
    assert _resolve_topics(None) == list(TOPIC_LABELS)
    assert _resolve_topics([]) == list(TOPIC_LABELS)
    assert _resolve_topics(["bogus"]) == list(TOPIC_LABELS)


def test_resolve_topics_filters_known():
    assert _resolve_topics(["pests", "bogus"]) == ["pests"]
    assert _resolve_topics("cleanliness") == ["cleanliness"]


def test_handler_builds_links():
    out = handler({"name": "Joe's Diner", "address": "123 Main St", "topics": ["pests"]}, None)

    assert out["name"] == "Joe's Diner"
    assert out["topics"] == ["pests"]
    sources = {link["source"] for link in out["review_links"]}
    assert sources == {"Yelp", "Google", "TripAdvisor"}
    assert all(link["url"].startswith("http") for link in out["review_links"])
    assert out["disclaimer"] == DISCLAIMER


def test_handler_requires_name():
    out = handler({"name": "", "topics": []}, None)
    assert out["error"]
    assert out["reason"] == "missing_name"


def test_links_percent_encode_special_chars():
    # Query-significant characters from the name must be percent/plus-encoded so
    # they can't inject params or path segments into any source's search URL.
    out = handler({"name": "Joe's & Co / Café ?q=evil", "address": "Chicago, IL"}, None)
    urls = {link["source"]: link["url"] for link in out["review_links"]}
    for src in ("Yelp", "Google", "TripAdvisor"):
        query = urls[src].split("?", 1)[1]
        assert " " not in query  # spaces are '+'-encoded
        assert "/" not in query  # the '/' in the name must not survive as a path sep
        assert "& Co" not in query  # the literal '&' from the name must be encoded


def test_links_go_direct_to_each_source():
    # Each link points at its named source's own domain (not a search-engine
    # detour). Links are general — not topic-scoped — so a requested topic's
    # synonyms (e.g. "rodents") must not leak into any URL.
    out = handler({"name": "Lou Malnati's", "address": "Chicago, IL", "topics": ["pests"]}, None)
    urls = {link["source"]: link["url"] for link in out["review_links"]}
    assert urls["Yelp"].startswith("https://www.yelp.com/search?")
    assert urls["Google"].startswith("https://www.google.com/maps/search/?api=1")
    assert urls["TripAdvisor"].startswith("https://www.tripadvisor.com/Search?")
    assert all("rodents" not in link["url"] for link in out["review_links"])
