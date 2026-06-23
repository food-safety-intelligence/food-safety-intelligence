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

**Bureau-specific features**: when the violations dataframe includes a
``department_bureau`` column, ``add_building_features`` also computes per-bureau
violation counts for the five bureaus directly tied to food-safety risk:

  * ``CONSERVATION``  — structural / pest / plumbing (1.3M rows, highest density)
  * ``REFRIGERATION`` — commercial refrigeration failures (direct food-safety risk)
  * ``PLUMBING``      — hot water supply and drainage (tied to food-inspection codes)
  * ``VENTILATION``   — kitchen exhaust systems
  * ``ELECTRICAL``    — power failures that cascade to refrigeration failures

These produce ``prior_bldg_{bureau}_365d`` columns plus a combined
``days_since_last_food_safety_bldg_violation`` recency across all five bureaus.
The single-window design (365d) is intentional for the sparse bureaus (32–43k
rows city-wide): 730d risks picking up violations from a previous tenant or a
prior building on the site.
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

# Bureaus whose violations are directly tied to food-safety risk.
# Derived from Chicago Building Violations (22u3-xenr) department_bureau
# distribution; these five account for ~1.5M of ~1.9M total violations.
# See module docstring for the food-safety rationale per bureau.
FOOD_SAFETY_BUREAUS: tuple[str, ...] = (
    "CONSERVATION",   # structural / pest / plumbing — highest-volume signal
    "REFRIGERATION",  # commercial refrigeration failures — direct risk
    "PLUMBING",       # hot water / drainage — tied to food-inspection codes
    "VENTILATION",    # kitchen exhaust systems
    "ELECTRICAL",     # power failures → refrigeration failures
)

# Column in the Building Violations SODA dataset that holds the bureau name.
BUREAU_COL: str = "department_bureau"


