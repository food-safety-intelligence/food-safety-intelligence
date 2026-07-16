"""Business-license history features.

Joins ``data/raw/licenses_historical.parquet`` to each inspection anchor and
derives leak-safe summaries of the license's history *as of* the anchor's
inspection date.

Two features land here in Phase 5 (more possible later):

  * ``license_age_days`` — days from the license's first known issuance to
    the anchor's inspection date. A 30-day-old restaurant looks different
    from a 30-year-old institution.
  * ``license_n_history_rows`` — count of historical license records (any
    application_type) at or before the anchor date. Proxies "renewal and
    status-change activity to date". A facility with one row has never
    renewed; one with twenty has gone through many cycles.

Experimental (not in ``ALL_FEATURES`` — see ``models.baseline.
ALCOHOL_TOBACCO_FEATURES``): ``has_alcohol_license`` / ``has_tobacco_license``,
prompted by CDPH's own model reportedly weighting these two license types
above the environmental features this project already rejected (see
docs/model-experiments.md). Both are "ever held this license type by the
anchor date" booleans, matched on ``license_description`` (Chicago's alcohol
licenses aren't one code: ``Tavern``, ``Consumption on Premises - Incidental
Activity``, ``Package Goods``, and the caterer's-liquor / special-event-liquor
variants all count).

**Leak guard**: we filter the historical table to ``date_issued <
inspection_date`` before aggregating. Renewals filed after the inspection
can't be visible to the model at inspection time.

**License-status as-of inspection date** is deferred — it requires the
"latest status at-or-before anchor" pattern (similar to the ffill-shift dance
in inspection_features.py). The simpler counts are more useful in Phase 5
and easier to validate.
"""

from __future__ import annotations

import pandas as pd

# license_description substrings (case-insensitive) that denote an alcohol or
# tobacco license. Chicago splits alcohol across several license types rather
# than one code — confirmed against the unfiltered licenses_current.parquet,
# since licenses_historical.parquet's own server-side pull filter (see
# foodsafety.config._FOOD_LICENSE_WHERE) has to list the same substrings to
# even fetch these rows.
_ALCOHOL_DESC_MARKERS: tuple[str, ...] = (
    "TAVERN",
    "LIQUOR",
    "CONSUMPTION ON PREMISES",
    "PACKAGE GOODS",
)
_TOBACCO_DESC_MARKERS: tuple[str, ...] = ("TOBACCO",)


def _first_marker_date(hist: pd.DataFrame, license_col: str, markers: tuple[str, ...]) -> pd.Series:
    """Earliest ``date_issued`` per license among rows whose ``license_description``
    contains any of ``markers`` (case-insensitive). Missing from the result for a
    license that never held a matching license type.
    """
    upper_desc = hist["license_description"].astype("string").str.upper()
    mask = pd.Series(False, index=hist.index)
    for m in markers:
        mask |= upper_desc.str.contains(m, na=False)
    return hist.loc[mask].groupby(license_col)["date_issued"].min()


def add_license_history_features(
    inspections: pd.DataFrame,
    licenses_historical: pd.DataFrame,
    *,
    license_col_inspections: str = "license_id",
    license_col_historical: str = "license_number",
    date_col: str = "inspection_date",
) -> pd.DataFrame:
    """Append per-anchor license history features.

    Args:
        inspections: must contain ``license_id`` and ``inspection_date``.
        licenses_historical: from ``data/raw/licenses_historical.parquet``.
            Required columns: ``license_number``, ``date_issued``. We use
            ``date_issued`` as the canonical "issuance event date" — it's
            populated on every row regardless of application_type.

    Returns: new DataFrame with the inspections columns plus:
        license_age_days        : Float32 (NaN if license never seen in history)
        license_n_history_rows  : Int32 (count up to and including anchor date;
                                          0 if no history at or before anchor)
        has_alcohol_license     : bool (experimental — see module docstring)
        has_tobacco_license     : bool (experimental — see module docstring)
    """
    out = inspections.copy()
    out[date_col] = pd.to_datetime(out[date_col])

    hist = licenses_historical.copy()
    hist[license_col_historical] = hist[license_col_historical].astype("string")
    hist["date_issued"] = pd.to_datetime(hist["date_issued"], errors="coerce")
    hist = hist.dropna(subset=["date_issued", license_col_historical])

    # First-issuance date per license — used for license_age_days.
    first_issued = hist.groupby(license_col_historical)["date_issued"].min().rename("_first_issued")

    # We need history-row counts strictly BEFORE the anchor's inspection
    # date. Build a per-license sorted list of date_issued; for each anchor,
    # use searchsorted to find how many issuances precede it.
    out["_inspection_date"] = out[date_col]
    out["_license_for_join"] = out[license_col_inspections].astype("string")

    # Attach first issuance to compute license age.
    out = out.merge(
        first_issued,
        left_on="_license_for_join",
        right_index=True,
        how="left",
    )
    out["license_age_days"] = (out["_inspection_date"] - out["_first_issued"]).dt.days.astype(
        "Float32"
    )

    # has_alcohol_license / has_tobacco_license: "ever held this license type
    # strictly before the anchor date" — same leak guard as license_age_days,
    # just gated on a matching license_description rather than any row.
    # licenses_historical always carries license_description (it's the column
    # the ingest WHERE filter itself matches on); a caller passing a minimal
    # frame without it (e.g. a unit-test fixture) degrades to all-False rather
    # than raising, matching license_age_days' NaN-degrade-on-missing pattern.
    if "license_description" in hist.columns:
        first_alcohol = _first_marker_date(hist, license_col_historical, _ALCOHOL_DESC_MARKERS)
        first_tobacco = _first_marker_date(hist, license_col_historical, _TOBACCO_DESC_MARKERS)
    else:
        first_alcohol = pd.Series(dtype="datetime64[ns]")
        first_tobacco = pd.Series(dtype="datetime64[ns]")

    out = out.merge(
        first_alcohol.rename("_first_alcohol"),
        left_on="_license_for_join",
        right_index=True,
        how="left",
    ).merge(
        first_tobacco.rename("_first_tobacco"),
        left_on="_license_for_join",
        right_index=True,
        how="left",
    )
    out["has_alcohol_license"] = (out["_first_alcohol"] < out["_inspection_date"]).fillna(False)
    out["has_tobacco_license"] = (out["_first_tobacco"] < out["_inspection_date"]).fillna(False)

    # Per-license sorted issuance dates → vectorised searchsorted.
    sorted_issuances = (
        hist.sort_values([license_col_historical, "date_issued"])
        .groupby(license_col_historical)["date_issued"]
        .apply(list)
    )

    # Map and count: how many issuances at this license have date_issued <
    # inspection_date? searchsorted with side='left' gives strict-less-than
    # count when applied to a sorted ascending array.
    def _count_before(license_id, anchor_date):
        issuances = sorted_issuances.get(license_id)
        if issuances is None:
            return 0
        # Use numpy searchsorted on the sorted python list-of-Timestamps —
        # cast to ndarray once; the per-row cost is small.
        import numpy as np

        arr = np.asarray(issuances, dtype="datetime64[ns]")
        return int(np.searchsorted(arr, anchor_date.to_datetime64(), side="left"))

    out["license_n_history_rows"] = [
        _count_before(lic, d)
        for lic, d in zip(out["_license_for_join"], out["_inspection_date"], strict=True)
    ]
    out["license_n_history_rows"] = out["license_n_history_rows"].astype("Int32")

    return out.drop(
        columns=[
            "_inspection_date",
            "_license_for_join",
            "_first_issued",
            "_first_alcohol",
            "_first_tobacco",
        ]
    )
