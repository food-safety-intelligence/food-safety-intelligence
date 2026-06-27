"""Generate `tests/fixtures/scores_mock.parquet` — a synthetic predictions
file the UI team builds against until the real model lands.

Schema matches `docs/interface_contracts.md` § 3. The fixture has a `_is_mock`
column the app uses to render the yellow "demo data" banner; the real
production `scores.parquet` will NOT include this column, so the app can
detect mock-vs-real by column presence.

Run:
    PYTHONPATH=src python scripts/build_scores_mock.py
    # or, after `uv sync`:
    uv run python scripts/build_scores_mock.py
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import pandas as pd

from foodsafety.config import RAW_DIR

RNG = np.random.default_rng(42)
random.seed(42)

# How many real restaurants to include in the fixture. Small on purpose — this
# file gets committed to git, so we keep it under ~100KB.
N_RESTAURANTS = 200

# Plausible driver templates for the mock. Each is keyed on the feature it
# refers to so the UI can map feature -> icon / color consistently. `label` is
# the plain-English UI string with a {value} placeholder we'll fill in.
DRIVER_TEMPLATES = [
    {
        "feature": "prior_priority_violations",
        "label": "{value} priority violations in prior 2 years",
    },
    {"feature": "prior_fails", "label": "{value} failed inspections previously"},
    {"feature": "days_since_last_inspection", "label": "Last inspected {value} days ago"},
    {
        "feature": "n_311_rodent_300m_90d",
        "label": "{value} rodent complaints within 300m in last 90 days",
    },
    {
        "feature": "n_311_sanitation_300m_90d",
        "label": "{value} sanitation complaints nearby (90 days)",
    },
    {"feature": "flag_kw_temperature", "label": "Temperature-related violation in recent history"},
    {"feature": "flag_kw_rodent", "label": "Vermin/pest-related violation noted previously"},
    {"feature": "static_facility_type", "label": "Facility type: {value}"},
]


def _score_to_tier(score: float) -> str:
    """Risk-tier thresholds per interface_contracts.md."""
    if score < 0.20:
        return "Low"
    if score < 0.40:
        return "Moderate"
    if score < 0.65:
        return "Elevated"
    return "High"


def _sample_drivers(score: float) -> list[dict]:
    """Pick 3 plausible drivers. High-score rows skew toward violation drivers;
    low-score rows skew toward 'days since last' / static drivers."""
    n = 3
    if score >= 0.5:
        candidates = [
            t
            for t in DRIVER_TEMPLATES
            if "violation" in t["feature"] or "311" in t["feature"] or "kw_" in t["feature"]
        ]
    else:
        candidates = DRIVER_TEMPLATES
    picks = random.sample(candidates, k=min(n, len(candidates)))
    drivers = []
    for p in picks:
        # Fabricate a plausible value for the {value} placeholder.
        if "days_since" in p["feature"]:
            value = int(RNG.integers(60, 730))
        elif "facility_type" in p["feature"]:
            value = random.choice(["Restaurant", "Grocery Store", "Bakery"])
        elif "kw_" in p["feature"]:
            value = "yes"
        else:
            value = int(RNG.integers(1, 8))
        drivers.append(
            {
                "feature": p["feature"],
                "value": str(value),
                "shap": round(float(RNG.uniform(0.02, 0.18)), 3),
                "label": p["label"].format(value=value),
            }
        )
    # Sort drivers by SHAP magnitude (descending) so the UI can render top-N
    # without re-sorting.
    drivers.sort(key=lambda d: d["shap"], reverse=True)
    return drivers


def build_fixture() -> pd.DataFrame:
    inspections_path = RAW_DIR / "inspections.parquet"
    if not inspections_path.exists():
        raise SystemExit(
            f"Cannot build mock — {inspections_path} not found. "
            "Run `make data` first, or copy from a teammate's data/raw/."
        )

    # Pull one row per license to anchor the fixture in real Chicago data.
    insp = pd.read_parquet(
        inspections_path,
        columns=["license_", "dba_name", "address", "latitude", "longitude", "inspection_date"],
    )
    # Drop placeholder/empty licenses; keep the most recent row per license so
    # dba_name and address are current-ish.
    insp = insp[~insp["license_"].isin(["", "0"])].dropna(subset=["license_"])
    insp = insp.sort_values("inspection_date").drop_duplicates("license_", keep="last")

    # Sample N restaurants, biasing slightly toward recent inspections so the
    # demo shows live-feeling addresses.
    sampled = insp.sample(n=min(N_RESTAURANTS, len(insp)), random_state=42).reset_index(drop=True)

    # Risk scores — beta(2, 5) skews toward low risk, with a few high outliers.
    # Realistic-looking distribution for a city where most restaurants are fine.
    scores = RNG.beta(2.0, 5.0, size=len(sampled)).round(4)

    as_of = pd.Timestamp.today().normalize()

    df = pd.DataFrame(
        {
            "license_id": sampled["license_"].astype(str),
            "dba_name": sampled["dba_name"].astype(str),
            "address": sampled["address"].astype(str),
            "lat": pd.to_numeric(sampled["latitude"], errors="coerce"),
            "lon": pd.to_numeric(sampled["longitude"], errors="coerce"),
            "as_of_date": as_of,
            "risk_score": scores,
            "risk_tier": [_score_to_tier(s) for s in scores],
            "top_drivers": [_sample_drivers(s) for s in scores],
            # Trend: small slope (positive or negative) so the UI's
            # improving/stable/worsening logic gets all three states.
            "trend_slope_90d": RNG.normal(0, 0.003, size=len(sampled)).round(5),
            # Mock marker — the real production scores.parquet will NOT have
            # this column. UI: `if "_is_mock" in df.columns: show_banner()`.
            "_is_mock": True,
        }
    )

    return df


def main() -> None:
    out_path = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "scores_mock.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    df = build_fixture()
    df.to_parquet(out_path, index=False)

    print(f"wrote {out_path}  ({len(df):,} rows, {out_path.stat().st_size / 1024:.1f} KB)")
    print("\n-- tier distribution --")
    print(df["risk_tier"].value_counts().to_string())
    print("\n-- head(3) --")
    print(
        df[["license_id", "dba_name", "risk_score", "risk_tier", "trend_slope_90d"]]
        .head(3)
        .to_string()
    )


if __name__ == "__main__":
    main()
