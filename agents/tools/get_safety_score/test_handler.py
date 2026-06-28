"""
Tests for the scores.json matcher in handler.py.

Covers the address-and-name disambiguation fix:
  1. Two establishments at the same normalised address map to the right
     license each (the shared-address bug — food courts, airports).
  2. A name that matches nothing in the address bucket returns None
     (no confident-wrong match).
  3. Store-number / punctuation normalisation ("Dunkin'" vs "DUNKIN #305").
  4. The index keeps every record at a shared address (no last-writer-wins).
"""

from __future__ import annotations

import json
import os
import sys
import types

# ---------------------------------------------------------------------------
# Path setup — allow running from the repo root or from this directory.
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# handler imports sagemaker_stub, which imports boto3. Provide a minimal stub
# so the module imports without the AWS SDK installed.
_boto3_stub = types.ModuleType("boto3")
sys.modules.setdefault("boto3", _boto3_stub)

from handler import (  # noqa: E402
    _fuzzy_lookup,
    _load_scores_index,
    _normalise_name,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Two distinct establishments sharing one airport-terminal address.
SHARED_ADDRESS = "11601 W TOUHY AVE"
RECORD_A = {"license_id": "LIC_A", "dba_name": "STARBUCKS #1138", "address": SHARED_ADDRESS}
RECORD_B = {"license_id": "LIC_B", "dba_name": "MCDONALD'S", "address": SHARED_ADDRESS}


def _index(*records: dict) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for r in records:
        # mirror the loader's keying without touching the lru_cache
        from handler import _normalise_address

        index.setdefault(_normalise_address(r["address"]), []).append(r)
    return index


# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------


def test_normalise_name_strips_store_number_and_punctuation():
    assert _normalise_name("Dunkin'") == "DUNKIN"
    assert _normalise_name("DUNKIN #305") == "DUNKIN"
    assert _normalise_name("McDonald's #1234") == "MCDONALDS"
    assert _normalise_name("  Joe & Sons,  Inc. ") == "JOE SONS INC"
    assert _normalise_name("") == ""


# ---------------------------------------------------------------------------
# Shared-address disambiguation (the core bug)
# ---------------------------------------------------------------------------


def test_shared_address_maps_each_name_to_correct_license():
    index = _index(RECORD_A, RECORD_B)

    starbucks = _fuzzy_lookup(SHARED_ADDRESS, "Starbucks", index)
    mcdonalds = _fuzzy_lookup(SHARED_ADDRESS, "McDonalds", index)

    assert starbucks is not None and starbucks["license_id"] == "LIC_A"
    assert mcdonalds is not None and mcdonalds["license_id"] == "LIC_B"


def test_name_not_in_bucket_returns_none():
    index = _index(RECORD_A, RECORD_B)
    # A completely different business at the same address must not borrow a score.
    assert _fuzzy_lookup(SHARED_ADDRESS, "Pizza Palace", index) is None


def test_empty_name_returns_none():
    index = _index(RECORD_A, RECORD_B)
    assert _fuzzy_lookup(SHARED_ADDRESS, "", index) is None


def test_store_number_does_not_block_match():
    index = _index(RECORD_A)
    # OSM "Starbucks" vs city "STARBUCKS #1138" should still match.
    match = _fuzzy_lookup(SHARED_ADDRESS, "Starbucks Coffee", index)
    assert match is not None and match["license_id"] == "LIC_A"


# ---------------------------------------------------------------------------
# Fuzzy address fall-through still works, then disambiguates by name
# ---------------------------------------------------------------------------


def test_fuzzy_address_then_name():
    index = _index(RECORD_A, RECORD_B)
    # Slightly different address string (expanded "AVENUE") should still resolve.
    match = _fuzzy_lookup("11601 W TOUHY AVENUE", "McDonald's", index)
    assert match is not None and match["license_id"] == "LIC_B"


# ---------------------------------------------------------------------------
# Index keeps every shared-address record (no last-writer-wins)
# ---------------------------------------------------------------------------


def test_loader_retains_all_shared_address_records(tmp_path, monkeypatch):
    payload = {"scores": [RECORD_A, RECORD_B]}
    p = tmp_path / "scores.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("SCORES_JSON_PATH", str(p))
    _load_scores_index.cache_clear()

    index = _load_scores_index()
    try:
        buckets = list(index.values())
        assert len(buckets) == 1  # one shared address
        assert len(buckets[0]) == 2  # both records retained
    finally:
        _load_scores_index.cache_clear()
