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
    assert "error" in handler({"name": "", "topics": []}, None)
