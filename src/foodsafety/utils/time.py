"""Chronological train/val/test splitter.

CLAUDE.md is explicit: never ``train_test_split(shuffle=True)`` on this data.
Random shuffling within a time-series leaks future information into training
and inflates eval metrics. This module is the ONLY allowed split helper.

The split is deliberately a function — not a sklearn ``BaseEstimator`` /
``Splitter`` — because we want the cutoff dates recorded in model metadata
(``data/models/<name>_metadata.json``). Embedding the cutoffs in a Splitter
class would hide them.

For inner-loop cross-validation during hyperparameter search, use
``sklearn.model_selection.TimeSeriesSplit`` ON THE TRAIN SUBSET ONLY. Never
cross-validate across the train/val boundary; that defeats the chronological
guarantee this module exists to enforce.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
import pandas as pd


class TemporalSplit(NamedTuple):
    """Three chronologically-ordered DataFrames + the cutoffs used to derive them.

    Keeping the cutoffs alongside the data lets us log them into model
    metadata without callers having to remember the values they passed.
    """

    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame
    train_end: pd.Timestamp
    val_end: pd.Timestamp


def temporal_split(
    df: pd.DataFrame,
    *,
    date_col: str = "inspection_date",
    train_end: str | pd.Timestamp,
    val_end: str | pd.Timestamp,
) -> TemporalSplit:
    """Three-way chronological split.

    Convention (right-exclusive on the left split boundary, right-exclusive
    on the middle boundary, left-inclusive on the test boundary):

        train: ``df[date_col] < train_end``
        val:   ``train_end <= df[date_col] < val_end``
        test:  ``df[date_col] >= val_end``

    Args:
        df: input frame. Not mutated.
        date_col: name of the datetime column to split on. Defaults to
            ``inspection_date`` (the standard anchor in this project).
        train_end: first date that is NOT in train.
        val_end: first date that is NOT in val.

    Raises:
        ValueError: if ``val_end <= train_end`` (would produce an empty val)
            or if ``date_col`` is missing.
    """
    if date_col not in df.columns:
        raise ValueError(f"date_col {date_col!r} not in DataFrame columns")

    train_end_ts = pd.Timestamp(train_end)
    val_end_ts = pd.Timestamp(val_end)
    if val_end_ts <= train_end_ts:
        raise ValueError(
            f"val_end ({val_end_ts.date()}) must be strictly after "
            f"train_end ({train_end_ts.date()}); otherwise val is empty."
        )

    dates = pd.to_datetime(df[date_col])

    train_mask = dates < train_end_ts
    val_mask = (dates >= train_end_ts) & (dates < val_end_ts)
    test_mask = dates >= val_end_ts

    return TemporalSplit(
        train=df.loc[train_mask].copy(),
        val=df.loc[val_mask].copy(),
        test=df.loc[test_mask].copy(),
        train_end=train_end_ts,
        val_end=val_end_ts,
    )


def expanding_year_folds(
    df: pd.DataFrame,
    *,
    date_col: str = "inspection_date",
    embargo_days: int = 180,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding-window cross-validation folds by calendar year, with an embargo.

    Intended for the inner hyperparameter / calibration loop on the TRAIN
    subset only (never across the train/val/test boundary — that defeats the
    chronological guarantee ``temporal_split`` exists to enforce).

    For each validation year Y (every distinct year after the earliest one
    present), the fold is::

        val   = rows whose date falls in calendar year Y
        train = rows whose date is < (Y-01-01 minus ``embargo_days``)

    The embargo drops the tail of train whose forward label window overlaps the
    validation year. The label is ``*_next_180d``: an anchor inspected within
    180 days of the year boundary "sees" outcomes that land inside the
    validation period, so without the embargo the CV score is optimistic.
    Quarterly folds are too small at this dataset's ~10% prevalence, hence
    full-year folds. ``train`` expands each fold (all history before the
    embargoed boundary), so later folds train on strictly more data.

    Args:
        df: input frame. Not mutated.
        date_col: datetime column to fold on.
        embargo_days: gap between train-end and val-start. Defaults to the
            180-day label window.

    Returns:
        A list of ``(train_idx, val_idx)`` POSITIONAL-index arrays (suitable
        for ``df.iloc[...]``), ordered by validation year. Folds whose train or
        val side is empty are skipped — the earliest year is never a val fold
        because it has no embargoed history before it.
    """
    if date_col not in df.columns:
        raise ValueError(f"date_col {date_col!r} not in DataFrame columns")

    dates = pd.to_datetime(df[date_col]).reset_index(drop=True)
    if len(dates) == 0:
        return []

    years = sorted(dates.dt.year.unique())
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for y in years[1:]:
        val_start = pd.Timestamp(year=int(y), month=1, day=1)
        val_end = pd.Timestamp(year=int(y) + 1, month=1, day=1)
        # Embargo: train must end 180d before the val year so a train anchor's
        # forward label window can't peek into the validation period.
        train_cut = val_start - pd.Timedelta(days=embargo_days)

        train_idx = np.where((dates < train_cut).to_numpy())[0]
        val_idx = np.where(((dates >= val_start) & (dates < val_end)).to_numpy())[0]
        if len(train_idx) and len(val_idx):
            folds.append((train_idx, val_idx))
    return folds


def split_window(df: pd.DataFrame, *, date_col: str = "inspection_date") -> dict:
    """Date range + row count of a split, for a methodology ``windows`` block.

    Returns ``{"start": ISO date, "end": ISO date, "n": row count}``.
    """
    d = pd.to_datetime(df[date_col])
    return {
        "start": d.min().date().isoformat(),
        "end": d.max().date().isoformat(),
        "n": int(len(df)),
    }


@dataclass(frozen=True)
class SplitSummary:
    """Compact stats about a split — useful for log lines and model metadata.

    Frozen so it's safe to pass around.
    """

    rows: int
    date_min: pd.Timestamp | None
    date_max: pd.Timestamp | None
    positive_rate: float | None  # None when label_col not provided

    def to_dict(self) -> dict:
        return {
            "rows": int(self.rows),
            "date_min": self.date_min.isoformat() if self.date_min is not None else None,
            "date_max": self.date_max.isoformat() if self.date_max is not None else None,
            "positive_rate": (
                float(self.positive_rate) if self.positive_rate is not None else None
            ),
        }


def summarize(
    df: pd.DataFrame,
    *,
    date_col: str = "inspection_date",
    label_col: str | None = None,
) -> SplitSummary:
    """Return a SplitSummary; useful for printing or persisting to metadata."""
    if len(df) == 0:
        return SplitSummary(rows=0, date_min=None, date_max=None, positive_rate=None)

    dates = pd.to_datetime(df[date_col])
    positive_rate: float | None = None
    if label_col and label_col in df.columns:
        positive_rate = float(df[label_col].astype(float).mean())

    return SplitSummary(
        rows=len(df),
        date_min=dates.min(),
        date_max=dates.max(),
        positive_rate=positive_rate,
    )
