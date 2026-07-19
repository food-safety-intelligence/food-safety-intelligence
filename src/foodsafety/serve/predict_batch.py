"""Batch scoring — produces the cross-team `scores.parquet` artifact.

For each restaurant in ``features.parquet`` we generate:

  * ``risk_score`` — calibrated probability from the production model
  * ``risk_tier`` — discretised band (Low / Moderate / Elevated / High)
  * ``top_drivers`` — list of plain-English driver objects from SHAP attribution
  * ``trend_slope`` — OLS slope of the forecast-only model's score over this
    restaurant's last ``TREND_K_VISITS`` inspections (visits, not a calendar
    window). Null if fewer than 2 scored points. See DR 0011.

Per CLAUDE.md, this is the **batch-score-to-JSON** pattern. The output
parquet is the authoritative contract artifact; ``scores.json`` (web app
input) is generated downstream by a thin converter script.

Anchor convention: one row per restaurant, using the **most recent inspection
date** as the ``as_of_date``. Phase 7 will extend to per-restaurant-per-day
rolling if the UI needs it; for the MVP the latest-inspection convention is
sufficient and matches what the detail page renders today.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from foodsafety.explain.shap_drivers import (
    linear_contributions,
    top_drivers_for_row,
)
from foodsafety.features.license_features import normalize_facility_type

# --- Unified cross-city risk-tier rule (DR 0017) ------------------------------
# Every city's model emits a CALIBRATED probability, but the three cities predict
# different events with very different base rates (Chicago P(fail-or-priority 180d)
# ~11%; NYC P(next graded B/C) ~41%; LA ~9%), so a shared ABSOLUTE cutoff would mean
# different things per city. Instead the cutoffs are anchored to each city's own
# base rate (its label prevalence):
#
#   Low       score <  0.5x base    -- clearly below baseline; genuinely low risk
#   Moderate  0.5x - 1.0x base      -- around the city's own baseline
#   Elevated  1.0x base - High_cut  -- above baseline
#   High      score >= High_cut     -- High_cut = max(2x base, the city's p98 score)
#
# Low/Moderate/Elevated boundaries are FIXED multiples of the base rate: "Low" then
# means the same low risk in every city, and (being fixed, not quantiles) a venue's
# tier only moves when ITS score moves, not when the population shifts. High is the
# rarer of "top 2%" or ">=2x base", so it stays a small, genuinely-elevated triage
# slice regardless of how each city's score distribution is shaped -- without the
# p98 cap, a low-base city piles many merely-above-average venues into High.
#
# This supersedes the fixed Chicago cutoffs (DR 0008) and the NYC/LA p40/p85/p98
# quantile blocks; all three producers now tier via `assign_risk_tiers`. Full
# rationale + per-city numbers in `docs/tier-method-cross-city-analysis.md`.
TIER_LOW_MULTIPLE = 0.5
TIER_MODERATE_MULTIPLE = 1.0
TIER_HIGH_MULTIPLE = 2.0
TIER_HIGH_PERCENTILE = 0.98

# Per-city base rate = label prevalence on the city's held-out test set. Fixed
# reference values (not recomputed per run) so the Low/Moderate/Elevated cutoffs
# stay stable across rescores. Chicago's is the default for build_scores_table;
# the NYC/LA producers pass their own.
CHICAGO_BASE_RATE = 0.108

# Trend slope is fit over each license's last K inspections (visits), not a fixed
# calendar window. K=5 is the tuned default — see DR 0011 / docs/model-experiments.md
# (2026-06-28): coverage is K-stable and the steeply-rising watch-list lift peaks
# at K=4-5. The trend is computed from the forecast-only model's score (passed in
# as ``trend_scores``), not the production risk score.
TREND_K_VISITS = 5

# Inspection results that mean the venue no longer operates (DR 0014). "No Entry"
# and "Not Ready" are deliberately NOT closure signals — the venue may be open.
# Closure is derived from the license's LATEST event only: an establishment that
# reopens does so under a new license_id, so an old closing event never marks a
# live license closed.
CLOSED_RESULTS = frozenset({"Out of Business", "Business Not Located"})

# Slope magnitude below which a trend reads as "stable". Mirrors the web app's
# TREND_STABLE_BAND (app/src/lib/scores.ts) so the totals worsening/improving
# counts match the per-establishment direction the app labels and shows. Keep
# the two in sync (DR 0011 retuned this from 0.001 to 0.0003).
TREND_STABLE_BAND = 0.0003


def out_of_business_status(labeled: pd.DataFrame) -> pd.DataFrame:
    """Per-license closure status from the full inspection event stream.

    ``labeled`` is ``inspections_labeled.parquet`` — the only artifact that
    carries every event type (License visits, Not Ready, Out of Business...).
    The features frame can't answer this: closure events aren't scoreable rows.

    Returns a frame indexed by ``license_id`` with:
      * ``is_out_of_business`` — the license's latest event result is in
        :data:`CLOSED_RESULTS`
      * ``closed_since`` — that event's date (NaT for active licenses)
    """
    ev = labeled[["license_id", "inspection_date", "results"]].copy()
    ev["inspection_date"] = pd.to_datetime(ev["inspection_date"])
    latest = ev.sort_values("inspection_date").drop_duplicates("license_id", keep="last")
    latest["is_out_of_business"] = latest["results"].isin(CLOSED_RESULTS)
    latest["closed_since"] = latest["inspection_date"].where(latest["is_out_of_business"])
    return latest.set_index("license_id")[["is_out_of_business", "closed_since"]]


def tier_thresholds(base_rate: float, high_percentile_score: float) -> list[tuple[float, str]]:
    """Unified tier cutoffs for one city (DR 0017).

    ``base_rate`` is the city's label prevalence; ``high_percentile_score`` is the
    :data:`TIER_HIGH_PERCENTILE` (p98) of the scored population. Returns the
    ``(upper_bound, tier)`` list :func:`score_to_tier` consumes, ``High`` last.
    """
    low = round(TIER_LOW_MULTIPLE * base_rate, 4)
    moderate = round(TIER_MODERATE_MULTIPLE * base_rate, 4)
    # High is the rarer of ">=2x base" or "top 2%": max() keeps it both genuinely
    # elevated and rare in every city.
    high = round(max(TIER_HIGH_MULTIPLE * base_rate, high_percentile_score), 4)
    return [(low, "Low"), (moderate, "Moderate"), (high, "Elevated"), (1.01, "High")]


def score_to_tier(score: float, thresholds: list[tuple[float, str]]) -> str:
    """Discretise a probability into Low / Moderate / Elevated / High."""
    for threshold, tier in thresholds:
        if score < threshold:
            return tier
    return "High"


def assign_risk_tiers(
    scores: pd.Series, base_rate: float
) -> tuple[pd.Series, list[tuple[float, str]]]:
    """Tier every score with the unified rule; return the tiers + thresholds used.

    ``base_rate`` is the city's label prevalence. The High cutoff's p98 is taken
    from ``scores`` itself (the served population), so callers can persist the
    returned thresholds to methodology.json rather than recomputing them.
    """
    p98 = float(scores.quantile(TIER_HIGH_PERCENTILE))
    thresholds = tier_thresholds(base_rate, p98)
    tiers = scores.apply(lambda s: score_to_tier(s, thresholds))
    return tiers, thresholds


def _establishment_key(df: pd.DataFrame) -> pd.Series:
    """A physical-establishment key: normalised ``dba_name`` + ``address``.

    A single physical restaurant can hold several license_ids over time — a
    renewal, an ownership change, or a close-then-reopen each mints a new
    license. Those licenses share the same name and street address, so keying
    on (name, address) collapses them to one establishment. Normalisation is
    required: the raw strings differ by trailing whitespace and case (e.g.
    "546 N WELLS ST " vs "546 N WELLS ST"), which a raw match would treat as
    distinct. Rows with no name AND no address fall back to license_id so blank
    records are never merged together.
    """
    name = df["dba_name"].fillna("").astype(str).str.upper().str.replace(r"\s+", " ", regex=True)
    addr = df["address"].fillna("").astype(str).str.upper().str.replace(r"\s+", " ", regex=True)
    name = name.str.strip()
    addr = addr.str.strip()
    key = name + "|" + addr
    blank = (name == "") & (addr == "")
    return key.mask(blank, "license:" + df["license_id"].astype(str))


# Source columns for the display area, in preference order. NYC's feed carries
# `boro`; LA's `city` names the separate incorporated cities (Beverly Hills, West
# Hollywood) and postal cities (Van Nuys) that a user actually means when they say
# where a place is. Chicago's feed has `city` too, but see _area_series.
_AREA_SOURCE_COLUMNS = ("boro", "city")

# Feed placeholders that mean "no value" and must not reach the UI as a label.
# NYC's boro column uses "0" for unknown.
_AREA_PLACEHOLDER = r"0|n/?a|none|unknown|not applicable"

# A source column whose single most common value covers at least this share of rows
# can't distinguish one area from another, so it counts as no signal. See
# _area_series for the measured per-city shares this sits between.
_AREA_DOMINANCE_LIMIT = 0.9


def _clean_area(values: pd.Series) -> pd.Series:
    """Normalise a raw feed area value for display."""
    out = values.fillna("").astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    out = out.mask(out.str.fullmatch(_AREA_PLACEHOLDER, case=False), "")
    # Title-case only the shouted values (LA ships "LOS ANGELES"); leave already
    # mixed-case ones alone so "Manhattan" and a name like "DeKalb" survive intact.
    return out.where(~out.str.isupper(), out.str.title())


def _area_series(df: pd.DataFrame) -> pd.Series:
    """Per-establishment display area, or empty when the feed carries no area signal.

    Chicago's feed has a ``city`` column, but 99.6% of rows say CHICAGO — it tells a
    user nothing, and shipping it would put a dead filter in front of the chart tool
    and a useless term in the app's search index. A column dominated by one value is
    therefore treated as no signal and yields empty.

    Dominance, not distinct-count, is the test: Chicago's column has 54 distinct
    values once typo variants (Cchicago, CHicago, CHICAGOCHICAGO) and a few genuine
    suburbs are counted, so counting values keeps a column that distinguishes
    nothing. Measured top-value share is 0.996 for Chicago against 0.30 (LA) and
    0.38 (NYC), so the threshold sits in a wide empty gap. The rule needs no
    per-city branch and any future single-city feed drops out the same way.
    """
    for col in _AREA_SOURCE_COLUMNS:
        if col not in df.columns:
            continue
        cleaned = _clean_area(df[col])
        present = cleaned[cleaned != ""]
        if present.empty:
            continue
        # Case-folded so Chicago's typo variants count toward the same dominant
        # value instead of masquerading as genuine variety.
        share = present.str.casefold().value_counts(normalize=True).iloc[0]
        if share < _AREA_DOMINANCE_LIMIT:
            return cleaned
    return pd.Series("", index=df.index, dtype="object")


def _clean_zip(values: pd.Series) -> pd.Series:
    """Five-digit ZIP for display. Anything else (ZIP+4, blank, junk) reduces to the
    leading five digits, or empty when there aren't five."""
    digits = values.fillna("").astype(str).str.extract(r"^\s*(\d{5})", expand=False)
    return digits.fillna("")


