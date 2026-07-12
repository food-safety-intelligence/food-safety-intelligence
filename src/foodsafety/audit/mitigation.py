"""Mitigation analysis — ANALYSIS ONLY, the model is never changed here.

If the audit found an equalized-odds gap on some axis, the cheapest post-hoc fix
is a per-group decision threshold: pick, for each group, the score cutoff that
gives every group the same recall (miss rate), and price what that costs in extra
inspections and precision. This quantifies the fairness/cost trade-off at the
operating point without touching the model or its features.

Nothing here writes a model or a served artifact. It edges toward the
out-of-scope "reweighting" line, so any decision to actually adopt per-group
thresholds is a product/scope call (Jun), not something this module enacts.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from foodsafety.audit import config, fairness


def equalize_recall_thresholds(
    frame: pd.DataFrame,
    column: str,
    *,
    flagged_tiers=config.FLAGGED_TIERS_PRIMARY,
    target_recall: float | None = None,
    min_pos: int = config.MIN_GROUP_POSITIVES,
) -> pd.DataFrame:
    """Per-group score threshold that equalizes recall, and the cost of adopting it.

    Baseline is the single deployed cutoff (the lowest score still in
    ``flagged_tiers``). ``target_recall`` defaults to the pooled recall at that
    cutoff, so the analysis answers: "give every group the pooled miss rate — what
    threshold does each need, and how many extra inspections does that add?"

    Returns one row per odds-reliable group with the baseline and adjusted
    threshold, flag rate, FPR and recall, and the change in flagged count. The
    aggregate extra-inspection count is attached as ``df.attrs['total_delta_flags']``.
    """
    df = frame[frame[column].notna()].copy()
    flagged0 = fairness.flagged_mask(df["risk_tier"], flagged_tiers).to_numpy()
    scores = df["y_score"].to_numpy()
    y = df["y_true"].to_numpy()
    if not flagged0.any():
        raise ValueError("No rows are flagged at this operating point.")
    tau0 = float(scores[flagged0].min())  # deployed global cutoff
    pooled_recall = float(flagged0[y == 1].mean()) if (y == 1).any() else float("nan")
    target = pooled_recall if target_recall is None else target_recall

    rows = []
    total_delta = 0
    for name, g in df.groupby(column, observed=True):
        gy = g["y_true"].to_numpy()
        gs = g["y_score"].to_numpy()
        pos, neg = gy == 1, gy == 0
        if int(pos.sum()) < min_pos:
            continue
        base_flag = gs >= tau0
        # Group cutoff that lets exactly `target` of positives through.
        tau_g = float(np.quantile(gs[pos], max(0.0, 1.0 - target)))
        adj_flag = gs >= tau_g
        delta = int(adj_flag.sum() - base_flag.sum())
        total_delta += delta
        rows.append(
            {
                "group": name,
                "n": int(len(g)),
                "positives": int(pos.sum()),
                "base_threshold": round(tau0, 4),
                "base_flag_rate": round(float(base_flag.mean()), 4),
                "base_recall": round(float(base_flag[pos].mean()), 4),
                "base_fpr": round(float(base_flag[neg].mean()), 4) if neg.any() else float("nan"),
                "target_recall": round(float(target), 4),
                "adj_threshold": round(tau_g, 4),
                "adj_flag_rate": round(float(adj_flag.mean()), 4),
                "adj_recall": round(float(adj_flag[pos].mean()), 4),
                "adj_fpr": round(float(adj_flag[neg].mean()), 4) if neg.any() else float("nan"),
                "delta_flags": delta,
            }
        )
    out = pd.DataFrame(rows).sort_values("n", ascending=False).reset_index(drop=True)
    out.attrs["total_delta_flags"] = total_delta
    out.attrs["baseline_flagged"] = int(flagged0.sum())
    return out
