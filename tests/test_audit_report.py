"""Unit tests for the fairness report builder / JSON serializer."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from foodsafety.audit import report


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    n = 800
    grp = np.where(np.arange(n) < n // 2, "Restaurant", "Grocery Store")
    y = rng.integers(0, 2, n)
    tier = np.where(rng.random(n) < 0.1, "High", "Low")
    return pd.DataFrame(
        {
            "city": "testcity",
            "as_of_date": pd.to_datetime("2025-08-01"),
            "y_true": y.astype("int8"),
            "y_score": rng.random(n),
            "risk_tier": pd.array(tier, dtype="string"),
            "facility_type_norm": pd.array(grp, dtype="string"),
            "forecast_score": rng.random(n),
        }
    )


def test_build_report_is_json_serializable_and_structured():
    rep = report.build_report(_frame(), "testcity", n_bootstrap=50)
    # Must round-trip through strict JSON (no NaN/inf, no numpy types leaking).
    text = json.dumps(rep, allow_nan=False)
    assert '"city": "testcity"' in text
    assert "model1_risk" in rep and "model2_forecast" in rep
    fac = rep["model1_risk"]["axes"]["facility_type"]
    assert "verdict" in fac and "gaps_primary_high" in fac
    assert "gaps_secondary_elevated_high" in fac
    assert set(rep["operating_points"]) == {"primary", "secondary"}


def test_write_report_round_trips(tmp_path):
    rep = report.build_report(_frame(), "testcity", n_bootstrap=50)
    out = tmp_path / "fairness_audit_testcity.json"
    report.write_report(rep, str(out))
    assert json.loads(out.read_text())["city"] == "testcity"
