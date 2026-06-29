"""Tests for the incremental ingestion module."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from foodsafety.config import DATASETS, INGEST_SPECS, LOOKBACK_DAYS, DatasetSpec
from foodsafety.ingest import cursor_start, ingest_dataset, upsert, watermark

# ---------------------------------------------------------------------------
# INGEST_SPECS coverage
# ---------------------------------------------------------------------------


def test_ingest_specs_cover_all_datasets():
    assert set(INGEST_SPECS) == set(DATASETS)
    for name, spec in INGEST_SPECS.items():
        assert spec.dataset_id == DATASETS[name]
        assert spec.cursor_col
        assert spec.pk
        assert spec.start


def test_lookback_days_positive():
    assert LOOKBACK_DAYS > 0


# ---------------------------------------------------------------------------
# watermark
# ---------------------------------------------------------------------------


def test_watermark_returns_max_cursor():
    df = pd.DataFrame({"inspection_date": ["2024-01-01", "2025-06-15", "2023-03-10"]})
    assert watermark(df, "inspection_date") == "2025-06-15"


def test_watermark_returns_none_on_empty():
    assert watermark(pd.DataFrame(), "inspection_date") is None


def test_watermark_returns_none_when_column_missing():
    df = pd.DataFrame({"other_col": [1, 2]})
    assert watermark(df, "inspection_date") is None


def test_watermark_returns_none_when_all_na():
    df = pd.DataFrame({"inspection_date": [None, None]})
    assert watermark(df, "inspection_date") is None


# ---------------------------------------------------------------------------
# cursor_start
# ---------------------------------------------------------------------------


def test_cursor_start_with_lookback():
    spec = DatasetSpec("x", "d", "pk", "2010-01-01T00:00:00")
    result = cursor_start("2025-06-15T00:00:00", 90, spec)
    assert result == "2025-03-17T00:00:00"


def test_cursor_start_without_watermark_falls_back_to_spec():
    spec = DatasetSpec("x", "d", "pk", "2010-01-01T00:00:00")
    assert cursor_start(None, 90, spec) == "2010-01-01T00:00:00"


# ---------------------------------------------------------------------------
# upsert
# ---------------------------------------------------------------------------


def test_upsert_dedupes_on_pk_keeps_latest():
    existing = pd.DataFrame({"id": ["a", "b"], "val": [1, 2]})
    new = pd.DataFrame({"id": ["b", "c"], "val": [20, 30]})
    result = upsert(existing, new, "id")
    assert len(result) == 3
    assert result.loc[result["id"] == "b", "val"].iloc[0] == 20


def test_upsert_on_empty_existing():
    new = pd.DataFrame({"id": ["a", "b"], "val": [1, 2]})
    result = upsert(pd.DataFrame(), new, "id")
    assert len(result) == 2


def test_upsert_dedupes_within_new():
    new = pd.DataFrame({"id": ["a", "a"], "val": [1, 2]})
    result = upsert(pd.DataFrame(), new, "id")
    assert len(result) == 1
    assert result.iloc[0]["val"] == 2


# ---------------------------------------------------------------------------
# ingest_dataset (integration, mocked IO + network)
# ---------------------------------------------------------------------------


@patch("foodsafety.ingest.storage")
@patch("foodsafety.ingest.fetch_soda_keyset")
def test_ingest_dataset_incremental_flow(mock_fetch, mock_storage):
    spec = DatasetSpec("test-id", "date", "pk", "2010-01-01T00:00:00")

    existing = pd.DataFrame({"pk": ["a", "b"], "date": ["2025-01-01", "2025-03-01"], "v": [1, 2]})
    new_rows = pd.DataFrame({"pk": ["b", "c"], "date": ["2025-06-01", "2025-06-10"], "v": [20, 30]})

    mock_storage.exists.return_value = True
    mock_storage.read_parquet.return_value = existing
    mock_storage.join.side_effect = lambda *args: "/".join(str(a) for a in args)
    mock_fetch.return_value = new_rows

    result = ingest_dataset("test", spec, lookback_days=90, verbose=False)

    assert len(result) == 3
    assert result.loc[result["pk"] == "b", "v"].iloc[0] == 20

    mock_fetch.assert_called_once()
    call_kwargs = mock_fetch.call_args[1]
    assert call_kwargs["dataset_id"] == "test-id"
    assert call_kwargs["cursor_col"] == "date"
    assert call_kwargs["cursor_start"] == "2024-12-01T00:00:00"

    mock_storage.write_parquet.assert_called_once()
    mock_storage.copy.assert_called_once()
    mock_storage.delete.assert_called_once()


@patch("foodsafety.ingest.storage")
@patch("foodsafety.ingest.fetch_soda_keyset")
def test_ingest_dataset_first_run_uses_spec_start(mock_fetch, mock_storage):
    spec = DatasetSpec("test-id", "date", "pk", "2010-01-01T00:00:00")

    mock_storage.exists.return_value = False
    mock_storage.join.side_effect = lambda *args: "/".join(str(a) for a in args)
    mock_fetch.return_value = pd.DataFrame({"pk": ["a"], "date": ["2025-01-01"], "v": [1]})

    result = ingest_dataset("test", spec, verbose=False)

    assert len(result) == 1
    call_kwargs = mock_fetch.call_args[1]
    assert call_kwargs["cursor_start"] == "2010-01-01T00:00:00"


@patch("foodsafety.ingest.storage")
@patch("foodsafety.ingest.fetch_soda_keyset")
def test_ingest_dataset_no_new_rows_returns_existing(mock_fetch, mock_storage):
    spec = DatasetSpec("test-id", "date", "pk", "2010-01-01T00:00:00")

    existing = pd.DataFrame({"pk": ["a"], "date": ["2025-01-01"], "v": [1]})
    mock_storage.exists.return_value = True
    mock_storage.read_parquet.return_value = existing
    mock_storage.join.side_effect = lambda *args: "/".join(str(a) for a in args)
    mock_fetch.return_value = pd.DataFrame()

    result = ingest_dataset("test", spec, verbose=False)

    pd.testing.assert_frame_equal(result, existing)
    mock_storage.write_parquet.assert_not_called()


@patch("foodsafety.ingest.storage")
@patch("foodsafety.ingest.fetch_soda_keyset")
def test_ingest_dataset_passes_select_for_system_columns(mock_fetch, mock_storage):
    spec = DatasetSpec("test-id", "date", ":id", "2010-01-01T00:00:00", select=":id,*")

    mock_storage.exists.return_value = False
    mock_storage.join.side_effect = lambda *args: "/".join(str(a) for a in args)
    mock_fetch.return_value = pd.DataFrame({":id": ["r1"], "date": ["2025-01-01"]})

    ingest_dataset("test", spec, verbose=False)

    call_kwargs = mock_fetch.call_args[1]
    assert call_kwargs["select"] == ":id,*"