# The display columns every city's scores artifact must carry. Empty string is a
# legal value: which of these a feed can populate varies by city.
DISPLAY_GEOGRAPHY_COLUMNS = ("neighborhood", "zip", "facility_type")


def add_display_geography(df: pd.DataFrame) -> pd.DataFrame:
    """Attach the descriptive display columns, derived from the feed's own values.

    Shared by ALL city score builders (Chicago's ``build_scores_table`` and the NYC
    / LA scripts) on purpose. These columns were empty in every city for months
    because each writer was expected to populate them independently and none did;
    a single derivation means a city cannot silently ship blanks again, and the
    three cities agree on what each column MEANS rather than by coincidence.

    Coverage differs by feed and that is expected, not a defect:
      * ``zip``           — all three cities.
      * ``neighborhood``  — NYC (borough) and LA (incorporated / postal city).
                            Empty for Chicago, whose feed has no area signal.
      * ``facility_type`` — Chicago only, as a canonical bucket. Descriptive use
                            only: DR 0004 bars it as a MODEL feature while keeping
                            facility type as a group-performance dimension.

    Consumers must treat every one of these as optional. The chart tool drops a
    column that is empty across all rows rather than offering a filter that
    silently matches nothing.
    """
    out = df.copy()
    out["neighborhood"] = _area_series(out)
    out["zip"] = _clean_zip(out["zip"]) if "zip" in out.columns else ""
    out["facility_type"] = (
        out["facility_type"].map(normalize_facility_type).fillna("")
        if "facility_type" in out.columns
        else ""
    )
    return out


