"""Feature-table orchestrator.

``build_features`` reads the contract inputs (the labeled inspections table
and the raw 311 complaints table), runs each feature module in turn, and
returns the modelling-ready DataFrame.

Row filter applied at the END of the build, not at the start:
  * Burn-in (pre-2019) inspections are KEPT during feature computation so
    they can contribute to ``prior_*`` aggregates at later inspections.
  * They are DROPPED from the returned DataFrame because they can't be
    trained on (no label).
  * Rows with non-modelable results (Out of Business, No Entry, etc.) and
    placeholder license tokens are also dropped at the end.

This separation between "keep for priors" and "use for training" is the
whole point of the burn-in design. If we filtered earlier we'd lose the
prior history at the start of 2019.

See CLAUDE.md § "Code style" — every ``.shift()`` / ``< as_of_date`` guard
must be commented with WHY. The feature modules called from here document
their own leak guards. This orchestrator just stitches them together.
"""

from __future__ import annotations

import pandas as pd

from foodsafety.features.complaint_features import add_complaint_features
from foodsafety.features.inspection_features import add_inspection_features
from foodsafety.features.keyword_flags import add_keyword_flags
from foodsafety.features.license_features import add_license_features
from foodsafety.features.license_history_features import add_license_history_features
from foodsafety.features.temporal_features import add_temporal_features
from foodsafety.utils.geo import flag_and_null_out_of_bbox


MODELABLE_RESULTS = frozenset({"Pass", "Pass w/ Conditions", "Fail"})


def build_features(
    inspections_labeled: pd.DataFrame,
    complaints: pd.DataFrame | None = None,
    licenses_historical: pd.DataFrame | None = None,
    *,
    drop_burnin: bool = True,
    drop_invalid_license: bool = True,
    drop_non_modelable: bool = True,
    drop_right_truncated: bool = False,
) -> pd.DataFrame:
    """End-to-end feature build.

    Args:
        inspections_labeled: output of ``foodsafety.data.labels.build_labels``.
            Must include ``license_id``, ``inspection_date``, ``results``,
            ``violations``, ``is_burnin``, ``is_fail_or_priority``, label.
        complaints: 311 dataframe (``complaints_311.parquet``). If None,
            the complaint features are skipped — handy for tests.
        licenses_historical: optional Business Licenses history dataframe.
            If None, license-history features are skipped.
        drop_burnin: drop rows with ``is_burnin=True`` from output.
        drop_invalid_license: drop rows with ``license_id`` in {"", "0"}.
        drop_non_modelable: drop rows whose ``results`` is not in
            ``MODELABLE_RESULTS``.
        drop_right_truncated: drop rows whose forward 180-day window extends
            past the dataset max date. Those labels are under-counted (we
            haven't observed the full window yet) so they bias eval metrics
            — but the FEATURES are valid for scoring. Default ``False`` so
            the parquet preserves them; the trainer filters them out before
            train/val/test, then scores against the full set.

    Returns:
        New DataFrame. Original inputs not mutated.
    """
    df = inspections_labeled.copy()
    df["inspection_date"] = pd.to_datetime(df["inspection_date"])

    # Build prior-history features FIRST. These use all rows including
    # burn-in (the whole reason burn-in exists is to feed `prior_*`).
    df = add_inspection_features(df)

    # Static facility metadata — cheap and leak-safe.
    df = add_license_features(df)

    # NLP layer B keyword flags.
    df = add_keyword_flags(df)

    # Calendar / seasonality features (no external join needed).
    df = add_temporal_features(df)

    # Spatial 311 counts (BallTree 300m). Skipped if no complaints provided.
    if complaints is not None:
        df = add_complaint_features(df, complaints)

    # License history (age + activity). Skipped if no historical-licenses df provided.
    if licenses_historical is not None:
        df = add_license_history_features(df, licenses_historical)

    # Add as_of_date as a synonym of inspection_date — per contract the row
    # key is (license_id, as_of_date). We set them equal here so the contract
    # is honoured without changing semantics; the +1d convention discussed in
    # docs/interface_contracts.md is purely notational.
    df["as_of_date"] = df["inspection_date"]

    # --- Output filter --------------------------------------------------
    if drop_burnin:
        df = df[~df["is_burnin"]]
    if drop_invalid_license:
        df = df[~df["license_id"].isin({"", "0"})]
    if drop_non_modelable:
        df = df[df["results"].isin(MODELABLE_RESULTS)]
    if drop_right_truncated:
        # Anchors whose 180-day forward window extends past the dataset's
        # latest inspection date have under-counted labels: any future Fail
        # we haven't observed becomes a silent 0. Keep them out of training
        # AND eval — otherwise held-out metrics are biased (the test split is
        # the most affected since it's the most recent slice; on the current
        # snapshot about half of the test rows are right-truncated).
        df = df[~df["right_truncated"]]

    # Geo sanity: flag + null (don't drop) any coords outside the Chicago bbox.
    # A bad geocode is a broken display field, not a reason to drop a valid
    # inspection — nulling routes it into the same missing-geo path the map and
    # 311 join already handle (skip the pin / count 0), instead of misplacing a
    # pin or computing a wrong spatial count. lat/lon aren't model features.
    df = flag_and_null_out_of_bbox(df)

    return df.reset_index(drop=True)
