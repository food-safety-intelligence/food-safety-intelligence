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
    _row_to_json,
    build_scores_table,
    out_of_business_status,
    score_to_tier,
    write_scores_json,
)

KEEP_COLUMNS = ("license_id", "dba_name", "address", "lat", "lon")
CONTRACT_COLUMNS = [
    *KEEP_COLUMNS,
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
    # Tier must be the discretisation of the score it sits next to.
    for _, row in scores.iterrows():
        assert row["risk_tier"] == score_to_tier(row["risk_score"])


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
    expected_worsening = sum(1 for r in active if (r["trend_slope"] or 0) > 0.001)
    assert payload["totals"]["worsening_30d"] == expected_worsening
