"""Smoke + edge-case tests for the SODA loaders.

HTTP is mocked end-to-end — these tests run offline and finish in milliseconds.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from foodsafety.io.cache import load_or_fetch
from foodsafety.io.soda import _safe_dedupe, fetch_soda


def _mock_response(payload: list[dict]) -> MagicMock:
    """Build a stub `requests.Response` returning the given JSON payload."""
    mock = MagicMock()
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


# ---------------------------------------------------------------------------
# fetch_soda
# ---------------------------------------------------------------------------


def test_fetch_soda_returns_empty_dataframe_on_empty_response():
    with patch("foodsafety.io.soda.requests.get", return_value=_mock_response([])):
        result = fetch_soda("dummy-id", verbose=False)
    assert isinstance(result, pd.DataFrame)
    assert result.empty


def test_fetch_soda_concatenates_pages_until_short_page():
    # Two full pages of 2 rows, then a short page → loop should stop after the short page.
    pages = [
        [{"id": "1", "v": "a"}, {"id": "2", "v": "b"}],
        [{"id": "3", "v": "c"}, {"id": "4", "v": "d"}],
        [{"id": "5", "v": "e"}],  # short page = end
    ]
    responses = [_mock_response(p) for p in pages]
    with patch("foodsafety.io.soda.requests.get", side_effect=responses):
        result = fetch_soda("dummy-id", page_size=2, max_pages=10, verbose=False)
    assert len(result) == 5
    assert list(result["id"]) == ["1", "2", "3", "4", "5"]


# ---------------------------------------------------------------------------
# _safe_dedupe
# ---------------------------------------------------------------------------


def test_safe_dedupe_ignores_unhashable_dict_columns():
    # `location` is the SODA-style nested dict that breaks default drop_duplicates.
    df = pd.DataFrame(
        {
            "sr_number": ["A", "A", "B"],
            "name": ["x", "x", "y"],
            "location": [
                {"type": "Point", "coordinates": [-87.6, 41.9]},
                {"type": "Point", "coordinates": [-87.6, 41.9]},
                {"type": "Point", "coordinates": [-87.7, 41.8]},
            ],
        }
    )
    # Without a dedupe_on key, the helper detects `location` is unhashable and
    # falls back to the hashable subset.
    result = _safe_dedupe(df, verbose=False)
    assert len(result) == 2


def test_safe_dedupe_on_primary_key_is_fast_path():
    df = pd.DataFrame({"sr_number": ["A", "A", "B"], "junk": [1, 2, 3]})
    result = _safe_dedupe(df, dedupe_on="sr_number", verbose=False)
    assert len(result) == 2
    # Keeps the first occurrence by default.
    assert result.iloc[0]["junk"] == 1


# ---------------------------------------------------------------------------
# load_or_fetch caching
# ---------------------------------------------------------------------------


def test_load_or_fetch_hits_cache_on_second_call(tmp_path):
    cache_dir = tmp_path / "cache"
    call_count = {"n": 0}

    def fetch() -> pd.DataFrame:
        call_count["n"] += 1
        return pd.DataFrame({"x": [1, 2, 3]})

    first = load_or_fetch("toy", fetch, cache_dir=cache_dir, verbose=False)
    second = load_or_fetch("toy", fetch, cache_dir=cache_dir, verbose=False)

    assert call_count["n"] == 1, "fetch_fn should not be called on cache hit"
    pd.testing.assert_frame_equal(first, second)


def test_load_or_fetch_writes_parquet_on_miss(tmp_path):
    cache_dir = tmp_path / "cache"
    df = pd.DataFrame({"x": [10, 20]})
    load_or_fetch("toy", lambda: df, cache_dir=cache_dir, verbose=False)
    assert (cache_dir / "toy.parquet").exists()
