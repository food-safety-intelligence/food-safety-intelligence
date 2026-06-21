"""Label construction for the food-safety risk model.

The target label is ``y_fail_or_critical_next_180d`` — 1 if the restaurant has
a Fail result OR a priority violation (codes 1-29) within 180 days AFTER the
anchor inspection date, else 0. The anchor inspection itself is excluded from
its own forward window — we predict what happens *after* this visit, not on it.

See ``docs/interface_contracts.md`` § ``inspections_labeled.parquet`` for the
authoritative schema. CLAUDE.md governs scope and the 2019 burn-in cutoff
(see the "What is IN scope" section: pre-2019 inspections are kept as burn-in
for ``prior_*`` features but never used as training labels — the July 2018
Chicago inspection-procedure change makes pre/post labels non-comparable).

This module is the only place where label semantics live. Notebooks and scripts
call ``build_labels(inspections)``; if the label definition changes, this is
the one file to update and the one test in ``tests/test_labels.py`` to revisit.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from foodsafety.config import LABEL_WINDOW_DAYS, TRAIN_START_DATE

# Each violation in the pipe-separated `violations` text starts with its
# numbered code: "10. ADEQUATE HANDWASHING ... | 55. PHYSICAL FACILITIES ..."
# Chicago codes: 1-29 are priority / priority-foundation (the serious tier);
# 30+ are core. We capture the code and decide priority membership downstream.
#
# Anchor: either the very start of the cell OR a "|" delimiter. The regex
# matches "<delim or start> <whitespace>* <1-2 digits> '.' <space>".
_VIOLATION_CODE_RE = re.compile(r"(?:^|\|)\s*(\d{1,2})\.\s")

# Result values that are operationally meaningful for modelling. Other values
# in the inspections data ("Out of Business", "No Entry", "Not Ready",
# "Business Not Located") describe an inspector's failure to perform the
# inspection, not a food-safety outcome. They are kept in the labeled table
# but should be dropped before training (handled in feature engineering, NOT
# here — keeping the labeled table broad lets us audit them later).
MODELABLE_RESULTS = frozenset({"Pass", "Pass w/ Conditions", "Fail"})

# Codes 1-29 are the priority / priority-foundation tier. A violation cell can
# contain multiple codes; we consider it "priority" if ANY priority code is
# present. The boundary number itself (29) is intentionally INCLUSIVE — Chicago's
# documentation places the priority/core split between code 29 and 30.
_PRIORITY_CODE_MAX = 29

# License placeholder values used by Chicago for unlicensed events / data
# entry errors. Multiple unrelated establishments share these tokens, so we
# can NOT compute meaningful labels for them (the per-license grouping would
# pool unrelated history together). Their label is left as NA.
INVALID_LICENSE_TOKENS = frozenset({"", "0"})


def extract_violation_codes(text: str | float | None) -> list[int]:
    """Return sorted list of integer violation codes found in one cell.

    Accepts None / NaN (returns empty list) so the function is safe to apply
    over a column with missing values.
    """
    if not isinstance(text, str):
        return []
    return sorted(int(c) for c in _VIOLATION_CODE_RE.findall(text))


def has_priority_violation(text: str | float | None) -> bool:
    """True iff any code 1-29 is present in the violations text."""
    return any(c <= _PRIORITY_CODE_MAX for c in extract_violation_codes(text))


def add_violation_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add violation-code derivatives as new columns. Returns a new DataFrame.

    Columns added:
        - ``violation_codes`` : list[int]
        - ``n_violations`` : int
        - ``has_priority_violation`` : bool
        - ``n_priority_violations`` : int (count of codes 1-29)
        - ``n_core_violations`` : int (count of codes 30+)

    These are NOT directly part of the label, but the label depends on
    ``has_priority_violation`` and the counts are useful first-class features
    for later notebooks.
    """
    out = df.copy()
    codes = out["violations"].apply(extract_violation_codes)
    out["violation_codes"] = codes
    out["n_violations"] = codes.str.len().astype("Int32")
    out["has_priority_violation"] = codes.apply(lambda cs: any(c <= _PRIORITY_CODE_MAX for c in cs))
    out["n_priority_violations"] = codes.apply(
        lambda cs: sum(1 for c in cs if c <= _PRIORITY_CODE_MAX)
    ).astype("Int32")
    out["n_core_violations"] = codes.apply(
        lambda cs: sum(1 for c in cs if c > _PRIORITY_CODE_MAX)
    ).astype("Int32")
    return out


