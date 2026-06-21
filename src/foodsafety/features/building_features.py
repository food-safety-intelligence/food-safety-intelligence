"""Building permit / violation features via block-face spatial join.

Physical-plant condition — old plumbing, failing refrigeration, structural
issues — is plausibly orthogonal to a venue's *inspection* history, which is
why building records are the first external-data bet for breaking the modelling
ceiling (the existing inspection / 311 / license feeds are mutually correlated
and exhausted).

**Why block-face, not same-building.** Chicago building records are filed under
the building's street number, which often differs from the food
establishment's recorded number (e.g. a restaurant at "3107 N BROADWAY" with
its block's permits/violations recorded at 3109 / 3112 / 3115). Exact
street-number matching is therefore brittle (empirically ~40 % recall for
violations, ~2 % for permits). A tight lat/lon radius is the robust match —
but at ~30 m it captures the immediate block-face (this building plus its
nearest neighbours), not strictly one parcel. We deliberately keep the radius
tight: a wider radius (≥100 m) degrades into "is there any construction on this
block," i.e. neighbourhood density, which both dilutes the building signal and
reintroduces the geographic proxy we dropped ``static_zip`` to avoid. The
granularity here is **block-face**, and the group-fairness gate is non-optional
because of it.

**Implementation** (mirrors ``complaint_features.add_complaint_features``):
  1. Build a ``sklearn.neighbors.BallTree`` over event (lat, lon) with
     ``metric='haversine'``.
  2. For each inspection anchor, ``query_radius`` returns the events within the
     block-face radius.
  3. Apply the date window and count / take recency.

**Leak-free guard**: only events strictly BEFORE the anchor date count
(``event_date < as_of_date``). A permit issued or violation recorded ON the
inspection day is excluded — we never let same-day or future physical-plant
records inform a prediction whose label window starts after the anchor.

**Cold-start / no-geo handling**: anchors with missing lat/lon get ``NA`` for
every column — "we couldn't compute a spatial signal", not a fabricated 0.
``days_since_*`` is also ``NA`` when the venue's block-face has no prior record
at all, so the model can tell "no history" from "yesterday".
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

# Earth's radius in metres — converts the block-face radius to the radian units
# the haversine BallTree expects.
EARTH_RADIUS_M: float = 6_371_000.0

# Block-face match radius. ~30 m keeps the match at building + nearest
# neighbours (see module docstring on why we reject wider radii).
DEFAULT_RADIUS_M: int = 30

# Trailing windows (days) for the count features. 365 / 730 mirror the
# prior_*_365d recency horizon the inspection features already use, so building
# counts compete on the same timescale.
VIOLATION_WINDOWS_D: tuple[int, ...] = (365, 730)
PERMIT_WINDOWS_D: tuple[int, ...] = (365,)


def add_building_features(
    inspections: pd.DataFrame,
    permits: pd.DataFrame | None,
    violations: pd.DataFrame | None,
    *,
    radius_m: int = DEFAULT_RADIUS_M,
    inspection_date_col: str = "inspection_date",
) -> pd.DataFrame:
    """Append block-face building-permit / violation features to inspections.

    Produces, for the block-face within ``radius_m`` of each anchor and strictly
    before its date:

      * ``prior_bldg_violations_365d`` / ``prior_bldg_violations_730d`` (Int32)
      * ``days_since_last_bldg_violation`` (Float64; NA = no prior on block-face)
      * ``prior_bldg_permits_365d`` (Int32)
      * ``days_since_last_bldg_permit`` (Float64; NA = no prior on block-face)

    Args:
        inspections: must contain ``inspection_date``, ``latitude``,
            ``longitude``.
        permits: Building Permits dataframe (``issue_date`` + ``latitude`` /
            ``longitude``). If ``None``, the permit columns are skipped.
        violations: Building Violations dataframe (``violation_date`` +
            ``latitude`` / ``longitude``). If ``None``, the violation columns
            are skipped.
        radius_m: block-face search radius in metres.

    Anchors with missing lat/lon get ``NA`` for every column (no spatial signal
    computable); building rows without geo are dropped before the tree build.
    """
    out = inspections.copy()
    out[inspection_date_col] = pd.to_datetime(out[inspection_date_col])
    out["latitude"] = pd.to_numeric(out["latitude"], errors="coerce")
    out["longitude"] = pd.to_numeric(out["longitude"], errors="coerce")

    has_geo = out[["latitude", "longitude"]].notna().all(axis=1).to_numpy()
    radius_rad = radius_m / EARTH_RADIUS_M

    if has_geo.any():
        anchor_coords_rad = np.radians(
            out.loc[has_geo, ["latitude", "longitude"]].to_numpy(dtype=np.float64)
        )
        anchor_dates = out.loc[has_geo, inspection_date_col].values.astype("datetime64[D]")
    else:
        anchor_coords_rad = np.empty((0, 2), dtype=np.float64)
        anchor_dates = np.empty(0, dtype="datetime64[D]")

    specs = [
        ("violation", violations, "violation_date", VIOLATION_WINDOWS_D),
        ("permit", permits, "issue_date", PERMIT_WINDOWS_D),
    ]
    for kind, events, date_col, windows in specs:
        count_cols = {w: f"prior_bldg_{kind}s_{w}d" for w in windows}
        recency_col = f"days_since_last_bldg_{kind}"

        # Default everything to NA — "signal not computable" for no-geo anchors,
        # overwritten below for the with-geo subset.
        for col in count_cols.values():
            out[col] = pd.array([pd.NA] * len(out), dtype="Int32")
        out[recency_col] = pd.array([pd.NA] * len(out), dtype="Float64")

        if events is None or len(anchor_coords_rad) == 0:
            continue

        ev = events[["latitude", "longitude", date_col]].copy()
        ev["latitude"] = pd.to_numeric(ev["latitude"], errors="coerce")
        ev["longitude"] = pd.to_numeric(ev["longitude"], errors="coerce")
        ev[date_col] = pd.to_datetime(ev[date_col], errors="coerce")
        ev = ev.dropna(subset=["latitude", "longitude", date_col])
        if ev.empty:
            continue

        counts, recency = _block_face_stats(
            event_coords_rad=np.radians(ev[["latitude", "longitude"]].to_numpy(dtype=np.float64)),
            event_dates=ev[date_col].to_numpy(dtype="datetime64[D]"),
            anchor_coords_rad=anchor_coords_rad,
            anchor_dates=anchor_dates,
            radius_rad=radius_rad,
            windows=windows,
        )
        for w in windows:
            out.loc[has_geo, count_cols[w]] = pd.array(counts[w], dtype="Int32")
        out.loc[has_geo, recency_col] = pd.array(recency, dtype="Float64")

    return out


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _block_face_stats(
    event_coords_rad: np.ndarray,
    event_dates: np.ndarray,
    anchor_coords_rad: np.ndarray,
    anchor_dates: np.ndarray,
    radius_rad: float,
    windows: tuple[int, ...],
) -> tuple[dict[int, np.ndarray], np.ndarray]:
    """Per-anchor block-face counts (one per window) + days-since-last.

    One BallTree build + radius query, then a per-anchor date pass. For each
    anchor we take the ages (in days) of all events within the radius, keep only
    those strictly before the anchor (``age > 0`` — the leak guard), count those
    within each window, and take the minimum positive age as recency.
    """
    tree = BallTree(event_coords_rad, metric="haversine")
    neighbour_indices = tree.query_radius(anchor_coords_rad, r=radius_rad)

    n = len(anchor_coords_rad)
    counts = {w: np.zeros(n, dtype=np.int32) for w in windows}
    recency = np.full(n, np.nan, dtype=np.float64)

    for i, idxs in enumerate(neighbour_indices):
        if len(idxs) == 0:
            continue
        # Age in days from event to anchor; positive = strictly before the
        # anchor date (the leak guard — same-day and future events excluded).
        ages = (anchor_dates[i] - event_dates[idxs]).astype("timedelta64[D]").astype(np.int64)
        prior = ages[ages > 0]
        if prior.size == 0:
            continue
        for w in windows:
            counts[w][i] = int((prior <= w).sum())
        recency[i] = float(prior.min())

    return counts, recency
