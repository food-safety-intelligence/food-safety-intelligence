"""Tests for evaluation metrics.

Covers the promotion-gate ranking metrics (``precision_at_k``, ``recall_at_k``,
``top_decile_lift``, the operating-point / decile / calibration tables and the
``evaluate`` bundle) plus ``group_performance_audit`` — the reusable fairness
check. These are the numbers the both-metrics promotion gate reads, so they're
pinned on deterministic perfect/worst rankings rather than only exercised
indirectly in notebooks.
"""

from __future__ import annotations

import numpy as np
import pytest

from foodsafety.models.evaluate import (
    calibration_table,
    decile_lift_table,
    evaluate,
    group_performance_audit,
    operating_point_table,
    precision_at_k,
    recall_at_k,
    top_decile_lift,
)

# A perfectly-ranked split: the 5 positives carry the 5 highest scores.
_PERFECT_Y = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]
_PERFECT_S = [0.90, 0.80, 0.70, 0.60, 0.55, 0.45, 0.40, 0.30, 0.20, 0.10]


def test_precision_at_k_perfect_and_full():
    # Top half is all positives -> precision 1.0; the whole set -> base rate.
    assert precision_at_k(_PERFECT_Y, _PERFECT_S, 0.5) == 1.0
    assert precision_at_k(_PERFECT_Y, _PERFECT_S, 1.0) == 0.5


def test_precision_at_k_worst_ranking_is_zero():
    # Reverse the scores: positives now rank last -> top half is all negatives.
    worst_s = list(reversed(_PERFECT_S))
    assert precision_at_k(_PERFECT_Y, worst_s, 0.5) == 0.0


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5])
def test_precision_at_k_rejects_out_of_range_kfrac(bad):
    with pytest.raises(ValueError):
        precision_at_k(_PERFECT_Y, _PERFECT_S, bad)


def test_recall_at_k_perfect_and_no_positives():
    # Perfect ranking: the top half captures every positive.
    assert recall_at_k(_PERFECT_Y, _PERFECT_S, 0.5) == 1.0
    # No positives anywhere -> recall is undefined (NaN), not a crash.
    assert np.isnan(recall_at_k([0, 0, 0, 0], [0.1, 0.2, 0.3, 0.4], 0.5))


def test_top_decile_lift():
    # base rate 0.5; the single top-decile pick is a positive -> precision 1.0.
    assert top_decile_lift(_PERFECT_Y, _PERFECT_S) == 2.0
    # All-negative -> base rate 0 -> lift undefined (NaN).
    assert np.isnan(top_decile_lift([0, 0, 0, 0], [0.4, 0.3, 0.2, 0.1]))


def test_operating_point_table_shape_and_values():
    table = operating_point_table(_PERFECT_Y, _PERFECT_S, k_fracs=(0.1, 0.5, 1.0))
    assert list(table.columns) == [
        "inspect_top_frac",
        "n_flagged",
        "precision",
        "recall",
        "lift",
        "events_caught",
    ]
    # Inspecting everyone catches every event; precision falls to the base rate.
    full = table.loc[table["inspect_top_frac"] == 1.0].iloc[0]
    assert full["recall"] == 1.0
    assert full["events_caught"] == 5
    assert full["precision"] == 0.5


def test_decile_lift_table_ranks_top_above_bottom():
    # Build a clean monotone signal so decile 1 is far above decile 10.
    rng = np.random.default_rng(42)
    y = np.array([1] * 50 + [0] * 50)
    # Scores correlate with the label, with noise that preserves the ordering.
    score = y * 0.6 + rng.uniform(0, 0.4, size=100)
    table = decile_lift_table(y, score)
    assert len(table) == 10
    assert table.loc[1, "positive_rate"] > table.loc[10, "positive_rate"]


def test_calibration_table_columns():
    rng = np.random.default_rng(0)
    y = (rng.uniform(size=200) < 0.3).astype(int)
    score = rng.uniform(size=200)
    table = calibration_table(y, score, n_bins=5)
    assert list(table.columns) == ["bin", "mean_predicted", "mean_observed"]
    assert len(table) <= 5


def test_evaluate_bundle_is_json_safe_and_sane():
    report = evaluate(_PERFECT_Y, _PERFECT_S)
    assert report.n == 10
    assert report.positive_rate == 0.5
    # Perfect ranking -> top scores are PR/ROC-AUC 1.0.
    assert report.pr_auc == pytest.approx(1.0)
    assert report.roc_auc == pytest.approx(1.0)
    d = report.to_dict()
    assert {"pr_auc", "roc_auc", "precision_at_10pct", "brier_score", "log_loss"} <= d.keys()
    assert all(isinstance(v, (int, float)) for v in d.values())


def test_group_performance_audit_flags_and_excludes_correctly():
    # Group A: scores rank the 5 positives ABOVE the 5 negatives -> high PR-AUC.
    yA = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]
    sA = [0.90, 0.80, 0.70, 0.60, 0.55, 0.10, 0.20, 0.30, 0.40, 0.45]
    # Group B: scores reversed -> positives ranked LAST -> low PR-AUC.
    yB = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]
    sB = [0.10, 0.20, 0.30, 0.40, 0.45, 0.90, 0.80, 0.70, 0.60, 0.55]
    # Group C: below min_n -> must be excluded from the audit.
    yC, sC = [1, 0, 1], [0.9, 0.1, 0.8]

    y = yA + yB + yC
    s = sA + sB + sC
    g = ["A"] * 10 + ["B"] * 10 + ["C"] * 3

    out = group_performance_audit(y, s, g, min_n=10, floor_frac=0.5)

    # Small group dropped; A and B audited.
    assert set(out["group"]) == {"A", "B"}
    a = out.loc[out["group"] == "A"].iloc[0]
    b = out.loc[out["group"] == "B"].iloc[0]
    assert a["pr_auc"] > b["pr_auc"]  # A ranks better than B

    # below_floor must exactly match "pr_auc < floor" for every row.
    floor = out.attrs["pr_auc_floor"]
    assert (out["below_floor"] == (out["pr_auc"] < floor)).all()
    assert out.attrs["pr_auc_floor"] == round(0.5 * out.attrs["overall_pr_auc"], 4)


def test_group_performance_audit_empty_when_all_groups_small():
    out = group_performance_audit(
        [1, 0, 1, 0], [0.8, 0.2, 0.7, 0.3], ["x", "x", "y", "y"], min_n=50
    )
    assert out.empty
    assert list(out.columns) == [
        "group",
        "n",
        "positive_rate",
        "pr_auc",
        "precision_at_k",
        "recall_at_k",
        "below_floor",
    ]
