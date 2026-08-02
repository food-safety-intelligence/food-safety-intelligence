"""The ``AuditFrame`` contract — the city-agnostic seam of the fairness audit.

Every city adapter emits a frame with these columns; the census join and the
metrics engine read only these columns and never touch a city's raw schema. This
is the same "normalise, then process" seam pattern the repo uses elsewhere
(``io.storage`` for local-vs-S3).

One row per evaluated ``(establishment, as_of_date)`` in the **chronological test
split** with a *realised* label — NOT the forward-looking served ``scores.json``
(whose labels are not yet known, so FPR / FNR / calibration are undefined on it).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd

from foodsafety.audit import config

# Columns the adapter must provide (before the census join adds the area_* fields).
BASE_COLUMNS: dict[str, str] = {
    "city": "string",
    "license_id": "string",
    "as_of_date": "datetime64[ns]",
    "y_true": "int8",  # realised 180d fail-or-priority label
    "y_score": "float64",  # Model 1 calibrated risk
    "risk_tier": "string",  # Low / Moderate / Elevated / High
    "lat": "float64",
    "lon": "float64",
    "facility_type_norm": "string",
    "license_age_days": "float64",
    "neighborhood": "string",
    "cuisine": "string",  # may be all-null where a city has no cuisine source
    # Model 2 (forecast) — optional; present only for the calibration/coverage lens.
    "forecast_score": "float64",
}

# Columns the census join (census.py) adds. Quantile columns are ordered category
# labels (e.g. "Q1 (lowest)"..); dominant-group is a plain category.
CENSUS_COLUMNS: tuple[str, ...] = (
    "tract_geoid",
    "area_income_q",
    "area_pct_nonwhite_q",
    "area_dominant_group",
    "area_pct_poverty_q",
    "area_pct_foreign_born_q",
    "area_pct_limited_english_q",
)


def add_tenure_bucket(df: pd.DataFrame) -> pd.DataFrame:
    """Add the new-vs-established ``tenure_bucket`` from ``license_age_days``.

    Rows with unknown license age (NaN — license never seen in history) get a
    dedicated "unknown" bucket rather than being dropped, so coverage is honest.
    """
    out = df.copy()
    cut = pd.cut(
        out["license_age_days"],
        bins=list(config.TENURE_BINS_DAYS),
        labels=list(config.TENURE_LABELS),
        right=False,
    ).astype("object")
    out["tenure_bucket"] = pd.Series(cut, index=out.index).fillna("unknown").astype("string")
    return out


def quantile_bucket(values: pd.Series, *, bins: int = config.QUANTILE_BINS) -> pd.Series:
    """Within-city quantile labels for a continuous demographic column.

    Returns an ordered categorical "Q1 (lowest)".."Q{bins} (highest)". Uses rank
    so ties don't collapse a quantile edge; NaN stays NaN (its own "unknown" group
    is applied by the caller when grouping).
    """
    labels = [f"Q{i + 1}" for i in range(bins)]
    labels[0] = "Q1 (lowest)"
    labels[-1] = f"Q{bins} (highest)"
    ranked = values.rank(method="first")
    q = pd.qcut(ranked, q=bins, labels=labels)
    return q.astype("category")


def validate(df: pd.DataFrame, *, require_census: bool = False) -> None:
    """Raise if the frame breaks the contract. Cheap, called at adapter boundaries."""
    missing = [c for c in BASE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"AuditFrame missing base columns: {missing}")
    if require_census:
        missing_c = [c for c in CENSUS_COLUMNS if c not in df.columns]
        if missing_c:
            raise ValueError(f"AuditFrame missing census columns: {missing_c}")
    bad = set(np.unique(df["y_true"].dropna())) - {0, 1}
    if bad:
        raise ValueError(f"y_true must be 0/1, saw {sorted(bad)}")
    tiers = set(df["risk_tier"].dropna().unique())
    known = {"Low", "Moderate", "Elevated", "High"}
    if not tiers <= known:
        raise ValueError(f"risk_tier has unknown values: {sorted(tiers - known)}")


@runtime_checkable
class CityAdapter(Protocol):
    """A per-city producer of the test-split ``AuditFrame`` (pre-census-join).

    Implementations own all city-specific loading: the temporal split, the served
    model, and the joins that attach lat/lon, facility type, license age,
    neighborhood, and (where available) cuisine. They must NOT attach any census
    demographic column — that is ``census.py``'s job, kept separate so the
    audit-only rule is structurally obvious.
    """

    city: str

    def build_audit_frame(self) -> pd.DataFrame:
        """Return the test-split frame satisfying ``BASE_COLUMNS``."""
        ...
