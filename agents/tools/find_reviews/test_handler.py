"""
Tests for the find_reviews tool — verifies the deterministic, offline parts:
  1. Deep links are always built (no network, no API key needed).
  2. Topic resolution normalises / defaults correctly.
  3. matched_topics scans review text for the right safety keywords.
  4. With no YELP_API_KEY, excerpts are empty and flagged unavailable.
  5. Every response carries the not-part-of-the-score disclaimer.

These never hit the network: the Yelp path is only exercised through env-var
absence, and link building is pure string work.
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
    TOPIC_KEYWORDS,
    _resolve_topics,
    handler,
    matched_topics,
)


def test_resolve_topics_defaults_to_all():
    assert _resolve_topics(None) == list(TOPIC_KEYWORDS)
    assert _resolve_topics([]) == list(TOPIC_KEYWORDS)
    assert _resolve_topics(["bogus"]) == list(TOPIC_KEYWORDS)


def test_resolve_topics_filters_known():
    assert _resolve_topics(["pests", "bogus"]) == ["pests"]
    assert _resolve_topics("cleanliness") == ["cleanliness"]


def test_matched_topics_finds_keywords():
    text = "There was a rat in the dining room and the floor was filthy."
    hits = matched_topics(text, ["pests", "cleanliness", "illness"])
    assert "pests" in hits
    assert "cleanliness" in hits
    assert "illness" not in hits


def test_matched_topics_case_insensitive():
    assert matched_topics("ROACHES everywhere", ["pests"]) == ["pests"]


def test_handler_builds_links_without_credentials(monkeypatch):
    monkeypatch.delenv("YELP_API_KEY", raising=False)
    out = handler({"name": "Joe's Diner", "address": "123 Main St", "topics": ["pests"]}, None)

    assert out["name"] == "Joe's Diner"
    assert out["topics"] == ["pests"]
    sources = {link["source"] for link in out["review_links"]}
    assert sources == {"Yelp", "Google", "Web"}
    assert all(link["url"].startswith("http") for link in out["review_links"])
    # No key configured → no excerpts, explicitly flagged.
    assert out["excerpts"] == []
    assert out["excerpts_available"] is False
    assert out["disclaimer"] == DISCLAIMER


def test_handler_requires_name():
    assert "error" in handler({"name": "", "topics": []}, None)
