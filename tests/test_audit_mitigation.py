"""Unit tests for the per-group threshold mitigation analysis."""

from __future__ import annotations

import numpy as np
import pandas as pd

from foodsafety.audit import mitigation


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    parts = []
    # Group A: well-separated positives; Group B: harder (lower scores).
    for name, pos_lo in (("A", 0.5), ("B", 0.3)):
        pos = pd.DataFrame({"grp": name, "y_true": 1, "y_score": rng.uniform(pos_lo, 1.0, 120)})
        neg = pd.DataFrame({"grp": name, "y_true": 0, "y_score": rng.uniform(0.0, 0.5, 120)})
        parts += [pos, neg]
    df = pd.concat(parts, ignore_index=True)
    df["risk_tier"] = np.where(df["y_score"] >= 0.7, "High", "Low")
    return df


def test_equalize_recall_hits_target_per_group():
    df = _frame()
    tbl = mitigation.equalize_recall_thresholds(df, "grp", target_recall=0.8)
    assert set(tbl["group"]) == {"A", "B"}
    # Every group's adjusted recall should land near the requested target.
    assert np.allclose(tbl["adj_recall"], 0.8, atol=0.05)
    assert "total_delta_flags" in tbl.attrs


def test_harder_group_needs_lower_threshold():
    df = _frame()
    tbl = mitigation.equalize_recall_thresholds(df, "grp", target_recall=0.8).set_index("group")
    # The harder group (B) must drop its cutoff further to reach the same recall.
    assert tbl.loc["B", "adj_threshold"] < tbl.loc["A", "adj_threshold"]
