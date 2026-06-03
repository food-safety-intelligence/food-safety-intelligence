"""Per-license inspection-history features (the workhorse `prior_*` columns).

Every column added here is **leak-free** — at each anchor row, the feature
value summarises only data with strictly earlier dates at the same license.
The current row's own outcome never enters its own feature value.

There are two leak-free patterns in this module and we use them consistently:

  1. **Exclusive cumulative count.**
        ``group['x'].cumsum() - group['x']``
     The cumsum INCLUDES the current row; subtracting the current row's
     contribution leaves the count over strictly earlier rows.

  2. **Last-event-strictly-before.**
        Mask event values; forward-fill within group; shift by 1.
     The ffill gives the last event at-or-before this row; the shift moves
     it to "before this row" without including the row itself.

If a teammate ever writes a `prior_*` feature without one of these two
patterns, ``tests/test_features.py`` should catch it (we assert leak-freeness
on synthetic data with a known answer).

See CLAUDE.md § "Code style" — every ``.shift()`` / ``< as_of_date`` guard
must be commented with WHY. The comments below are mandatory, not optional.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def add_inspection_features(
    df: pd.DataFrame,
    *,
    license_col: str = "license_id",
    date_col: str = "inspection_date",
) -> pd.DataFrame:
    """Append per-anchor prior-history features.

    Required input columns (from ``inspections_labeled.parquet``):
        - ``license_id``, ``inspection_date``
        - ``is_fail_or_priority`` : bool — anchor event flag (from labels.py)
        - ``results`` : string — so we can isolate Fail anchors
        - ``violations`` : string — for the violation-code rollups

    Returns a new DataFrame. Does not mutate the input.

    Features added (every one of them describes events STRICTLY BEFORE the
    anchor's inspection_date at the same license_id):

        prior_inspections            int   — count of prior inspections
        prior_fails                  int   — count of prior Fail results
        prior_priority_violations    int   — count of prior priority (code 1-29) violations
        prior_core_violations        int   — count of prior core (code 30+) violations
        prior_fail_or_priority_events int  — count of prior is_fail_or_priority=True rows
        prior_fail_rate              float — prior_fails / prior_inspections, NaN if no priors
        prior_event_rate             float — prior_fail_or_priority / prior_inspections, NaN if no priors
        days_since_last_inspection   float — days; NaN if this is the first inspection
        days_since_last_fail         float — days since last prior Fail; NaN if no prior Fail
    """
    # We need stable sort order for the cumsum/shift patterns to produce
    # the right semantics. The group-key sort is also required for the
    # ffill-within-group dance below.
    out = df.sort_values([license_col, date_col], kind="mergesort").reset_index(drop=True)

    # --- Building-block event-flag columns ---------------------------------
    # We use int columns rather than bool because cumsum on bool is allowed
    # but produces a confusing dtype. Int8 is plenty for these counts at row level.
    out["_is_fail_int"] = (out["results"] == "Fail").astype("int8")
    # Re-derive violation counts here rather than trusting upstream — keeps
    # this module self-contained and lets tests pass a minimal input.
    out["_priority_int"] = out["violations"].apply(_count_priority).astype("int32")
    out["_core_int"] = out["violations"].apply(_count_core).astype("int32")
    # is_fail_or_priority may already exist from labels.py — re-compute if not.
    if "is_fail_or_priority" not in out.columns:
        out["is_fail_or_priority"] = (out["_is_fail_int"] == 1) | (out["_priority_int"] > 0)
    out["_event_int"] = out["is_fail_or_priority"].astype("int8")

    group = out.groupby(license_col, sort=False)

    # --- Pattern 1: exclusive cumulative counts ----------------------------
    # cumsum() includes the current row. Subtracting the row's value gives
    # the count over strictly earlier rows at this license. This is the
    # leak-free guard. Do NOT replace these subtractions with .shift() —
    # shift() is not group-aware and would bleed values across licenses at
    # group boundaries.
    out["prior_inspections"] = (
        group.cumcount().astype("int32")
        # cumcount() is 0-indexed and naturally excludes the current row already
    )
    out["prior_fails"] = (
        group["_is_fail_int"].cumsum() - out["_is_fail_int"]
    ).astype("int32")
    out["prior_priority_violations"] = (
        group["_priority_int"].cumsum() - out["_priority_int"]
    ).astype("int32")
    out["prior_core_violations"] = (
        group["_core_int"].cumsum() - out["_core_int"]
    ).astype("int32")
    out["prior_fail_or_priority_events"] = (
        group["_event_int"].cumsum() - out["_event_int"]
    ).astype("int32")

    # Ratios: only defined when there's at least one prior. NaN otherwise —
    # tree models handle NaN natively; logreg pipelines should impute.
    safe_denom = out["prior_inspections"].replace(0, np.nan)
    out["prior_fail_rate"] = (out["prior_fails"] / safe_denom).astype("float64")
    out["prior_event_rate"] = (
        out["prior_fail_or_priority_events"] / safe_denom
    ).astype("float64")

    # --- Pattern 2: "last event strictly before" --------------------------
    # days_since_last_inspection: shift the date within the license group.
    # ``group_keys=False`` keeps the result aligned with the original index.
    last_insp = group[date_col].shift(1)
    out["days_since_last_inspection"] = (
        (out[date_col] - last_insp).dt.days.astype("float64")
    )

    # days_since_last_fail: more involved. We want the date of the most
    # recent Fail at this license BEFORE the current row.
    #
    # The trick:
    #   1. Build a Series whose value is the date when results=='Fail', NaT otherwise.
    #   2. ffill WITHIN the license group — each row now carries the date of
    #      the most recent Fail at-or-before this row.
    #   3. shift(1) WITHIN the license group — now each row carries the date
    #      of the most recent Fail STRICTLY before this row. The shift also
    #      correctly leaves NaT in the first row of each group.
    #
    # Step 2's groupby().ffill() and Step 3's groupby().shift() each respect
    # group boundaries, so there's no cross-license leak.
    fail_date_or_nat = out[date_col].where(out["_is_fail_int"] == 1, pd.NaT)
    last_fail_at_or_before = fail_date_or_nat.groupby(out[license_col], sort=False).ffill()
    last_fail_strictly_before = last_fail_at_or_before.groupby(
        out[license_col], sort=False
    ).shift(1)
    out["days_since_last_fail"] = (
        (out[date_col] - last_fail_strictly_before).dt.days.astype("float64")
    )

    # Drop intermediate columns; they were named with `_` prefix on purpose.
    return out.drop(columns=["_is_fail_int", "_priority_int", "_core_int", "_event_int"])


# ---------------------------------------------------------------------------
# Helpers — kept local to this module so the file is self-contained.
# We import from `labels.py` would also work but couples the modules; the
# duplication is two lines and trivially correct.
# ---------------------------------------------------------------------------

import re as _re

_VIOLATION_CODE_RE = _re.compile(r"(?:^|\|)\s*(\d{1,2})\.\s")


def _violation_codes(text: object) -> list[int]:
    if not isinstance(text, str):
        return []
    return [int(c) for c in _VIOLATION_CODE_RE.findall(text)]


def _count_priority(text: object) -> int:
    return sum(1 for c in _violation_codes(text) if c <= 29)


def _count_core(text: object) -> int:
    return sum(1 for c in _violation_codes(text) if c > 29)
