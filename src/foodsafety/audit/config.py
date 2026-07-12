"""Audit configuration — grouping axes, ACS variable registry, tolerance bands.

Single source of truth for *what* the fairness audit measures and *what counts as
a flag*. The audit engine (``fairness.py``) and the census join (``census.py``)
read these registries so the same rules apply to every city.

Design notes:
  * Continuous demographic variables are bucketed into **within-city quantiles**
    so "low-income tract" is relative to each city and comparable across the three.
  * Exact ACS 5-year variable codes are NOT hardcoded here — they are resolved and
    validated against the Census data dictionary in ``census.py``. This registry
    carries the concept + table family + how to bucket it, which is stable; the
    numeric codes are an implementation detail that changes between ACS vintages.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Operating point: what "flagged" means for FPR / FNR / statistical parity.
# The models emit a continuous risk plus a discretised tier (Low / Moderate /
# Elevated / High, from serve.predict_batch.assign_risk_tiers). We audit the
# disparity users actually experience, so "flagged" = the deployed High tier.
# Elevated+High is carried as a secondary cut (a wider worklist).
# --------------------------------------------------------------------------- #
FLAGGED_TIERS_PRIMARY: frozenset[str] = frozenset({"High"})
FLAGGED_TIERS_SECONDARY: frozenset[str] = frozenset({"Elevated", "High"})

# Top-K cross-check: a threshold-free view aligned with the existing
# precision@k / recall@k convention in models.evaluate.group_performance_audit.
TOP_K_FRAC: float = 0.10

# --------------------------------------------------------------------------- #
# Noise floors. Small / low-prevalence groups swing on base rate, not bias
# (the recurring lesson — decision 0005). A group is only *audited* above these
# floors, and a gap is only called a finding when its bootstrap CI clears the
# tolerance band below.
# --------------------------------------------------------------------------- #
MIN_GROUP_N: int = 50
MIN_GROUP_POSITIVES: int = 50  # treat sub-~50-positive groups as noise
N_BOOTSTRAP: int = 1000  # seeded by config.RANDOM_STATE in fairness.py

# --------------------------------------------------------------------------- #
# Tolerance bands — the line between "gap" and "finding".
# --------------------------------------------------------------------------- #
# Statistical parity: the four-fifths rule. A group's flag rate below 80% (or the
# most-flagged group's rate above 125%) of the reference is a disparate-impact flag.
DISPARATE_IMPACT_RATIO_MIN: float = 0.80
# Equalized odds: absolute FPR / FNR gap (max - min across audited groups) that we
# treat as material once the CI excludes it.
FPR_GAP_MAX: float = 0.10
FNR_GAP_MAX: float = 0.10
# Calibration: absolute gap in expected calibration error across groups.
ECE_GAP_MAX: float = 0.05


# --------------------------------------------------------------------------- #
# Grouping axes.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Axis:
    """One way to slice the population for the disparity metrics.

    ``column`` is the audit-frame column carrying the group label. ``primary``
    axes get the full battery (parity + FPR/FNR + calibration); non-primary axes
    are reported as tract-level correlations only (see README — keeps the audit
    out of multiple-comparisons soup).
    """

    key: str
    label: str
    column: str
    primary: bool
    note: str = ""


AXES: tuple[Axis, ...] = (
    # Geographic region — city-specific boundary set (Chicago community area,
    # NYC neighborhood tabulation area / borough, LA neighborhood). Also the
    # boundary set that backs a future user-facing neighborhood filter.
    Axis("neighborhood", "Neighborhood", "neighborhood", primary=True),
    # Area (residential) demographics from the census join — the honest read of
    # "customer demographics": the tract population where the establishment sits,
    # not its actual patrons.
    Axis("income", "Area median household income", "area_income_q", primary=True),
    Axis("race_nonwhite", "Area % non-white", "area_pct_nonwhite_q", primary=True),
    Axis("race_dominant", "Area dominant group", "area_dominant_group", primary=True),
    Axis("poverty", "Area % below poverty", "area_pct_poverty_q", primary=True),
    Axis("foreign_born", "Area % foreign-born", "area_pct_foreign_born_q", primary=True),
    Axis(
        "limited_english",
        "Area % limited-English households",
        "area_pct_limited_english_q",
        primary=True,
        note="immigrant-community / language-access lens (over-scrutiny question)",
    ),
    # Establishment attributes (no census needed).
    Axis(
        "cuisine",
        "Cuisine",
        "cuisine",
        primary=True,
        note="NYC native; Chicago/LA OSM-derived, caveated",
    ),
    Axis("tenure", "New vs established", "tenure_bucket", primary=True),
    Axis("facility_type", "Facility type", "facility_type_norm", primary=True),
)


# --------------------------------------------------------------------------- #
# New-vs-established buckets, from license_age_days (features.license_history).
# The <1yr bucket isolates the ~9% cold-start slice.
# --------------------------------------------------------------------------- #
TENURE_BINS_DAYS: tuple[float, ...] = (0, 365, 1095, float("inf"))
TENURE_LABELS: tuple[str, ...] = ("new (<1yr)", "established (1-3yr)", "mature (3yr+)")


# --------------------------------------------------------------------------- #
# ACS 5-year variable registry.
#   kind="continuous"  -> bucketed into within-city quantiles (QUANTILE_BINS)
#   kind="composition" -> the dominant-group categorical (race/ethnicity)
# `primary` variables feed the grouping axes above; the rest are reported as
# tract-level correlations with flag rate / miscalibration (README § Metrics).
# --------------------------------------------------------------------------- #
QUANTILE_BINS: int = 4  # quartiles by default


@dataclass(frozen=True)
class AcsVar:
    key: str
    label: str
    table_family: str  # ACS table the concept comes from; exact code pinned in census.py
    kind: str  # "continuous" | "composition"
    primary: bool
    note: str = ""


ACS_VARS: tuple[AcsVar, ...] = (
    # --- primary: the protected-class core ---
    AcsVar("median_hh_income", "Median household income", "B19013", "continuous", primary=True),
    AcsVar("pct_nonwhite", "% non-white", "B03002", "continuous", primary=True),
    AcsVar(
        "dominant_group",
        "Dominant race/ethnicity",
        "B03002",
        "composition",
        primary=True,
        note="majority White / Black / Hispanic / Asian / none",
    ),
    AcsVar("pct_poverty", "% below poverty line", "B17001", "continuous", primary=True),
    AcsVar("pct_foreign_born", "% foreign-born", "B05002", "continuous", primary=True),
    AcsVar(
        "pct_limited_english", "% limited-English households", "C16002", "continuous", primary=True
    ),
    # --- secondary: reported as tract-level correlations, not group cuts ---
    AcsVar("pct_no_hs_diploma", "% no high-school diploma", "B15003", "continuous", primary=False),
    AcsVar(
        "pct_bachelors_plus", "% bachelor's degree or higher", "B15003", "continuous", primary=False
    ),
    AcsVar(
        "pct_renter_occupied", "% renter-occupied housing", "B25003", "continuous", primary=False
    ),
    AcsVar("median_gross_rent", "Median gross rent", "B25064", "continuous", primary=False),
    AcsVar("median_home_value", "Median home value", "B25077", "continuous", primary=False),
    AcsVar("unemployment_rate", "Unemployment rate", "B23025", "continuous", primary=False),
    AcsVar("pct_snap", "% households receiving SNAP", "B22010", "continuous", primary=False),
    AcsVar(
        "pop_density",
        "Population density",
        "B01003",
        "continuous",
        primary=False,
        note="also carried as a confound — dense tracts hold more establishments",
    ),
    AcsVar(
        "pct_under_5",
        "% residents under 5",
        "B01001",
        "continuous",
        primary=False,
        note="foodborne-illness-vulnerable residents",
    ),
    AcsVar(
        "pct_65_plus",
        "% residents 65+",
        "B01001",
        "continuous",
        primary=False,
        note="foodborne-illness-vulnerable residents",
    ),
)


def primary_acs_vars() -> tuple[AcsVar, ...]:
    return tuple(v for v in ACS_VARS if v.primary)


def secondary_acs_vars() -> tuple[AcsVar, ...]:
    return tuple(v for v in ACS_VARS if not v.primary)