def build_scores_table(
    model,
    features: pd.DataFrame,
    feature_columns: Sequence[str],
    *,
    n_drivers: int = 4,
    keep_columns: tuple = ("license_id", "dba_name", "address", "lat", "lon"),
    contributions_fn=None,
    trend_scores=None,
    closure_status: pd.DataFrame | None = None,
    base_rate: float = CHICAGO_BASE_RATE,
) -> pd.DataFrame:
    """Produce the scores table for every restaurant in ``features``.

    Aggregation strategy: one row per ``license_id``, anchored on the most
    recent inspection. The ``trend_slope`` is the OLS slope over the license's
    last ``TREND_K_VISITS`` inspections (see DR 0011).

    ``trend_scores`` (optional) is a per-row series of forecast-only model scores
    aligned to ``features`` — the forward-looking basis for the trend (the
    forecast model ignores each visit's own pass/fail, so a failed inspection and
    its required re-check don't dominate the slope). When given, the slope is fit
    over those; when omitted (e.g. the secondary LogReg path), it falls back to
    the production ``risk_score``, which is still last-K but not forward-looking.

    Args:
        model: fitted estimator with ``.predict_proba``. The same model that
            was persisted to ``data/models/<name>.joblib``.
        features: full ``features.parquet`` content (multi-row per restaurant
            allowed — we score each row, then pick the latest per license).
        feature_columns: the ``ALL_FEATURES`` list from
            ``foodsafety.models.baseline``. Needed both for predict_proba
            input and for SHAP attribution column ordering.
        n_drivers: number of top drivers to include per restaurant.
        keep_columns: which raw display columns to copy through to the
            scores table (used by the UI).
        closure_status: per-license frame from :func:`out_of_business_status`.
            When omitted every row is marked active — callers producing the
            real contract artifact must pass it (DR 0014).
    """
    df = features.copy()
    df["inspection_date"] = pd.to_datetime(df["inspection_date"])

    # Ensure lat/lon are renamed / present per the contract.
    if "lat" not in df.columns and "latitude" in df.columns:
        df["lat"] = df["latitude"]
    if "lon" not in df.columns and "longitude" in df.columns:
        df["lon"] = df["longitude"]

    # Score every inspection — needed for trend computation.
    X = df[list(feature_columns)]
    df["risk_score"] = model.predict_proba(X)[:, 1]

    # Forward-looking trend basis: the forecast-only model's per-inspection score
    # (aligned to `features` by position). Falls back to risk_score when absent.
    df["_trend_score"] = (
        np.asarray(trend_scores) if trend_scores is not None else df["risk_score"].to_numpy()
    )

    # Per-restaurant aggregation. First collapse each license to its most recent
    # inspection, then collapse licenses that belong to the same physical
    # establishment (name + address) — a reopen/renewal mints a new license_id,
    # so a license-only dedup lists the same restaurant twice (a stale ghost next
    # to the live entry). Sorted by inspection_date, so keep="last" keeps the
    # most-recently-inspected license per establishment; the closure flag below
    # then applies to that survivor (DR 0014).
    latest = df.sort_values("inspection_date")
    latest_per_license = latest.drop_duplicates("license_id", keep="last").copy()
    latest_per_license["_establishment_key"] = _establishment_key(latest_per_license)
    latest_per_license = (
        latest_per_license.drop_duplicates("_establishment_key", keep="last")
        .drop(columns="_establishment_key")
        .copy()
    )

    # SHAP attribution for the latest-anchor rows. Done in one batched call
    # against the latest set rather than the full feature frame.
    # Per-feature attribution for the latest-anchor rows. Defaults to the linear
    # (LogReg) explainer; the XGB serve path injects a TreeSHAP-based fn that
    # returns the same (rows × original_features) log-odds contribution frame.
    latest_X = latest_per_license[list(feature_columns)]
    if contributions_fn is None:
        contributions = linear_contributions(
            model, latest_X, original_features=list(feature_columns)
        )
    else:
        contributions = contributions_fn(latest_X)

    # Build top_drivers list per row.
    drivers_per_row: list[list[dict]] = []
    for idx, row in latest_per_license.iterrows():
        row_values = row[feature_columns]
        row_contribs = contributions.loc[idx]
        drivers = top_drivers_for_row(row_values, row_contribs, k=n_drivers)
        drivers_per_row.append([d.to_dict() for d in drivers])
    latest_per_license["top_drivers"] = drivers_per_row

    # Trend slope over the last K visits, on the forecast-only score (DR 0011).
    latest_per_license["trend_slope"] = _compute_trend_slopes(
        df, latest_per_license, score_col="_trend_score"
    )

    # Tier (unified rule, DR 0017) + as_of_date. Thresholds are stashed on the
    # frame's .attrs so the producer can persist them to methodology.json.
    tiers, applied_thresholds = assign_risk_tiers(latest_per_license["risk_score"], base_rate)
    latest_per_license["risk_tier"] = tiers
    latest_per_license["as_of_date"] = latest_per_license["inspection_date"]

    # Closure status (DR 0014). Licenses absent from the closure frame — and
    # every license when no frame is given — count as active.
    if closure_status is not None:
        joined = latest_per_license["license_id"].map(closure_status["is_out_of_business"])
        latest_per_license["is_out_of_business"] = joined.fillna(False).astype(bool)
        latest_per_license["closed_since"] = latest_per_license["license_id"].map(
            closure_status["closed_since"]
        )
    else:
        latest_per_license["is_out_of_business"] = False
        latest_per_license["closed_since"] = pd.NaT

    # Display geography. Kept out of keep_columns so callers passing their own
    # keep_columns still get them: these are contract fields, not caller-selectable
    # display extras.
    latest_per_license = add_display_geography(latest_per_license)

    # Output schema per contract.
    output_cols = list(keep_columns) + [
        *DISPLAY_GEOGRAPHY_COLUMNS,
        "as_of_date",
        "risk_score",
        "risk_tier",
        "top_drivers",
        "trend_slope",
        "is_out_of_business",
        "closed_since",
    ]
    result = latest_per_license[output_cols].reset_index(drop=True)
    result.attrs["risk_tier_thresholds"] = applied_thresholds
    return result


