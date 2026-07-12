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


def test_low_positive_group_audits_parity_but_not_odds():
    # A large group with few positives: audited for parity, but FNR/calibration are
    # masked (not reliable) — this is the split-noise-floor behaviour that lets
    # sparse geographic groups (e.g. ZIP) still contribute a flag-rate comparison.
    a = _group("A", 100, 100, pos_flagged=80, neg_flagged=10, score=0.5)
    b = _group("B", 100, 100, pos_flagged=80, neg_flagged=10, score=0.5)
    sparse = _group("SPARSE", 10, 300, pos_flagged=5, neg_flagged=15, score=0.2)
    res = fairness.audit_axis(_frame(a, b, sparse), AX, n_bootstrap=100)
    gt = res.group_table.set_index("group")
    assert gt.loc["SPARSE", "audited"]  # n = 310 >= floor
    assert not gt.loc["SPARSE", "odds_reliable"]  # only 10 positives
    assert pd.isna(gt.loc["SPARSE", "fnr"])  # FNR masked for the sparse group
    assert res.n_audited_groups == 3  # it still counts for the parity comparison


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


def test_forecast_calibration_gap_is_flagged():
    # Group A forecast well-calibrated (0.5 == prevalence); group B over-confident.
    a = _group("A", 100, 100, pos_flagged=50, neg_flagged=50, score=0.5)
    b = _group("B", 100, 100, pos_flagged=50, neg_flagged=50, score=0.5)
    a["forecast_score"] = 0.5
    b["forecast_score"] = 0.9
    res = fairness.audit_forecast_axis(_frame(a, b), AX, n_bootstrap=200)
    assert res.finding
    assert res.coverage == 1.0


def test_audit_forecast_empty_without_score():
    a = _group("A", 100, 100, pos_flagged=80, neg_flagged=10, score=0.5)
    assert fairness.audit_forecast(_frame(a)) == {}  # no forecast_score column


def test_flagged_mask_uses_configured_tiers():
    tiers = pd.Series(["High", "Elevated", "Low", "Moderate"])
    prim = fairness.flagged_mask(tiers)
    assert prim.tolist() == [True, False, False, False]
    sec = fairness.flagged_mask(tiers, config.FLAGGED_TIERS_SECONDARY)
    assert sec.tolist() == [True, True, False, False]