def _compute_forward_labels(
    df: pd.DataFrame,
    window_days: int,
) -> np.ndarray:
    """Per-license forward-window labels. Pure helper, see `build_labels`.

    For every row i, look at rows at the same license_id with
    ``inspection_date in (date_i, date_i + window_days]``. Label is 1 if any
    of those rows has ``is_fail_or_priority == True``, else 0.

    Returns a numpy int8 array of length len(df), aligned to df's existing
    integer position (0..N-1). Callers should ensure df is positionally
    indexed before calling.
    """
    n = len(df)
    out = np.zeros(n, dtype=np.int8)
    dates = df["inspection_date"].to_numpy()
    flags = df["is_fail_or_priority"].to_numpy()
    window = np.timedelta64(window_days, "D")

    # Group by license_id and process each group. `.indices` returns a dict
    # of {license_id: np.array of row positions}, which avoids the overhead
    # of pulling DataFrame slices.
    for license_id, positions in df.groupby("license_id", sort=False).indices.items():
        if license_id in INVALID_LICENSE_TOKENS:
            # Leave defaults (0) — caller will mask these back to NA. We don't
            # compute labels because the placeholder license pools unrelated
            # establishments and the label would be meaningless.
            continue

        # Positions are not guaranteed to be sorted; sort within the group by
        # date so we can break early in the inner loop.
        order = np.argsort(dates[positions])
        sorted_positions = positions[order]
        sorted_dates = dates[sorted_positions]
        sorted_flags = flags[sorted_positions]

        # For each anchor i in this license, scan forward until we either
        # find a fail/priority within the window or pass beyond it. Inner
        # loop is O(window-size) per row; small in practice because most
        # licenses have <20 inspections in the history.
        for i in range(len(sorted_positions)):
            upper = sorted_dates[i] + window
            for j in range(i + 1, len(sorted_positions)):
                if sorted_dates[j] > upper:
                    break  # rest will also be > upper (sorted)
                if sorted_flags[j]:
                    out[sorted_positions[i]] = 1
                    break

    return out


def build_labels(
    inspections: pd.DataFrame,
    *,
    label_window_days: int = LABEL_WINDOW_DAYS,
    train_start_date: str = TRAIN_START_DATE,
) -> pd.DataFrame:
    """Construct the inspections_labeled table from raw inspections.

    The returned DataFrame adds these columns to the input:
        - ``is_fail_or_priority`` : bool — true if this single inspection is
          a Fail OR contains a priority violation. Building block for the
          label, not a feature for training.
        - ``is_burnin`` : bool — true if ``inspection_date < train_start_date``.
          These rows are kept (so ``prior_*`` features can be computed at the
          start of 2019) but their label is NA — we never train on them.
        - ``right_truncated`` : bool — true if the anchor's full
          ``window_days`` forward window extends past the latest inspection
          in the dataset. The label is still computed (as 0 if no in-window
          fail was observed), but downstream code may wish to drop these
          from evaluation to avoid biasing recent recency periods.
        - ``y_fail_or_critical_next_180d`` : Int8 — the label. NA on burn-in
          rows and on rows with placeholder license tokens (see
          ``INVALID_LICENSE_TOKENS``).

    The input ``license_`` column is renamed to ``license_id`` to match the
    contract in ``docs/interface_contracts.md``.

    Args:
        inspections: DataFrame from ``data/raw/inspections.parquet`` (the
            output of ``foodsafety.io.cache.load_or_fetch``). Required
            columns: ``inspection_id``, ``license_``, ``inspection_date``,
            ``results``, ``violations``.
        label_window_days: forward-window size in days. Defaults to
            ``config.LABEL_WINDOW_DAYS`` (180).
        train_start_date: ISO date string. Inspections strictly before this
            are burn-in. Defaults to ``config.TRAIN_START_DATE`` ("2019-01-01").

    Returns:
        New DataFrame; the input is not mutated.
    """
    df = inspections.copy()

    # Rename to match the contract. We do this early so the rest of the
    # function reads naturally as `license_id`.
    if "license_" in df.columns and "license_id" not in df.columns:
        df = df.rename(columns={"license_": "license_id"})
    df["license_id"] = df["license_id"].fillna("").astype(str)

    # Type coercions — inspections.parquet stores object dtypes and we need
    # datetime arithmetic for the forward window.
    df["inspection_date"] = pd.to_datetime(df["inspection_date"])

    # Per-inspection event flag. The label aggregates this flag over the
    # FUTURE 180-day window at the same license.
    df["is_fail_or_priority"] = (df["results"] == "Fail") | df["violations"].apply(
        has_priority_violation
    )

    # Burn-in flag — pre-2019 rows are kept but label is NA.
    train_start_ts = pd.Timestamp(train_start_date)
    df["is_burnin"] = df["inspection_date"] < train_start_ts

    # Right-truncation flag — the anchor's window extends past the latest
    # date in this dataset. We can't observe the full window, so the label
    # is potentially under-counted (we'd record 0 even if a future
    # inspection unseen in this snapshot would have been a Fail).
    dataset_max = df["inspection_date"].max()
    df["right_truncated"] = (
        df["inspection_date"] + pd.Timedelta(days=label_window_days)
    ) > dataset_max

    # Compute labels with positional indexing. We reset_index here so the
    # numpy positions returned by `_compute_forward_labels` align with the
    # row order; we restore the original index at the end.
    original_index = df.index
    df = df.reset_index(drop=True)
    labels = _compute_forward_labels(df, label_window_days)
    df["y_fail_or_critical_next_180d"] = pd.array(labels, dtype="Int8")

    # Mask the label to NA where we couldn't / shouldn't compute it:
    #   - burn-in rows (pre-2019)
    #   - rows with invalid license tokens ("" or "0")
    na_mask = df["is_burnin"] | df["license_id"].isin(INVALID_LICENSE_TOKENS)
    df.loc[na_mask, "y_fail_or_critical_next_180d"] = pd.NA

    df.index = original_index
    return df