def add_building_features(
    inspections: pd.DataFrame,
    permits: pd.DataFrame | None,
    violations: pd.DataFrame | None,
    *,
    radius_m: int = DEFAULT_RADIUS_M,
    inspection_date_col: str = "inspection_date",
    bureau_col: str = BUREAU_COL,
    food_safety_bureaus: tuple[str, ...] = FOOD_SAFETY_BUREAUS,
) -> pd.DataFrame:
    """Append block-face building-permit / violation features to inspections.

    Produces, for the block-face within ``radius_m`` of each anchor and strictly
    before its date:

    **Aggregate violation features** (always, when violations is not None):
      * ``prior_bldg_violations_365d`` / ``prior_bldg_violations_730d`` (Int32)
      * ``days_since_last_bldg_violation`` (Float64; NA = no prior on block-face)

    **Bureau-specific features** (when violations has a ``bureau_col`` column):
      * ``prior_bldg_{bureau}_365d`` for each bureau in ``food_safety_bureaus``
        (one 365d count per bureau; slug = bureau.lower().replace(" ", "_"))
      * ``days_since_last_food_safety_bldg_violation`` (Float64) — recency of
        ANY violation from a food-safety-relevant bureau

    **Permit features** (when permits is not None):
      * ``prior_bldg_permits_365d`` (Int32)
      * ``days_since_last_bldg_permit`` (Float64)

    Args:
        inspections: must contain ``inspection_date``, ``latitude``,
            ``longitude``.
        permits: Building Permits dataframe (``issue_date`` + ``latitude`` /
            ``longitude``). If ``None``, the permit columns are skipped.
        violations: Building Violations dataframe (``violation_date`` +
            ``latitude`` / ``longitude``). If ``None``, the violation columns
            are skipped.
        radius_m: block-face search radius in metres.
        bureau_col: column in ``violations`` holding the bureau name. When
            absent from violations, bureau-specific features are skipped.
        food_safety_bureaus: bureau names to compute individual count features
            for. Defaults to ``FOOD_SAFETY_BUREAUS``.

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

    # --- Bureau-specific violation features ----------------------------------
    # Only computed when violations carries a department_bureau column (i.e.
    # the caller fetched it). Each bureau gets a 365d count. A single-window
    # design keeps the feature count manageable for sparse bureaus (32–43k
    # rows city-wide). Also compute a combined food-safety-bureau recency.
    if (
        violations is not None
        and bureau_col in violations.columns
        and len(anchor_coords_rad) > 0
    ):
        _add_bureau_features(
            out=out,
            violations=violations,
            has_geo=has_geo,
            anchor_coords_rad=anchor_coords_rad,
            anchor_dates=anchor_dates,
            radius_rad=radius_rad,
            bureau_col=bureau_col,
            food_safety_bureaus=food_safety_bureaus,
        )

    return out


def _add_bureau_features(
    out: pd.DataFrame,
    violations: pd.DataFrame,
    has_geo: np.ndarray,
    anchor_coords_rad: np.ndarray,
    anchor_dates: np.ndarray,
    radius_rad: float,
    bureau_col: str,
    food_safety_bureaus: tuple[str, ...],
) -> None:
    """Add per-bureau violation counts + combined food-safety recency in-place.

    Builds one BallTree per bureau (subset of violations) and calls
    _block_face_stats. Mutates ``out`` directly to avoid extra copies.
    """
    date_col = "violation_date"
    fs_recency_col = "days_since_last_food_safety_bldg_violation"

    # Initialise all output columns to NA before filling with-geo rows.
    for bureau in food_safety_bureaus:
        slug = bureau.lower().replace(" ", "_")
        count_col = f"prior_bldg_{slug}_365d"
        out[count_col] = pd.array([pd.NA] * len(out), dtype="Int32")
    out[fs_recency_col] = pd.array([pd.NA] * len(out), dtype="Float64")

    # Shared geo + date prep for the full violations frame.
    ev_all = violations[["latitude", "longitude", date_col, bureau_col]].copy()
    ev_all["latitude"] = pd.to_numeric(ev_all["latitude"], errors="coerce")
    ev_all["longitude"] = pd.to_numeric(ev_all["longitude"], errors="coerce")
    ev_all[date_col] = pd.to_datetime(ev_all[date_col], errors="coerce")
    ev_all = ev_all.dropna(subset=["latitude", "longitude", date_col])
    if ev_all.empty:
        return

    # Per-bureau 365d count.
    for bureau in food_safety_bureaus:
        slug = bureau.lower().replace(" ", "_")
        count_col = f"prior_bldg_{slug}_365d"

        ev_b = ev_all[ev_all[bureau_col] == bureau]
        if ev_b.empty:
            continue

        counts, _ = _block_face_stats(
            event_coords_rad=np.radians(
                ev_b[["latitude", "longitude"]].to_numpy(dtype=np.float64)
            ),
            event_dates=ev_b[date_col].to_numpy(dtype="datetime64[D]"),
            anchor_coords_rad=anchor_coords_rad,
            anchor_dates=anchor_dates,
            radius_rad=radius_rad,
            windows=(365,),
        )
        out.loc[has_geo, count_col] = pd.array(counts[365], dtype="Int32")

    # Combined food-safety recency: days since the nearest prior violation from
    # ANY of the five bureaus. One BallTree over the union — cheaper than five
    # separate recency queries and gives the model a single "how long since
    # any relevant building issue" signal.
    ev_fs = ev_all[ev_all[bureau_col].isin(food_safety_bureaus)]
    if not ev_fs.empty:
        _, recency = _block_face_stats(
            event_coords_rad=np.radians(
                ev_fs[["latitude", "longitude"]].to_numpy(dtype=np.float64)
            ),
            event_dates=ev_fs[date_col].to_numpy(dtype="datetime64[D]"),
            anchor_coords_rad=anchor_coords_rad,
            anchor_dates=anchor_dates,
            radius_rad=radius_rad,
            windows=(365,),  # windows arg required; recency is window-independent
        )
        out.loc[has_geo, fs_recency_col] = pd.array(recency, dtype="Float64")


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