def _compute_trend_slopes(
    full_scored: pd.DataFrame,
    latest_per_license: pd.DataFrame,
    *,
    score_col: str = "risk_score",
    k_visits: int = TREND_K_VISITS,
) -> pd.Series:
    """OLS slope of ``score_col`` over each license's last ``k_visits`` inspections.

    For each license, take the ``k_visits`` most recent inspections up to and
    including its anchor, fit an OLS regression of ``score_col`` on date offset
    (in days), and return the slope coefficient. Returns NaN if fewer than 2
    points or the points share a date.

    Last-K *visits* (not a fixed calendar window) is what gives the trend broad
    coverage — almost any license with >=2 inspections gets a slope — and
    ``score_col`` is normally the forecast-only model's score, so the slope is
    not driven by the mandated fail->re-inspection swing in the production score.
    See DR 0011 and docs/model-experiments.md (2026-06-28).
    """
    slopes: list[float] = []
    full_indexed = full_scored.set_index("license_id").sort_values("inspection_date")
    for license_id, anchor_date in latest_per_license[["license_id", "inspection_date"]].itertuples(
        index=False
    ):
        # All inspections at this license — pandas .loc lookup is fast.
        try:
            subset = full_indexed.loc[[license_id]]
        except KeyError:
            slopes.append(np.nan)
            continue

        # The last k_visits inspections up to (and including) the anchor date.
        upto = subset[subset["inspection_date"] <= anchor_date].tail(k_visits)
        if len(upto) < 2:
            slopes.append(np.nan)
            continue

        x_days = (upto["inspection_date"] - upto["inspection_date"].min()).dt.days.to_numpy(
            dtype=float
        )
        if np.ptp(x_days) == 0:  # all on the same day -> no slope
            slopes.append(np.nan)
            continue
        y = upto[score_col].to_numpy(dtype=float)
        # np.polyfit returns highest-order coefficient first; degree 1 → [slope, intercept].
        try:
            slope = float(np.polyfit(x_days, y, deg=1)[0])
        except (np.linalg.LinAlgError, ValueError):
            slope = float("nan")
        slopes.append(slope)
    return pd.Series(slopes, index=latest_per_license.index)


