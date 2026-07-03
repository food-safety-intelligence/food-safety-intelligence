"""Tests for the SODA (Socrata) API loaders (``foodsafety.io.soda``).

The live HTTP is mocked — ``requests.get`` is patched and ``time.sleep`` is
stubbed — so the pagination / cursor / retry LOGIC is exercised without touching
the network or waiting on real backoff. What's pinned down:

  - ``fetch_soda`` advances ``$offset`` per page and stops on a short page.
  - ``fetch_soda_keyset`` advances the cursor across pages and dedupes the rows
    re-fetched at the ``>=`` page boundary.
  - ``_request_with_retry`` retries transient timeouts/connection errors but
    NOT HTTP 4xx/5xx, and gives up after the retry budget.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pandas as pd
import pytest
import requests

from foodsafety.io import soda


def _resp(rows: list[dict]) -> Mock:
    """A fake requests.Response: ``.json()`` returns rows, ``raise_for_status`` is a no-op."""
    r = Mock()
    r.json.return_value = rows
    r.raise_for_status.return_value = None
    return r


@patch("foodsafety.io.soda.time.sleep")
@patch("foodsafety.io.soda.requests.get")
def test_fetch_soda_paginates_and_stops_on_short_page(mock_get, _sleep):
    mock_get.side_effect = [
        _resp([{"id": "a"}, {"id": "b"}]),  # full page (== page_size) -> continue
        _resp([{"id": "c"}]),  # short page -> stop
    ]
    out = soda.fetch_soda("ds", page_size=2, verbose=False)

    assert list(out["id"]) == ["a", "b", "c"]
    assert mock_get.call_count == 2
    # The second request advanced the offset by one page.
    assert mock_get.call_args_list[1].kwargs["params"]["$offset"] == 2


@patch("foodsafety.io.soda.time.sleep")
@patch("foodsafety.io.soda.requests.get")
def test_fetch_soda_empty_first_page_returns_empty(mock_get, _sleep):
    mock_get.side_effect = [_resp([])]
    out = soda.fetch_soda("ds", page_size=2, verbose=False)

    assert out.empty
    assert mock_get.call_count == 1


@patch("foodsafety.io.soda.time.sleep")
@patch("foodsafety.io.soda.requests.get")
def test_fetch_soda_keyset_advances_cursor_and_dedupes(mock_get, _sleep):
    # Each page is full (== page_size) until the last; the cursor's `>=` clause
    # re-fetches the boundary row, which dedupe must drop.
    mock_get.side_effect = [
        _resp(
            [{"created_date": "2019-01-01", "id": "a"}, {"created_date": "2019-01-02", "id": "b"}]
        ),
        _resp(
            [{"created_date": "2019-01-02", "id": "b"}, {"created_date": "2019-01-03", "id": "c"}]
        ),
        _resp([{"created_date": "2019-01-03", "id": "c"}]),  # short -> stop
    ]
    out = soda.fetch_soda_keyset(
        "ds",
        cursor_col="created_date",
        cursor_start="2019-01-01",
        page_size=2,
        dedupe_on="id",
        verbose=False,
    )

    # Boundary re-fetches of 'b' and 'c' are deduped away.
    assert sorted(out["id"]) == ["a", "b", "c"]
    # The cursor advanced to each page's last value.
    wheres = [c.kwargs["params"]["$where"] for c in mock_get.call_args_list]
    assert "2019-01-01" in wheres[0]
    assert "2019-01-02" in wheres[1]
    assert "2019-01-03" in wheres[2]


@patch("foodsafety.io.soda.time.sleep")
@patch("foodsafety.io.soda.requests.get")
def test_request_with_retry_returns_response_on_success(mock_get, _sleep):
    resp = _resp([{"id": "a"}])
    mock_get.return_value = resp

    got, elapsed = soda._request_with_retry("u", {}, 10, 3, False, 0)

    assert got is resp
    assert isinstance(elapsed, float)
    assert mock_get.call_count == 1


@patch("foodsafety.io.soda.time.sleep")
@patch("foodsafety.io.soda.requests.get")
def test_request_with_retry_retries_transient_then_succeeds(mock_get, sleep):
    resp = _resp([])
    mock_get.side_effect = [requests.Timeout("boom"), resp]

    got, _ = soda._request_with_retry("u", {}, 10, 3, False, 0)

    assert got is resp
    assert mock_get.call_count == 2
    assert sleep.call_count == 1  # backoff once, between the two attempts


@patch("foodsafety.io.soda.time.sleep")
@patch("foodsafety.io.soda.requests.get")
def test_request_with_retry_gives_up_after_budget(mock_get, _sleep):
    mock_get.side_effect = requests.ConnectionError("down")

    with pytest.raises(requests.ConnectionError):
        soda._request_with_retry("u", {}, 10, 2, False, 0)
    assert mock_get.call_count == 2  # exhausted the budget


@patch("foodsafety.io.soda.time.sleep")
@patch("foodsafety.io.soda.requests.get")
def test_request_with_retry_does_not_retry_http_error(mock_get, _sleep):
    resp = Mock()
    resp.raise_for_status.side_effect = requests.HTTPError("404")
    mock_get.return_value = resp

    with pytest.raises(requests.HTTPError):
        soda._request_with_retry("u", {}, 10, 3, False, 0)
    assert mock_get.call_count == 1  # 4xx/5xx are a request error, not retried


@patch("foodsafety.io.soda.time.sleep")
@patch("foodsafety.io.soda.requests.get")
def test_fetch_soda_passes_soql_params(mock_get, _sleep):
    mock_get.side_effect = [_resp([{"id": "a"}])]
    soda.fetch_soda("ds", where="x > 1", select="id", order="id", page_size=2, verbose=False)

    p = mock_get.call_args_list[0].kwargs["params"]
    assert p["$where"] == "x > 1"
    assert p["$select"] == "id"
    assert p["$order"] == "id"


@patch("foodsafety.io.soda.time.sleep")
@patch("foodsafety.io.soda.requests.get")
def test_fetch_soda_keyset_applies_where_extra(mock_get, _sleep):
    mock_get.side_effect = [_resp([{"created_date": "2019-01-01", "id": "a"}])]
    soda.fetch_soda_keyset(
        "ds",
        cursor_col="created_date",
        cursor_start="2019-01-01",
        where_extra="kind='x'",
        page_size=2,
        verbose=False,
    )

    where = mock_get.call_args_list[0].kwargs["params"]["$where"]
    assert "kind='x'" in where
    assert "created_date >= '2019-01-01'" in where


@patch("foodsafety.io.soda.time.sleep")
@patch("foodsafety.io.soda.requests.get")
def test_fetch_soda_keyset_applies_select(mock_get, _sleep):
    # select lets the caller request Socrata system columns (e.g. ":id") that
    # aren't returned by default.
    mock_get.side_effect = [_resp([{"created_date": "2019-01-01", ":id": "row-a"}])]
    soda.fetch_soda_keyset(
        "ds",
        cursor_col="created_date",
        cursor_start="2019-01-01",
        select="*,:id",
        page_size=2,
        verbose=False,
    )

    assert mock_get.call_args_list[0].kwargs["params"]["$select"] == "*,:id"


@patch("foodsafety.io.soda.time.sleep")
@patch("foodsafety.io.soda.requests.get")
def test_fetch_soda_keyset_writes_and_cleans_shards(mock_get, _sleep, tmp_path):
    # With shard_dir set, each page is persisted as a parquet shard and the final
    # result is read back from those shards; on a clean exit the shards are removed.
    mock_get.side_effect = [
        _resp(
            [{"created_date": "2019-01-01", "id": "a"}, {"created_date": "2019-01-02", "id": "b"}]
        ),
        _resp([{"created_date": "2019-01-03", "id": "c"}]),  # short -> stop
    ]
    out = soda.fetch_soda_keyset(
        "ds",
        cursor_col="created_date",
        cursor_start="2019-01-01",
        page_size=2,
        shard_dir=str(tmp_path),
        dedupe_on="id",
        verbose=False,
    )

    assert sorted(out["id"]) == ["a", "b", "c"]
    assert list(tmp_path.glob("page_*.parquet")) == []  # cleaned up on success


@patch("foodsafety.io.soda.time.sleep")
@patch("foodsafety.io.soda.requests.get")
def test_fetch_soda_keyset_resumes_from_existing_shard(mock_get, _sleep, tmp_path):
    from foodsafety.io import storage

    # A shard left behind by an interrupted prior run.
    storage.write_parquet(
        pd.DataFrame({"created_date": ["2019-01-01"], "id": ["a"]}),
        str(tmp_path / "page_0000.parquet"),
        index=False,
    )
    mock_get.side_effect = [_resp([{"created_date": "2019-01-02", "id": "b"}])]  # short -> stop

    out = soda.fetch_soda_keyset(
        "ds",
        cursor_col="created_date",
        cursor_start="2019-01-01",
        page_size=2,
        shard_dir=str(tmp_path),
        dedupe_on="id",
        verbose=False,
    )

    assert sorted(out["id"]) == ["a", "b"]
    # Resumed from the shard's last cursor — only the continuation page was fetched.
    assert mock_get.call_count == 1


def test_safe_dedupe_drops_duplicate_rows():
    df = pd.DataFrame({"id": ["a", "a", "b"], "v": [1, 1, 2]})
    assert len(soda._safe_dedupe(df, verbose=False)) == 2


def test_safe_dedupe_handles_unhashable_columns():
    # Socrata's `location` arrives as a dict; plain drop_duplicates would raise
    # "unhashable type: 'dict'", so dedupe falls back to the hashable columns.
    df = pd.DataFrame({"id": ["a", "a"], "location": [{"x": 1}, {"x": 1}]})
    assert len(soda._safe_dedupe(df, verbose=False)) == 1
