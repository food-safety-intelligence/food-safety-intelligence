"""
Tests for the food_safety_info tool — verifies the deterministic, offline parts:
  1. Every cited URL is https and on the curated ALLOWED_DOMAINS allow-list.
  2. Topic resolution matches by query text and by explicit topic list.
  3. Each topic entry carries a title, a non-empty summary, and >=1 source.
  4. Every response carries the education-only disclaimer.

These never hit the network — link resolution lives in the eval (--links).
"""

from __future__ import annotations

import os
import sys

# Allow running from the repo root or from this directory.
_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from handler import (  # noqa: E402
    _SOURCES,
    _TOPICS,
    DISCLAIMER,
    all_source_urls,
    handler,
    is_allowed_url,
)


def test_every_catalogue_url_is_allowed_and_https():
    # The whole point of the curated list: no link can come from outside it.
    for url in all_source_urls():
        assert url.startswith("https://"), url
        assert is_allowed_url(url), url


def test_is_allowed_url_rejects_offlist_and_http():
    assert not is_allowed_url("https://example.com/food")
    assert not is_allowed_url("http://www.cdc.gov/food-safety/")  # not https
    assert not is_allowed_url("https://notcdc.gov/food")  # suffix must be a real boundary
    assert is_allowed_url("https://www.cdc.gov/food-safety/about/index.html")
    assert is_allowed_url("https://data.cityofchicago.org/x")  # sub-domain of an allowed domain


def test_every_topic_has_title_summary_and_sources():
    for key, (title, summary, source_ids) in _TOPICS.items():
        assert title and summary, key
        assert source_ids, key
        # Every source id a topic references must exist in the catalogue.
        for sid in source_ids:
            assert sid in _SOURCES, f"{key} -> unknown source {sid}"


def test_query_matches_specific_pathogen():
    out = handler({"query": "how dangerous is listeria when pregnant?"}, None)
    assert "listeria" in out["topics"]
    # Pregnancy phrasing also pulls the at-risk topic.
    assert "at_risk_groups" in out["topics"]
    for entry in out["info"]:
        assert entry["summary"]
        assert all(is_allowed_url(s["url"]) for s in entry["sources"])
    assert out["disclaimer"] == DISCLAIMER


def test_stats_question_routes_to_overview():
    out = handler({"query": "how common is food poisoning in the US?"}, None)
    assert "overview" in out["topics"]


def test_explicit_topics_win_over_query():
    out = handler({"query": "anything", "topics": ["salmonella", "bogus"]}, None)
    assert out["topics"] == ["salmonella"]  # bogus dropped, query ignored


def test_unmatched_query_falls_back_to_defaults():
    out = handler({"query": "tell me about food safety generally"}, None)
    assert out["topics"] == ["overview", "prevention"]


def test_topic_cap():
    # Throw many pathogens at it; the response stays focused.
    out = handler(
        {"query": "salmonella listeria norovirus campylobacter e. coli chicago recalls"}, None
    )
    assert 1 <= len(out["topics"]) <= 4