def write_scores_json(
    scores: pd.DataFrame,
    out_path,
    *,
    schema_version: str = "0.2.0",
    model_version: str = "baseline_logreg_sigmoid",
    label_window_days: int = 180,
    totals: dict | None = None,
    calibration: dict | None = None,
    risk_tier_thresholds: list[tuple[float, str]] | None = None,
) -> None:
    """Convert ``scores.parquet`` to the JSON the Next.js app reads.

    Schema matches ``app/public/data/scores_mock.json`` minus the
    ``_is_mock`` field — that omission is what makes the web app drop the
    demo banner automatically when this file replaces the mock.

    ``calibration`` is the Platt triple ``{a, b, intercept}`` shipped ONCE at
    the top level (not per row). The detail page reconstructs each
    establishment's calibrated-log-odds waterfall from it plus the per-row
    ``risk_score`` and ``top_drivers`` shap values — so the full waterfall costs
    three floats total, not a payload field per restaurant.
    """
    import json

    from foodsafety.io import storage

    df = scores.copy()
    df["as_of_date"] = pd.to_datetime(df["as_of_date"]).dt.strftime("%Y-%m-%d")
    df["risk_score"] = df["risk_score"].round(4)
    df["trend_slope"] = df["trend_slope"].astype(float).round(6)
    if "is_out_of_business" not in df.columns:
        # Pre-0.6.0 scores.parquet (no closure columns) — treat all as active.
        df["is_out_of_business"] = False
        df["closed_since"] = pd.NaT
    df["closed_since"] = pd.to_datetime(df["closed_since"]).dt.strftime("%Y-%m-%d")

    if totals is None:
        tier_counts = df["risk_tier"].value_counts().to_dict()
        # Trend counts cover ACTIVE venues only — a closed business can't be
        # "worsening", and the homepage renders these numbers (DR 0014).
        active_slope = df.loc[~df["is_out_of_business"], "trend_slope"].fillna(0)
        totals = {
            "establishments": int(len(df)),
            "tier_counts": {
                "Low": int(tier_counts.get("Low", 0)),
                "Moderate": int(tier_counts.get("Moderate", 0)),
                "Elevated": int(tier_counts.get("Elevated", 0)),
                "High": int(tier_counts.get("High", 0)),
            },
            "out_of_business": int(df["is_out_of_business"].sum()),
            # Establishments trending worse / better by the last-K-visits
            # forecast slope (DR 0011), among ACTIVE venues only — a closed
            # business can't be "worsening" (DR 0014). No window in the key name:
            # the slope is a visit-count trend, not a calendar window, and K is
            # tunable, so a window/K suffix would go stale on a retune. The
            # ±TREND_STABLE_BAND cutoff matches the web app's trendDirection so
            # these counts equal the number of establishments the app labels
            # worsening / improving.
            "worsening": int((active_slope > TREND_STABLE_BAND).sum()),
            "improving": int((active_slope < -TREND_STABLE_BAND).sum()),
        }

    payload = {
        "schema_version": schema_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of_date": df["as_of_date"].max(),
        "is_mock": False,
        "model_version": model_version,
        "label_window_days": label_window_days,
        "totals": totals,
        "calibration": calibration,
        # Unified tier cutoffs actually used this run (DR 0017), so the
        # methodology page reports the real bands without recomputing p98.
        "risk_tier_thresholds": (
            [[float(t), name] for t, name in risk_tier_thresholds]
            if risk_tier_thresholds is not None
            else None
        ),
        "scores": [_row_to_json(r) for r in df.itertuples(index=False)],
    }

    # out_path may be a local path or an s3:// URI — route through storage.
    storage.write_text(json.dumps(payload, separators=(",", ":")), out_path)


