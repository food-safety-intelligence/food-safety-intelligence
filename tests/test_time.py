"""Tests for the chronological splitter.

These tests exist because CLAUDE.md treats chronological splitting as the
single most important defensibility property of the model. A future teammate
who modifies the splitter should run these and not break them.
"""

from __future__ import annotations

import pandas as pd
import pytest

from foodsafety.utils.time import summarize, temporal_split


def _df(dates: list[str], **extra) -> pd.DataFrame:
    df = pd.DataFrame({"inspection_date": pd.to_datetime(dates)})
    for k, v in extra.items():
        df[k] = v
    return df


# ---------------------------------------------------------------------------
# Core split semantics
# ---------------------------------------------------------------------------


def test_split_partitions_all_rows_exactly_once():
    df = _df(
        ["2019-01-01", "2020-06-15", "2022-03-01", "2024-12-31", "2025-09-30"]
    )
    s = temporal_split(df, train_end="2023-01-01", val_end="2025-01-01")
    assert len(s.train) + len(s.val) + len(s.test) == len(df)
    # No row is in two splits — check via the row indices being disjoint.
    indices = set(s.train.index) | set(s.val.index) | set(s.test.index)
    assert len(indices) == len(df)


def test_train_strictly_before_train_end():
    df = _df(["2022-12-31", "2023-01-01"])
    s = temporal_split(df, train_end="2023-01-01", val_end="2024-01-01")
    # Row dated 2022-12-31 → train; row dated 2023-01-01 → val (NOT train).
    assert list(s.train["inspection_date"]) == [pd.Timestamp("2022-12-31")]
    assert list(s.val["inspection_date"]) == [pd.Timestamp("2023-01-01")]
    assert len(s.test) == 0


def test_val_strictly_before_val_end():
    df = _df(["2024-12-31", "2025-01-01"])
    s = temporal_split(df, train_end="2024-01-01", val_end="2025-01-01")
    # Row dated 2024-12-31 → val; row dated 2025-01-01 → test (NOT val).
    assert list(s.val["inspection_date"]) == [pd.Timestamp("2024-12-31")]
    assert list(s.test["inspection_date"]) == [pd.Timestamp("2025-01-01")]


def test_split_preserves_other_columns():
    df = _df(["2019-06-01", "2024-06-01"], y=[0, 1], facility=["A", "B"])
    s = temporal_split(df, train_end="2024-01-01", val_end="2025-01-01")
    assert list(s.train.columns) == list(df.columns)
    assert s.train["y"].tolist() == [0]
    assert s.train["facility"].tolist() == ["A"]
    assert s.val["y"].tolist() == [1]


def test_split_does_not_mutate_input():
    df = _df(["2019-06-01", "2024-06-01"])
    before = df.copy()
    temporal_split(df, train_end="2024-01-01", val_end="2025-01-01")
    pd.testing.assert_frame_equal(df, before)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def test_val_end_must_be_strictly_after_train_end():
    df = _df(["2020-01-01"])
    with pytest.raises(ValueError, match="strictly after"):
        temporal_split(df, train_end="2024-01-01", val_end="2024-01-01")
    with pytest.raises(ValueError, match="strictly after"):
        temporal_split(df, train_end="2024-01-01", val_end="2023-01-01")


def test_missing_date_col_raises():
    df = pd.DataFrame({"some_other_col": [1, 2]})
    with pytest.raises(ValueError, match="date_col"):
        temporal_split(df, train_end="2024-01-01", val_end="2025-01-01")


# ---------------------------------------------------------------------------
# Empty splits
# ---------------------------------------------------------------------------


def test_empty_input_returns_three_empty_splits():
    df = _df([])
    s = temporal_split(df, train_end="2024-01-01", val_end="2025-01-01")
    assert len(s.train) == 0
    assert len(s.val) == 0
    assert len(s.test) == 0


def test_cutoffs_stored_on_split():
    df = _df(["2020-01-01"])
    s = temporal_split(df, train_end="2024-01-01", val_end="2025-06-30")
    assert s.train_end == pd.Timestamp("2024-01-01")
    assert s.val_end == pd.Timestamp("2025-06-30")


# ---------------------------------------------------------------------------
# summarize() helper
# ---------------------------------------------------------------------------


def test_summarize_basic():
    df = _df(["2020-01-01", "2020-06-01", "2020-12-31"], y=[0, 1, 1])
    s = summarize(df, label_col="y")
    assert s.rows == 3
    assert s.date_min == pd.Timestamp("2020-01-01")
    assert s.date_max == pd.Timestamp("2020-12-31")
    assert s.positive_rate == pytest.approx(2 / 3)


def test_summarize_empty_returns_nones():
    s = summarize(_df([]))
    assert s.rows == 0
    assert s.date_min is None
    assert s.positive_rate is None


def test_summarize_without_label_col():
    df = _df(["2020-01-01"], y=[0])
    s = summarize(df)  # no label_col arg
    assert s.positive_rate is None
