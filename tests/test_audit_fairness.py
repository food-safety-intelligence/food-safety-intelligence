"""Unit tests for the disparity metrics engine (synthetic data — no census/model)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from foodsafety.audit import config, fairness
from foodsafety.audit.config import Axis

AX = Axis("grp", "Test group", "grp", primary=True)


def _group(name: str, n_pos: int, n_neg: int, *, pos_flagged: int, neg_flagged: int, score: float):
    """Build one group's rows with an exact flagged-count per label."""
    y = [1] * n_pos + [0] * n_neg
    flag = [True] * pos_flagged + [False] * (n_pos - pos_flagged)
    flag += [True] * neg_flagged + [False] * (n_neg - neg_flagged)
    return pd.DataFrame(
        {
            "grp": name,
            "y_true": y,
            "risk_tier": ["High" if f else "Low" for f in flag],
            "y_score": score,
        }
    )


def _frame(*groups: pd.DataFrame) -> pd.DataFrame:
    return pd.concat(groups, ignore_index=True)


def test_fair_frame_has_no_findings():
    # Two identical groups: equal flag rate / FPR / FNR / calibration.
    a = _group("A", 100, 100, pos_flagged=80, neg_flagged=10, score=0.5)
    b = _group("B", 100, 100, pos_flagged=80, neg_flagged=10, score=0.5)
    res = fairness.audit_axis(_frame(a, b), AX, n_bootstrap=200)
    assert res.n_audited_groups == 2
    assert not res.any_finding


def test_fnr_disparity_is_flagged():
    # Group B's positives are mostly missed (FNR 0.8 vs 0.2) and it is under-flagged.
    a = _group("A", 100, 100, pos_flagged=80, neg_flagged=0, score=0.5)
    b = _group("B", 100, 100, pos_flagged=20, neg_flagged=0, score=0.5)
    res = fairness.audit_axis(_frame(a, b), AX, n_bootstrap=300)
    g = res.gaps.set_index("metric")
    assert g.loc["fnr_gap", "finding"]  # 0.6 gap, well past the 0.10 band
    assert g.loc["disparate_impact_ratio", "finding"]  # 0.2 flag-rate ratio < 0.8
    assert g.loc["fnr_gap", "ci_low"] > config.FNR_GAP_MAX


def test_below_floor_group_not_audited():
    # A tiny group (few positives) must not be audited even if lopsided.
    a = _group("A", 100, 100, pos_flagged=80, neg_flagged=10, score=0.5)
    b = _group("B", 100, 100, pos_flagged=80, neg_flagged=10, score=0.5)
    tiny = _group("TINY", 10, 10, pos_flagged=0, neg_flagged=0, score=0.5)
    res = fairness.audit_axis(_frame(a, b, tiny), AX, n_bootstrap=100)
    gt = res.group_table.set_index("group")
    assert not gt.loc["TINY", "audited"]
    assert res.n_audited_groups == 2


def test_calibration_gap_is_flagged():
    # Group A well-calibrated (score == prevalence 0.5); group B badly over-confident
    # (score 0.9 but prevalence 0.5) -> large ECE gap.
    a = _group("A", 100, 100, pos_flagged=50, neg_flagged=50, score=0.5)
    b = _group("B", 100, 100, pos_flagged=50, neg_flagged=50, score=0.9)
    res = fairness.audit_axis(_frame(a, b), AX, n_bootstrap=200)
    g = res.gaps.set_index("metric")
    assert g.loc["ece_gap", "finding"]


def test_coverage_excludes_missing_group():
    a = _group("A", 100, 100, pos_flagged=80, neg_flagged=10, score=0.5)
    b = _group("B", 100, 100, pos_flagged=80, neg_flagged=10, score=0.5)
    missing = a.copy()
    missing["grp"] = np.nan
    res = fairness.audit_axis(_frame(a, b, missing), AX, n_bootstrap=50)
    # 400 audited rows out of 600 total -> coverage 2/3.
    assert res.coverage == pytest.approx(2 / 3, abs=1e-6)


def test_single_group_returns_empty_gaps():
    a = _group("A", 100, 100, pos_flagged=80, neg_flagged=10, score=0.5)
    res = fairness.audit_axis(_frame(a), AX, n_bootstrap=50)
    assert res.n_audited_groups == 1
    assert len(res.gaps) == 0
    assert not res.any_finding


def test_flagged_mask_uses_configured_tiers():
    tiers = pd.Series(["High", "Elevated", "Low", "Moderate"])
    prim = fairness.flagged_mask(tiers)
    assert prim.tolist() == [True, False, False, False]
    sec = fairness.flagged_mask(tiers, config.FLAGGED_TIERS_SECONDARY)
    assert sec.tolist() == [True, True, False, False]
