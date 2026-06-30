"""Feature presentation registry — ONE source of truth for how a feature reads.

This module is pure text with no ML dependencies, so label consumers (the batch
scorer, the methodology builder, the modeling notebook) can import it without
pulling in numpy / pandas / sklearn via ``shap_drivers``. The attribution math
lives in ``shap_drivers`` and imports the registry from here.

Each feature has two presentational forms, kept together so they can't drift:
  • ``name``  — a generic, value-free label for the GLOBAL feature-impact chart
    (model card / methodology page), which ranks features across the whole
    population, so there is no single value to show.
  • ``label`` — the PER-ROW driver label. Usually a ``{value}`` format template
    filled with the row's value; numeric features show the value, boolean
    keyword flags only render when True (the False case is suppressed at the
    caller), category features show the triggering category.

A few binary OUTCOME features (e.g. ``was_fail``) read oppositely for the pass
vs fail case and surface in BOTH directions — a fail pushes risk up, a pass
pulls it down. A single template can't say both, so their ``label`` is a
``{True: ..., False: ...}`` dict chosen by the row's value at render time.

The per-row labels are what end up on the restaurant detail page next to the
horizontal driver bars; they were tuned for the Clinical Quiet mockup's tone —
neutral, not alarmist. ``FEATURE_LABELS`` and ``display_name()`` below are
DERIVED from this registry, so the global and per-row views stay in sync.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeaturePresentation:
    name: str
    label: str | dict[bool, str]


FEATURES: dict[str, FeaturePresentation] = {
    "prior_inspections": FeaturePresentation(
        "Prior inspections on record", "{value} prior inspections on record"
    ),
    "prior_fails": FeaturePresentation(
        "Prior failed inspections", "{value} failed inspections previously"
    ),
    "prior_priority_violations": FeaturePresentation(
        "Prior priority violations", "{value} priority violations in prior history"
    ),
    "prior_core_violations": FeaturePresentation(
        "Prior core violations", "{value} core violations in prior history"
    ),
    "prior_fail_or_priority_events": FeaturePresentation(
        "Prior fail-or-priority events", "{value} prior fail-or-priority events"
    ),
    "prior_pass_w_conditions": FeaturePresentation(
        "Prior 'Pass with conditions' results", "{value:.0f} prior 'Pass with conditions' results"
    ),
    "prior_reinspections": FeaturePresentation(
        "Prior re-inspections", "{value:.0f} prior re-inspections"
    ),
    "prior_complaint_inspections": FeaturePresentation(
        "Prior complaint-driven inspections", "{value:.0f} prior complaint-driven inspections"
    ),
    "prior_fails_365d": FeaturePresentation(
        "Failed inspections in the last year", "{value:.0f} failed inspections in the last year"
    ),
    "prior_priority_violations_365d": FeaturePresentation(
        "Priority violations in the last year",
        "{value:.0f} priority violations in the last year",
    ),
    "prev_priority_violations": FeaturePresentation(
        "Priority violations at previous inspection",
        "{value:.0f} priority violations at the previous inspection",
    ),
    "priority_violation_trend": FeaturePresentation(
        "Trend in priority violations", "Recent trend in priority violations"
    ),
    "days_since_last_inspection": FeaturePresentation(
        "Days since last inspection", "Last inspected {value:.0f} days ago"
    ),
    "days_since_last_fail": FeaturePresentation(
        "Days since last failure", "Last fail was {value:.0f} days ago"
    ),
    "license_age_days": FeaturePresentation("License age", "License is {value:.0f} days old"),
    "license_n_history_rows": FeaturePresentation(
        "License history entries", "{value} entries in license history"
    ),
    "temporal_month": FeaturePresentation("Month of inspection", "Anchored in month {value}"),
    "temporal_quarter": FeaturePresentation("Quarter of inspection", "Anchored in Q{value}"),
    "static_facility_type": FeaturePresentation("Facility type", "Facility type: {value}"),
    "static_risk_tier": FeaturePresentation("Chicago risk tier", "Chicago risk tier: {value}"),
    "static_inspection_type": FeaturePresentation("Inspection type", "Inspection type: {value}"),
    "static_zip": FeaturePresentation("ZIP code", "ZIP {value}"),
    # Current-inspection own outcome + code counts (observed at as_of_date; the
    # 180-day label window is strictly after). These are the model's strongest
    # drivers, so they must read clearly for both the fail and the pass case.
    "n_priority_this_inspection": FeaturePresentation(
        "Priority violations at this inspection",
        "{value:.0f} priority violations at this inspection",
    ),
    "n_core_this_inspection": FeaturePresentation(
        "Core violations at this inspection", "{value:.0f} core violations at this inspection"
    ),
    "was_fail": FeaturePresentation(
        "Outcome of the current inspection",
        {True: "Failed the current inspection", False: "Passed the current inspection"},
    ),
    "last_was_fail": FeaturePresentation(
        "Previous inspection outcome",
        {True: "Previous inspection was a fail", False: "Previous inspection passed"},
    ),
    # Boolean flag labels (per-row only rendered when value is True).
    "flag_kw_temperature": FeaturePresentation(
        "Temperature violation (recent text)", "Temperature-related violation in recent history"
    ),
    "flag_kw_cooling": FeaturePresentation(
        "Improper cooling (recent text)", "Improper cooling cited"
    ),
    "flag_kw_raw_food": FeaturePresentation(
        "Raw-food handling (recent text)", "Raw-food handling issue cited"
    ),
    "flag_kw_cross_contamination": FeaturePresentation(
        "Cross-contamination (recent text)", "Cross-contamination concerns"
    ),
    "flag_kw_expired": FeaturePresentation(
        "Expired food / date-marking (recent text)", "Expired food / date-marking issue"
    ),
    "flag_kw_rodent": FeaturePresentation(
        "Rodent / vermin (recent text)", "Vermin / rodent violation noted"
    ),
    "flag_kw_pest": FeaturePresentation("Pest activity (recent text)", "Pest activity noted"),
    "flag_kw_no_soap": FeaturePresentation(
        "No soap at handwash sink (recent text)", "Missing soap at handwash sink"
    ),
    "flag_kw_no_paper_towels": FeaturePresentation(
        "No paper towels (recent text)", "Missing paper towels at handwash sink"
    ),
    "flag_kw_handwash_sink": FeaturePresentation(
        "Handwashing-sink issue (recent text)", "Handwashing-sink issue"
    ),
    "flag_kw_sewage": FeaturePresentation(
        "Sewage / plumbing (recent text)", "Sewage / plumbing issue"
    ),
    "flag_kw_certified_manager": FeaturePresentation(
        "Certified-manager issue (recent text)", "Certified-manager certification issue"
    ),
    # Block-face building-violation features were reverted (not in ALL_FEATURES) —
    # they failed the both-metrics gate under CV. Their driver labels are removed
    # with them; re-add here if the feature is ever promoted.
    # Citywide NOAA weather features — present here so the A/B's leave-one-out
    # attribution reads clearly. Not yet in ALL_FEATURES; see WEATHER_FEATURES
    # in baseline.py and docs/model-experiments.md.
    "prior_tmax_3d_avg": FeaturePresentation(
        "3-day average high temperature", "3-day average high of {value:.0f}°C"
    ),
    "prior_tmin_3d_avg": FeaturePresentation(
        "3-day average low temperature", "3-day average low of {value:.0f}°C"
    ),
    "prior_precip_7d_sum": FeaturePresentation(
        "7-day total precipitation", "{value:.0f}mm of rain in the last 7 days"
    ),
    "prior_heat_days_30d": FeaturePresentation(
        "Hot days in the last 30 days", "{value:.0f} days over 90°F in the last 30 days"
    ),
    "prior_freeze_days_30d": FeaturePresentation(
        "Freezing days in the last 30 days",
        "{value:.0f} days below freezing in the last 30 days",
    ),
}

# Derived view — the per-row label map. Existing call sites (top_drivers_for_row,
# predict_batch, notebook 06, the tests) import FEATURE_LABELS unchanged.
FEATURE_LABELS: dict[str, str | dict[bool, str]] = {k: v.label for k, v in FEATURES.items()}


def display_name(feature: str) -> str:
    """Plain-English, value-free name for a feature in the global chart; falls
    back to the raw key so a newly-added feature still renders (un-prettified)."""
    return FEATURES[feature].name if feature in FEATURES else feature
