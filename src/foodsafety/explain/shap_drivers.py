"""SHAP-style per-feature attribution for the linear baseline.

For a calibrated logistic-regression pipeline, the "SHAP" decomposition has a
closed form: each feature's contribution is ``coef * scaled_value`` in
log-odds space. This is the exact local additive explanation (same as
``shap.LinearExplainer`` would produce for a linear model). We roll our own
in ~30 lines rather than pull the ``shap`` package — fewer dependencies, and
the math is uncomplicated.

For the XGBoost model we'd use ``shap.TreeExplainer`` (different code path);
since we shipped baseline as production, that path stays in the Phase-6
backlog.

Two product surfaces depend on this module:

  1. **The restaurant detail page** — top 3-5 drivers per restaurant, with
     plain-English labels.
  2. **The model card** — global feature impact (mean |contribution|), for the
     research write-up.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

# ---------------------------------------------------------------------------
# Plain-English labels for the UI driver bars.
# ---------------------------------------------------------------------------
#
# Most entries are a format template: ``{value}`` is filled in with the row's
# value for that feature. Numeric features show the value; boolean keyword flags
# only render when True (the False case is suppressed at the caller); category
# features show the actual category that triggered.
#
# A few binary OUTCOME features (e.g. ``was_fail``) read oppositely for the
# pass vs fail case and surface in BOTH directions — a fail pushes risk up, a
# pass pulls it down. A single template can't say both, so those map to a
# ``{True: ..., False: ...}`` dict chosen by the row's value at render time.
#
# These strings are what end up on the restaurant detail page next to the
# horizontal driver bars. They were tuned for the Clinical Quiet mockup's
# tone — neutral, not alarmist.
FEATURE_LABELS: dict[str, str | dict[bool, str]] = {
    "prior_inspections": "{value} prior inspections on record",
    "prior_fails": "{value} failed inspections previously",
    "prior_priority_violations": "{value} priority violations in prior history",
    "prior_core_violations": "{value} core violations in prior history",
    "prior_fail_or_priority_events": "{value} prior fail-or-priority events",
    "prior_pass_w_conditions": "{value:.0f} prior 'Pass with conditions' results",
    "prior_reinspections": "{value:.0f} prior re-inspections",
    "prior_complaint_inspections": "{value:.0f} prior complaint-driven inspections",
    "prior_fails_365d": "{value:.0f} failed inspections in the last year",
    "prior_priority_violations_365d": "{value:.0f} priority violations in the last year",
    "prev_priority_violations": "{value:.0f} priority violations at the previous inspection",
    "priority_violation_trend": "Recent trend in priority violations",
    "days_since_last_inspection": "Last inspected {value:.0f} days ago",
    "days_since_last_fail": "Last fail was {value:.0f} days ago",
    "license_age_days": "License is {value:.0f} days old",
    "license_n_history_rows": "{value} entries in license history",
    "temporal_month": "Anchored in month {value}",
    "temporal_quarter": "Anchored in Q{value}",
    "static_facility_type": "Facility type: {value}",
    "static_risk_tier": "Chicago risk tier: {value}",
    "static_inspection_type": "Inspection type: {value}",
    "static_zip": "ZIP {value}",
    # Current-inspection own outcome + code counts (observed at as_of_date; the
    # 180-day label window is strictly after). These are the model's strongest
    # drivers, so they must read clearly for both the fail and the pass case.
    "n_priority_this_inspection": "{value:.0f} priority violations at this inspection",
    "n_core_this_inspection": "{value:.0f} core violations at this inspection",
    "was_fail": {True: "Failed the current inspection", False: "Passed the current inspection"},
    "last_was_fail": {True: "Previous inspection was a fail", False: "Previous inspection passed"},
    # Boolean flag labels (only rendered when value is True)
    "flag_kw_temperature": "Temperature-related violation in recent history",
    "flag_kw_cooling": "Improper cooling cited",
    "flag_kw_raw_food": "Raw-food handling issue cited",
    "flag_kw_cross_contamination": "Cross-contamination concerns",
    "flag_kw_expired": "Expired food / date-marking issue",
    "flag_kw_rodent": "Vermin / rodent violation noted",
    "flag_kw_pest": "Pest activity noted",
    "flag_kw_no_soap": "Missing soap at handwash sink",
    "flag_kw_no_paper_towels": "Missing paper towels at handwash sink",
    "flag_kw_handwash_sink": "Handwashing-sink issue",
    "flag_kw_sewage": "Sewage / plumbing issue",
    "flag_kw_certified_manager": "Certified-manager certification issue",
}


@dataclass(frozen=True)
class Driver:
    """One row of the top-drivers list, ready for JSON serialization."""

    feature: str
    value: str
    shap: float
    label: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "feature": self.feature,
            "value": self.value,
            "shap": round(self.shap, 4),
            "label": self.label,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# Linear explainer
# ---------------------------------------------------------------------------


def _underlying_pipeline(model) -> Pipeline:
    """Pull the inner Pipeline out of a calibrated wrapper.

    Training wraps the fitted pipeline in ``FrozenEstimator`` before
    calibration, so for a ``CalibratedClassifierCV`` the pipeline lives at
    ``model.calibrated_classifiers_[0].estimator.estimator``. We unwrap the
    FrozenEstimator layer if present. Other shapes are returned unchanged.
    """
    if isinstance(model, CalibratedClassifierCV):
        inner = model.calibrated_classifiers_[0].estimator
        if isinstance(inner, FrozenEstimator):
            inner = inner.estimator
        return inner
    return model


def linear_contributions(
    model,
    X: pd.DataFrame,
    original_features: list[str],
) -> pd.DataFrame:
    """Per-feature contributions in log-odds space for every row in ``X``.

    Returns a DataFrame of shape ``(len(X), len(original_features))`` with the
    same row index as ``X`` and ``original_features`` as columns. For each
    cell, the value is the additive contribution of that ORIGINAL feature to
    the linear (log-odds) prediction.

    For one-hot expanded categorical features (e.g., ``static_zip`` becomes
    60+ columns after the OneHotEncoder), we sum the contributions of all
    its expansions to attribute back to the original column. That keeps the
    per-feature view interpretable.
    """
    pipeline = _underlying_pipeline(model)
    if not isinstance(pipeline, Pipeline):
        raise TypeError(f"Expected sklearn Pipeline, got {type(pipeline).__name__}")

    preprocess: ColumnTransformer = pipeline.named_steps["preprocess"]
    logreg: LogisticRegression = pipeline.named_steps["model"]

    X_processed = preprocess.transform(X)
    if hasattr(X_processed, "toarray"):  # sparse → dense (small N for prediction)
        X_processed = X_processed.toarray()
    coef = logreg.coef_[0]  # binary classifier → 1D

    # Element-wise: contribution per expanded column.
    expanded_contributions = X_processed * coef  # (n_rows, n_expanded_cols)

    output_names = preprocess.get_feature_names_out()

    # Map each expanded-column name back to its original feature so the
    # per-row contributions can be summed.
    expanded_to_original = _map_expanded_to_original(output_names, original_features)

    # Sum into a DataFrame with original-feature columns.
    contrib_df = pd.DataFrame(0.0, index=X.index, columns=original_features, dtype="float64")
    for j, expanded_name in enumerate(output_names):
        orig = expanded_to_original.get(expanded_name)
        if orig is None:
            continue
        contrib_df[orig] += expanded_contributions[:, j]

    return contrib_df


def _map_expanded_to_original(
    expanded_names: np.ndarray, original_features: list[str]
) -> dict[str, str]:
    """Build a lookup ``expanded_column_name → original_feature_name``.

    ColumnTransformer prefixes outputs with the transformer name:
      - ``num__prior_fails`` → ``prior_fails``
      - ``bool__flag_kw_pest`` → ``flag_kw_pest``
      - ``cat__static_zip_60614`` → ``static_zip``

    For the categorical case we strip the transformer prefix, then find the
    longest match in ``original_features`` that is a prefix of the remaining
    string. ZIPs are numeric and unambiguous; facility types contain spaces
    and that's why we match by longest prefix rather than splitting on ``_``.
    """
    mapping: dict[str, str] = {}
    originals_sorted = sorted(original_features, key=len, reverse=True)

    for name in expanded_names:
        if name.startswith(("num__", "bool__")):
            stripped = name.split("__", 1)[1]
            if stripped in original_features:
                mapping[name] = stripped
            continue
        if name.startswith("cat__"):
            stripped = name.split("__", 1)[1]
            for orig in originals_sorted:
                if stripped.startswith(orig):
                    mapping[name] = orig
                    break
            continue
        # passthrough columns appear unprefixed in some sklearn versions
        if name in original_features:
            mapping[name] = name

    return mapping


def top_drivers_for_row(
    row_values: pd.Series,
    row_contributions: pd.Series,
    *,
    k: int = 4,
    labels: Mapping[str, str | Mapping[bool, str]] | None = None,
) -> list[Driver]:
    """Pick the top-K drivers for one restaurant.

    "Top" means largest absolute log-odds contribution. We prefer **positive**
    contributions (features that push risk UP) but include negative ones if
    they're materially large, since "no prior fails" is a legitimate driver
    too.

    Boolean flag features only render when they fired (True). A False flag
    contributes 0 to log-odds anyway, so it's correctly excluded by the
    magnitude sort, but this also keeps the labelling tidy if there's a
    rounding artefact.
    """
    labels = labels or FEATURE_LABELS

    # Hide boolean-False rows from drivers (their contribution is 0; suppress
    # any near-zero negative noise that might rank in the top-K).
    eligible_mask = []
    for feat in row_contributions.index:
        if feat.startswith("flag_kw_"):
            eligible_mask.append(bool(row_values.get(feat, False)))
        else:
            eligible_mask.append(True)
    eligible = pd.Series(eligible_mask, index=row_contributions.index)

    # Rank by magnitude over the eligible features.
    contribs = row_contributions.where(eligible, 0.0)
    ranked = contribs.reindex(contribs.abs().sort_values(ascending=False).index)
    top = ranked.head(k)

    drivers: list[Driver] = []
    for feat, shap_val in top.items():
        if abs(shap_val) < 1e-6:
            continue  # don't show purely-zero contributors
        raw_value = row_values.get(feat)
        label_template = labels.get(feat, feat)
        if isinstance(label_template, Mapping):
            # Sign-aware label for a binary outcome feature: the same feature
            # reads oppositely for the fail vs pass case (and surfaces in both).
            label = label_template.get(bool(raw_value), feat)
        else:
            try:
                label = label_template.format(value=raw_value)
            except (TypeError, ValueError):
                label = label_template
        drivers.append(
            Driver(
                feature=feat,
                value=str(raw_value),
                shap=float(shap_val),
                label=label,
            )
        )
    return drivers
