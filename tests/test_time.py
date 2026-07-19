"""Tests for the chronological splitter.

These tests exist because CLAUDE.md treats chronological splitting as the
single most important defensibility property of the model. A future teammate
who modifies the splitter should run these and not break them.
"""

from __future__ import annotations

import pandas as pd
import pytest

from foodsafety.utils.time import (
    expanding_year_folds,
    split_window,
    summarize,
    temporal_split,
)


def _df(dates: list[str], **extra) -> pd.DataFrame:
    df = pd.DataFrame({"inspection_date": pd.to_datetime(dates)})
    for k, v in extra.items():
        df[k] = v
    return df


# ---------------------------------------------------------------------------
# Core split semantics
# ---------------------------------------------------------------------------


def test_split_partitions_all_rows_exactly_once():
    df = _df(["2019-01-01", "2020-06-15", "2022-03-01", "2024-12-31", "2025-09-30"])
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
# expanding_year_folds() — inner-loop CV with embargo
# ---------------------------------------------------------------------------


def test_expanding_year_folds_one_fold_per_year_after_first():
    # 2019 has no fold (earliest year, no embargoed history before it);
    # 2020/2021/2022 each get a val fold.
    df = _df([f"{y}-06-01" for y in (2019, 2020, 2021, 2022)])
    folds = expanding_year_folds(df)
    assert len(folds) == 3


def test_expanding_year_folds_val_is_exactly_one_year():
    df = _df(["2019-06-01", "2020-03-01", "2020-09-01", "2021-06-01"])
    folds = expanding_year_folds(df)
    # First fold validates on 2020 → both 2020 rows, nothing else.
    _, val_idx = folds[0]
    val_years = pd.to_datetime(df.iloc[val_idx]["inspection_date"]).dt.year.tolist()
    assert val_years == [2020, 2020]


def test_expanding_year_folds_embargo_excludes_tail_of_train():
    # A train anchor inside the 180-day embargo before the val year must be
    # excluded; one comfortably before it must be kept.
    df = _df(
        [
            "2019-01-15",  # well before embargo → train
            "2019-10-01",  # within 180d of 2020-01-01 → embargoed out
            "2020-06-01",  # the validation year
        ]
    )
    folds = expanding_year_folds(df, embargo_days=180)
    train_idx, val_idx = folds[0]
    train_dates = pd.to_datetime(df.iloc[train_idx]["inspection_date"]).tolist()
    assert train_dates == [pd.Timestamp("2019-01-15")]
    assert pd.to_datetime(df.iloc[val_idx]["inspection_date"]).tolist() == [
        pd.Timestamp("2020-06-01")
    ]


def test_expanding_year_folds_train_expands_and_never_overlaps_val():
    df = _df(["2019-01-01", "2020-01-01", "2021-01-01", "2022-01-01", "2023-01-01"])
    folds = expanding_year_folds(df)
    prev_train = -1
    for train_idx, val_idx in folds:
        # train grows (or holds) each fold
        assert len(train_idx) >= prev_train
        prev_train = len(train_idx)
        # train and val never share a row
        assert not (set(train_idx) & set(val_idx))


def test_expanding_year_folds_empty_input():
    assert expanding_year_folds(_df([])) == []


# ---------------------------------------------------------------------------
# split_window() — date range + count for the methodology `windows` block
# ---------------------------------------------------------------------------


def test_split_window_reports_range_and_count():
    w = split_window(_df(["2024-03-15", "2024-01-02", "2024-12-31"]))
    assert w == {"start": "2024-01-02", "end": "2024-12-31", "n": 3}


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
