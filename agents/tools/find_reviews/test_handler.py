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
    assert sources == {"Yelp", "Google", "Web"}
    assert all(link["url"].startswith("http") for link in out["review_links"])
    assert out["disclaimer"] == DISCLAIMER


def test_handler_requires_name():
    out = handler({"name": "", "topics": []}, None)
    assert out["error"]
    assert out["reason"] == "missing_name"


def test_links_percent_encode_special_chars():
    # Query-significant characters from the name must be percent-encoded so they
    # can't inject params or path segments — in the DDG ?q= searches AND the
    # Google Maps path.
    out = handler({"name": "Joe's & Co / Café ?q=evil", "address": "Chicago, IL"}, None)
    urls = {link["source"]: link["url"] for link in out["review_links"]}
    for url in (urls["Yelp"], urls["Web"]):
        q = url.split("?q=", 1)[1]
        assert " " not in q and "/" not in q and "& Co" not in q
    # Google is a direct Maps search; the place string is encoded in the path.
    tail = urls["Google"].split("/maps/search/", 1)[1]
    assert " " not in tail and "/" not in tail and "& Co" not in tail


def test_topic_scoping_in_urls():
    # A specific topic scopes Yelp (site: search) + Web; Google is a direct,
    # general Maps link. All-topics uses a concise "food safety" term.
    pests = {
        link["source"]: link["url"]
        for link in handler(
            {"name": "Lou Malnati's", "address": "Chicago, IL", "topics": ["pests"]}, None
        )["review_links"]
    }
    assert "site%3Ayelp.com" in pests["Yelp"] and "rodents" in pests["Yelp"]
    assert pests["Google"].startswith("https://www.google.com/maps/search/")
    assert "rodents" in pests["Web"]
    allt = {
        link["source"]: link["url"]
        for link in handler({"name": "Lou Malnati's", "address": "Chicago, IL"}, None)[
            "review_links"
        ]
    }
    assert "food+safety" in allt["Web"] and "droppings" not in allt["Web"]
