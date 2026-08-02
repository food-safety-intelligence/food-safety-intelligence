"""Smoke tests for batch scoring (``foodsafety.serve.predict_batch``).

This is the module that produces ``scores.parquet`` — the cross-team contract
artifact the whole web app depends on. It had no test before: a regression here
ships a broken (or schema-drifted) scores file to production with nothing to
catch it. These tests fit a tiny real baseline pipeline on synthetic features
and assert the end-to-end output, rather than mocking the model, so the SHAP
attribution and trend paths are actually exercised.

What's pinned down:
  - **Output schema** — exactly the contract columns, one row per license.
  - **Latest-inspection anchor** — the row kept per license is its most recent.
  - **top_drivers** — a JSON-ready list of dicts, never raw column names.
  - **Trend** — null with <2 points in the 90-day window, a float with >=2.
  - **JSON conversion** — ``write_scores_json`` emits the app's payload shape.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from foodsafety.models.baseline import ALL_FEATURES, LABEL_COL, build_baseline_pipeline
from foodsafety.serve.predict_batch import (
    DISPLAY_GEOGRAPHY_COLUMNS,
    TREND_STABLE_BAND,
    _area_series,
    _clean_zip,
    _row_to_json,
    add_display_geography,
    assign_risk_tiers,
    build_scores_table,
    out_of_business_status,
    score_to_tier,
    tier_thresholds,
    write_scores_json,
)

KEEP_COLUMNS = ("license_id", "dba_name", "address", "lat", "lon")
CONTRACT_COLUMNS = [
    *KEEP_COLUMNS,
    # Display geography, derived from the feed rather than caller-supplied, so it
    # sits outside KEEP_COLUMNS. Empty string is a legal value for both.
    "neighborhood",
    "zip",
    "facility_type",
    "as_of_date",
    "risk_score",
    "risk_tier",
    "top_drivers",
    "trend_slope",
    "is_out_of_business",
    "closed_since",
]


def _make_features(n_licenses: int = 40, seed: int = 42) -> pd.DataFrame:
    """Synthetic ``features.parquet``-shaped frame covering every model column.

    Most licenses get a single inspection; two licenses (``L0`` and ``L1``) get
    three inspections inside a 90-day window so the trend path has >=2 points.
    """
    rng = np.random.default_rng(seed)
    rows: list[dict] = []

    def base_row(lic: str, date: pd.Timestamp) -> dict:
        row: dict = {
            "license_id": lic,
            "dba_name": f"Restaurant {lic}",
            "address": f"{rng.integers(100, 9999)} W Example St",
            "lat": 41.8 + rng.normal(scale=0.05),
            "lon": -87.6 + rng.normal(scale=0.05),
            "inspection_date": date,
            LABEL_COL: int(rng.random() < 0.3),  # both classes present
        }
        for feat in ALL_FEATURES:
            if feat.startswith("flag_kw_"):
                row[feat] = int(rng.random() < 0.2)
            elif feat == "static_risk_tier":
                row[feat] = rng.choice(["Risk 1 (High)", "Risk 2 (Medium)", "Risk 3 (Low)"])
            elif feat == "static_inspection_type":
                row[feat] = rng.choice(["Canvass", "Complaint", "Re-Inspection"])
            elif feat == "was_fail" or feat == "last_was_fail":
                row[feat] = int(rng.random() < 0.4)
            else:
                row[feat] = float(rng.integers(0, 20))
        return row

    # Two multi-inspection licenses (for the trend path).
    for lic in ("L0", "L1"):
        for offset in (60, 30, 0):  # all within 90 days of the latest
            rows.append(base_row(lic, pd.Timestamp("2024-06-01") - pd.Timedelta(days=offset)))

    # The rest get a single inspection each.
    for i in range(2, n_licenses):
        rows.append(base_row(f"L{i}", pd.Timestamp("2024-05-15")))

    return pd.DataFrame(rows)


def _fit_model(features: pd.DataFrame):
    # min_frequency=1 so the small synthetic categories aren't all collapsed.
    pipeline = build_baseline_pipeline(onehot_min_frequency=1)
    pipeline.fit(features[ALL_FEATURES], features[LABEL_COL])
    return pipeline


def test_scores_table_has_exact_contract_schema():
    features = _make_features()
    model = _fit_model(features)
    scores = build_scores_table(model, features, ALL_FEATURES)

    assert list(scores.columns) == CONTRACT_COLUMNS


def test_one_row_per_license_anchored_on_latest():
    features = _make_features()
    model = _fit_model(features)
    scores = build_scores_table(model, features, ALL_FEATURES)

    # One row per license, no duplicates.
    assert scores["license_id"].is_unique
    assert len(scores) == features["license_id"].nunique()

    # The multi-inspection licenses anchor on their most recent date.
    l0 = scores.loc[scores["license_id"] == "L0", "as_of_date"].iloc[0]
    assert pd.Timestamp(l0) == pd.Timestamp("2024-06-01")


def test_risk_score_and_tier_are_valid():
    features = _make_features()
    model = _fit_model(features)
    scores = build_scores_table(model, features, ALL_FEATURES)

    assert scores["risk_score"].between(0.0, 1.0).all()
    assert set(scores["risk_tier"]).issubset({"Low", "Moderate", "Elevated", "High"})
    # Tier must be the discretisation of the score under the unified-rule thresholds
    # this run actually used (recorded on the frame's .attrs — DR 0017).
    thresholds = scores.attrs["risk_tier_thresholds"]
    for _, row in scores.iterrows():
        assert row["risk_tier"] == score_to_tier(row["risk_score"], thresholds)


def test_top_drivers_are_json_ready_dicts():
    features = _make_features()
    model = _fit_model(features)
    scores = build_scores_table(model, features, ALL_FEATURES, n_drivers=4)

    for drivers in scores["top_drivers"]:
        assert isinstance(drivers, list)
        assert len(drivers) <= 4
        for d in drivers:
            assert isinstance(d, dict)
            assert {"feature", "value", "shap", "label"} <= d.keys()
            # A label must never be a raw model column name.
            assert d["label"] != d["feature"] or d["feature"] not in ALL_FEATURES


def test_trend_slope_null_for_single_inspection_float_for_series():
    features = _make_features()
    model = _fit_model(features)
    scores = build_scores_table(model, features, ALL_FEATURES)

    # L0 has three in-window inspections -> a real slope.
    l0_slope = scores.loc[scores["license_id"] == "L0", "trend_slope"].iloc[0]
    assert pd.notna(l0_slope)
    assert isinstance(float(l0_slope), float)

    # A single-inspection license -> NaN (fewer than 2 points).
    l5_slope = scores.loc[scores["license_id"] == "L5", "trend_slope"].iloc[0]
    assert pd.isna(l5_slope)


def test_write_scores_json_emits_app_payload(tmp_path):
    features = _make_features()
    model = _fit_model(features)
    scores = build_scores_table(model, features, ALL_FEATURES)

    out = tmp_path / "scores.json"
    write_scores_json(scores, str(out), calibration={"a": 1.0, "b": 0.0, "intercept": 0.0})

    payload = json.loads(out.read_text())
    assert payload["is_mock"] is False
    assert payload["schema_version"]
    assert payload["totals"]["establishments"] == len(scores)
    assert len(payload["scores"]) == len(scores)

    first = payload["scores"][0]
    assert {"license_id", "risk_score", "risk_tier", "top_drivers"} <= first.keys()
    # Dates are serialised as ISO strings, not timestamps.
    assert isinstance(first["as_of_date"], str)


def test_totals_trend_counts_use_stable_band(tmp_path):
    # totals.worsening / .improving must count with TREND_STABLE_BAND (the same
    # cutoff the web app's trendDirection uses), so the header counts equal the
    # number of establishments the app labels worsening / improving. A wider band
    # (the pre-DR-0011 0.001) would silently undercount vs the displayed labels.
    features = _make_features()
    model = _fit_model(features)
    scores = build_scores_table(model, features, ALL_FEATURES).copy()

    b = TREND_STABLE_BAND
    # Straddle the band: 2 clearly worsening, 1 clearly improving; a slope just
    # inside the band, exactly 0, and null must all read as stable (uncounted).
    controlled = [2 * b, 2 * b, -2 * b, b / 2, -b / 2, 0.0, None]
    col = (controlled + [0.0] * len(scores))[: len(scores)]
    scores["trend_slope"] = col

    out = tmp_path / "scores.json"
    write_scores_json(scores, str(out), calibration={"a": 1.0, "b": 0.0, "intercept": 0.0})
    totals = json.loads(out.read_text())["totals"]

    assert totals["worsening"] == 2
    assert totals["improving"] == 1


def test_row_to_json_strips_whitespace_on_display_strings():
    # Source data carries names like "  JIMMY FAMOUS BURGER" with leading
    # spaces; the JSON boundary must strip them so the app's A–Z sort doesn't
    # float those names above the "A"s.
    df = pd.DataFrame(
        [
            {
                "license_id": "L1",
                "dba_name": "  JIMMY FAMOUS BURGER",
                "address": "  123 W Example St  ",
                "lat": 41.9,
                "lon": -87.6,
                "as_of_date": pd.Timestamp("2026-06-01"),
                "risk_score": 0.5,
                "risk_tier": "Moderate",
                "trend_slope": None,
                "top_drivers": [],
                "is_out_of_business": False,
                "closed_since": None,
            }
        ]
    )
    row = next(df.itertuples(index=False))
    out = _row_to_json(row)
    assert out["dba_name"] == "JIMMY FAMOUS BURGER"
    assert out["address"] == "123 W Example St"


# ---------------------------------------------------------------------------
# Out-of-business status (DR 0014)
# ---------------------------------------------------------------------------


def _make_labeled_events() -> pd.DataFrame:
    """Minimal ``inspections_labeled``-shaped event stream (all event types)."""
    return pd.DataFrame(
        [
            # L0: pass, then found closed — latest event wins.
            {"license_id": "L0", "inspection_date": "2024-01-10", "results": "Pass"},
            {"license_id": "L0", "inspection_date": "2025-01-13", "results": "Out of Business"},
            # L1: old closure, then reopened/passed — NOT closed (latest is Pass).
            {"license_id": "L1", "inspection_date": "2023-05-01", "results": "Out of Business"},
            {"license_id": "L1", "inspection_date": "2024-03-01", "results": "Pass"},
            # L2: latest is No Entry — not a closure signal.
            {"license_id": "L2", "inspection_date": "2024-06-01", "results": "No Entry"},
            # L3: Business Not Located counts as closed.
            {
                "license_id": "L3",
                "inspection_date": "2024-07-04",
                "results": "Business Not Located",
            },
        ]
    )


def test_out_of_business_status_uses_latest_event_only():
    status = out_of_business_status(_make_labeled_events())

    assert status.loc["L0", "is_out_of_business"]
    assert status.loc["L0", "closed_since"] == pd.Timestamp("2025-01-13")
    # A closure followed by a later Pass means the license is active.
    assert not status.loc["L1", "is_out_of_business"]
    assert pd.isna(status.loc["L1", "closed_since"])
    # "No Entry" is not a closure.
    assert not status.loc["L2", "is_out_of_business"]
    assert status.loc["L3", "is_out_of_business"]


def test_scores_table_carries_closure_and_defaults_active():
    features = _make_features()
    model = _fit_model(features)

    closure = out_of_business_status(
        pd.DataFrame(
            [
                {"license_id": "L0", "inspection_date": "2025-01-13", "results": "Out of Business"},
                {"license_id": "L1", "inspection_date": "2024-03-01", "results": "Pass"},
            ]
        )
    )
    scores = build_scores_table(model, features, ALL_FEATURES, closure_status=closure)

    by_lic = scores.set_index("license_id")
    assert bool(by_lic.loc["L0", "is_out_of_business"])
    assert by_lic.loc["L0", "closed_since"] == pd.Timestamp("2025-01-13")
    assert not bool(by_lic.loc["L1", "is_out_of_business"])
    # Licenses absent from the closure frame default to active, not NaN.
    assert not bool(by_lic.loc["L5", "is_out_of_business"])
    assert scores["is_out_of_business"].dtype == bool

    # No closure frame at all -> every row active (test/dev convenience path).
    scores_none = build_scores_table(model, features, ALL_FEATURES)
    assert not scores_none["is_out_of_business"].any()


def test_write_scores_json_closure_fields_and_active_only_trend_counts(tmp_path):
    features = _make_features()
    model = _fit_model(features)
    closure = out_of_business_status(
        pd.DataFrame(
            # L0 is one of the two multi-inspection licenses, so it has a real
            # trend slope — closing it must remove it from the trend counts.
            [{"license_id": "L0", "inspection_date": "2025-01-13", "results": "Out of Business"}]
        )
    )
    scores = build_scores_table(model, features, ALL_FEATURES, closure_status=closure)

    out = tmp_path / "scores.json"
    write_scores_json(scores, str(out), calibration={"a": 1.0, "b": 0.0, "intercept": 0.0})
    payload = json.loads(out.read_text())

    assert payload["totals"]["out_of_business"] == 1
    rows = {r["license_id"]: r for r in payload["scores"]}
    assert rows["L0"]["is_out_of_business"] is True
    assert rows["L0"]["closed_since"] == "2025-01-13"
    assert rows["L5"]["is_out_of_business"] is False
    assert rows["L5"]["closed_since"] is None

    # Trend counts must cover active venues only: recompute from the rows.
    active = [r for r in payload["scores"] if not r["is_out_of_business"]]
    expected_worsening = sum(1 for r in active if (r["trend_slope"] or 0) > TREND_STABLE_BAND)
    assert payload["totals"]["worsening"] == expected_worsening


def test_reopened_license_collapses_to_one_establishment_row():
    """A physical establishment holding two license_ids appears once.

    A reopen/renewal mints a new license_id at the same name + address, which a
    license-only dedup would list twice (a stale ghost beside the live entry).
    The most-recently-inspected license wins. A same-name chain at a *different*
    address must stay a separate row, and normalisation (case + trailing space)
    must not defeat the collapse.
    """
    features = _make_features()
    model = _fit_model(features)

    # Clone a single-inspection license into a NEW license_id at the SAME name +
    # address but a later inspection date — the reopen case. Vary case and add a
    # trailing space to prove normalisation collapses them.
    old = features[features["license_id"] == "L5"].copy()
    reopened = old.copy()
    reopened["license_id"] = "L5_REOPEN"
    reopened["inspection_date"] = old["inspection_date"].iloc[0] + pd.Timedelta(days=200)
    reopened["dba_name"] = old["dba_name"].iloc[0].lower()
    reopened["address"] = old["address"].iloc[0].upper() + "  "

    # Same name, different address (a chain) — must NOT be merged.
    chain = old.copy()
    chain["license_id"] = "L5_CHAIN"
    chain["address"] = "999 Other Ave"

    combined = pd.concat([features, reopened, chain], ignore_index=True)
    scores = build_scores_table(model, combined, ALL_FEATURES)
    ids = set(scores["license_id"])

    # Reopened pair collapses to the most-recently-inspected license.
    assert "L5_REOPEN" in ids
    assert "L5" not in ids
    # The chain at a different address survives on its own.
    assert "L5_CHAIN" in ids

    # No physical establishment (normalised name + address) is listed twice.
    est = (
        scores["dba_name"].str.upper().str.replace(r"\s+", " ", regex=True).str.strip()
        + "|"
        + scores["address"].str.upper().str.replace(r"\s+", " ", regex=True).str.strip()
    )
    assert est.is_unique


# ---------------------------------------------------------------------------
# Unified cross-city tier rule (DR 0017)
# ---------------------------------------------------------------------------


def test_tier_thresholds_are_multiples_of_base_rate():
    # Low = 0.5x base, Moderate = 1x base; High = max(2x base, p98). Here 2x base
    # (0.216) dominates the small p98 (0.20), so High cuts at 0.216.
    thr = tier_thresholds(0.108, 0.20)
    assert thr == [(0.054, "Low"), (0.108, "Moderate"), (0.216, "Elevated"), (1.01, "High")]


def test_tier_thresholds_high_cut_uses_p98_when_it_dominates():
    # For a low-base city with a long right tail, p98 (0.31) exceeds 2x base
    # (0.174), so High is capped at the top ~2% — keeping it small, not a big slice.
    thr = tier_thresholds(0.087, 0.31)
    assert thr[2] == (0.31, "Elevated")  # High cut = max(0.174, 0.31)
    assert thr[0] == (0.0435, "Low")


def test_assign_risk_tiers_labels_and_thresholds():
    scores = pd.Series([0.01, 0.08, 0.15, 0.95])
    tiers, thr = assign_risk_tiers(scores, base_rate=0.108)
    # p98 of this tiny series is ~0.95, so High cut = max(0.216, ~0.95) -> ~0.95.
    assert thr[0] == (0.054, "Low") and thr[1] == (0.108, "Moderate")
    # 0.01 < 0.054 Low; 0.08 in [0.054,0.108) Moderate; 0.15 Elevated; 0.95 top.
    assert list(tiers) == ["Low", "Moderate", "Elevated", "High"]


def test_assign_risk_tiers_high_stays_rare_for_a_low_base_city():
    # A low-base distribution with a right tail: the p98 cap keeps High ~2%,
    # instead of a fixed 2x-base cut sweeping many merely-above-average venues in.
    import numpy as np

    scores = pd.Series(np.concatenate([np.full(980, 0.03), np.linspace(0.1, 0.6, 20)]))
    tiers, _ = assign_risk_tiers(scores, base_rate=0.087)
    high_share = (tiers == "High").mean()
    assert high_share <= 0.03


# ---------------------------------------------------------------------------
# Display geography (neighborhood / zip)
#
# These columns shipped empty in every city for months: `_row_to_json` hardcoded
# "" and no test looked. The chart tool advertised them as filters, so every
# neighborhood chart silently returned an empty frame. The tests below pin the
# derivation AND the empty case, because empty is a legitimate value for one city
# and a bug in another — only asserting the source-shape distinction separates them.
# ---------------------------------------------------------------------------


def test_area_series_uses_nyc_borough_column():
    df = pd.DataFrame({"boro": ["Manhattan", "Brooklyn", "Queens", "Manhattan"]})
    assert list(_area_series(df)) == ["Manhattan", "Brooklyn", "Queens", "Manhattan"]


def test_area_series_prefers_borough_over_city():
    # NYC carries both; boro is the meaningful area, city is not.
    df = pd.DataFrame({"city": ["NEW YORK"] * 3, "boro": ["Bronx", "Queens", "Bronx"]})
    assert list(_area_series(df)) == ["Bronx", "Queens", "Bronx"]


def test_area_series_title_cases_shouted_la_city_names():
    df = pd.DataFrame({"city": ["LOS ANGELES", "WEST HOLLYWOOD", "SANTA MONICA"]})
    assert list(_area_series(df)) == ["Los Angeles", "West Hollywood", "Santa Monica"]


def test_area_series_is_empty_for_a_single_city_feed():
    # Chicago's feed has a `city` column, but it says CHICAGO on ~every row, so it
    # distinguishes nothing. A dead filter is worse than no filter: it returns an
    # empty frame with no error, which reads as "no such places in this city".
    df = pd.DataFrame({"city": ["CHICAGO"] * 999 + ["EVANSTON"]})
    assert set(_area_series(df)) == {""}


def test_area_series_ignores_typo_variants_when_measuring_dominance():
    # The real Chicago feed has Cchicago / CHicago / CHICAGOCHICAGO. Counting
    # DISTINCT values would see variety (54 of them) and wrongly keep the column;
    # dominance case-folds so the variants collapse onto the dominant value.
    df = pd.DataFrame({"city": ["CHICAGO"] * 900 + ["chicago"] * 60 + ["CHicago"] * 40})
    assert set(_area_series(df)) == {""}


def test_area_series_blanks_placeholder_values():
    # NYC's boro column uses "0" for unknown; it must not become a label.
    df = pd.DataFrame({"boro": ["Manhattan", "0", "Brooklyn", "Manhattan"]})
    assert list(_area_series(df)) == ["Manhattan", "", "Brooklyn", "Manhattan"]


def test_area_series_empty_when_no_source_column_exists():
    df = pd.DataFrame({"license_id": ["L0", "L1"]})
    assert list(_area_series(df)) == ["", ""]


def test_clean_zip_keeps_five_digits_and_drops_the_rest():
    raw = pd.Series(["60614", "60614-1234", " 90210 ", "", None, "ABCDE", "123"])
    assert list(_clean_zip(raw)) == ["60614", "60614", "90210", "", "", "", ""]


def test_row_to_json_emits_derived_geography_not_placeholders():
    # The exact regression: these three keys were hardcoded to "" here, discarding
    # whatever the scores table had computed.
    features = _make_features()
    model = _fit_model(features)
    scores = build_scores_table(model, features, ALL_FEATURES)
    scores["neighborhood"] = "Brooklyn"
    scores["zip"] = "11201"
    scores["facility_type"] = "Restaurant"

    row = next(scores.itertuples(index=False))
    payload = _row_to_json(row)

    assert payload["neighborhood"] == "Brooklyn"
    assert payload["zip"] == "11201"
    assert payload["facility_type"] == "Restaurant"


def test_facility_type_collapses_the_vulnerable_population_families():
    # normalize_facility_type consolidates the families the fairness audit cares
    # about (the Daycare family alone spans ~20 raw spellings). Descriptive use
    # only — DR 0004 keeps facility type as a group-performance dimension while
    # barring it as a model feature.
    features = _make_features()
    features["facility_type"] = ["DAYCARE (2 - 6 YEARS)", "Day Care 1023"] * (len(features) // 2)
    model = _fit_model(features)
    scores = build_scores_table(model, features, ALL_FEATURES)

    assert set(scores["facility_type"]) == {"Daycare"}


def test_facility_type_keeps_a_faithful_long_tail():
    # It does NOT collapse to a small closed vocabulary: only the vulnerable-
    # population families are consolidated, so ~190 rare one-off values survive in
    # real Chicago data (they cover ~1.6% of rows; the top 10 cover ~96%).
    #
    # That is deliberate. The app's detail page displays this value for a SINGLE
    # establishment, so bucketing the tail into "Other" would replace a real venue's
    # type with a meaningless label. The tail is handled where it actually matters —
    # the chart tool's guidance says to plot the top N, not every category.
    features = _make_features()
    features["facility_type"] = ["Airport Lounge", "Restaurant"] * (len(features) // 2)
    model = _fit_model(features)
    scores = build_scores_table(model, features, ALL_FEATURES)

    assert set(scores["facility_type"]) == {"Airport Lounge", "Restaurant"}


def test_facility_type_empty_when_the_feed_lacks_it():
    features = _make_features()  # no facility_type column at all
    model = _fit_model(features)
    scores = build_scores_table(model, features, ALL_FEATURES)

    assert set(scores["facility_type"]) == {""}


def test_add_display_geography_is_the_one_shared_derivation():
    # Chicago's build_scores_table and the NYC / LA scripts all route through this,
    # so a city cannot ship its own idea of what these columns mean. Each city's
    # feed populates a different subset, which is expected, not a defect.
    nyc = add_display_geography(
        pd.DataFrame({"boro": ["Manhattan", "Queens"], "zip": ["10003", "11354"]})
    )
    assert list(nyc["neighborhood"]) == ["Manhattan", "Queens"]
    assert list(nyc["zip"]) == ["10003", "11354"]
    assert list(nyc["facility_type"]) == ["", ""]  # NYC's feed has none

    la = add_display_geography(
        pd.DataFrame({"city": ["WEST HOLLYWOOD", "TORRANCE"], "zip": ["90069", "90501"]})
    )
    assert list(la["neighborhood"]) == ["West Hollywood", "Torrance"]

    chicago = add_display_geography(
        pd.DataFrame(
            {"city": ["CHICAGO"] * 50, "zip": ["60614"] * 50, "facility_type": ["Restaurant"] * 50}
        )
    )
    assert set(chicago["neighborhood"]) == {""}  # no area signal in the feed
    assert set(chicago["zip"]) == {"60614"}
    assert set(chicago["facility_type"]) == {"Restaurant"}


def test_add_display_geography_always_emits_every_column():
    # A feed with none of the source columns still gets all three, empty — so a
    # downstream writer selecting them can never raise KeyError on a new city.
    out = add_display_geography(pd.DataFrame({"license_id": ["L0", "L1"]}))
    assert set(DISPLAY_GEOGRAPHY_COLUMNS) <= set(out.columns)
    for col in DISPLAY_GEOGRAPHY_COLUMNS:
        assert list(out[col]) == ["", ""]