def _display_str(value) -> str:
    """A display string for scores.json: never null, never padded."""
    return "" if value is None or pd.isna(value) else str(value).strip()


def _row_to_json(row) -> dict:
    # Strip surrounding whitespace on the display strings at this JSON boundary:
    # some source dba_name/address values carry leading spaces (e.g.
    # "  JIMMY FAMOUS BURGER"), which sort ahead of the "A"s in the app's A–Z
    # list. Normalising here keeps every consumer of scores.json clean.
    return {
        "license_id": str(row.license_id),
        "dba_name": _display_str(row.dba_name),
        "address": _display_str(row.address),
        # Derived in build_scores_table from the feed's own area/zip columns.
        # neighborhood is empty for a single-city feed like Chicago's, which the
        # chart tool's live-filter guard then drops rather than offering a filter
        # that matches nothing.
        "neighborhood": _display_str(getattr(row, "neighborhood", "")),
        "zip": _display_str(getattr(row, "zip", "")),
        "facility_type": _display_str(getattr(row, "facility_type", "")),
        "lat": None if pd.isna(row.lat) else float(row.lat),
        "lon": None if pd.isna(row.lon) else float(row.lon),
        "as_of_date": str(row.as_of_date),
        "risk_score": float(row.risk_score),
        "risk_tier": str(row.risk_tier),
        "trend_slope": (None if pd.isna(row.trend_slope) else float(row.trend_slope)),
        "trend_ci_low": None,
        "trend_ci_high": None,
        "top_drivers": list(row.top_drivers) if row.top_drivers is not None else [],
        "is_out_of_business": bool(row.is_out_of_business),
        "closed_since": (None if pd.isna(row.closed_since) else str(row.closed_since)),
    }
