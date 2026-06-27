"""Tests for evaluation metrics.

Focused on ``group_performance_audit`` — the reusable fairness check. The
ranking metrics it wraps (``precision_at_k`` etc.) are exercised indirectly here
and in the modeling notebooks.
"""

from __future__ import annotations

from foodsafety.models.evaluate import group_performance_audit


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
