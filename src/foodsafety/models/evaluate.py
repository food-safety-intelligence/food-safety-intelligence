"""Model evaluation — metric functions and report generation.

CLAUDE.md pins the metric stack: **PR-AUC + precision@top-decile** are the
headlines. ROC-AUC is reported but never treated as the decision metric
(ROC-AUC looks optimistic on imbalanced data while the operationally relevant
metric — "of the top 10% the model flags, how many actually fail?" — can be
mediocre).

**Accuracy is deliberately NOT reported.** With a ~11% positive rate, a
do-nothing "always predict safe" classifier already scores ~89% accuracy while
catching zero real risk, and ``class_weight='balanced'`` trades raw accuracy for
recall on the minority — so the model's 0.5-threshold accuracy is actually
*lower* than that trivial baseline. Accuracy is misleading under this imbalance;
PR-AUC + precision/recall@k are the honest read.

Every metric function here takes ``y_true`` and ``y_score`` as 1-D arrays;
they don't depend on the estimator type, so the same code evaluates LogReg,
XGBoost, and any future model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)

ArrayLike = np.ndarray | pd.Series | Sequence[float]


def _as_array(x: ArrayLike) -> np.ndarray:
    return np.asarray(x, dtype=float)


def precision_at_k(
    y_true: ArrayLike, y_score: ArrayLike, k_frac: float = 0.10
) -> float:
    """Precision in the top ``k_frac`` fraction of predicted scores.

    The operational interpretation: if we surface the top K% of restaurants
    to a Chicago inspector tomorrow, what fraction of them will actually
    have a failed inspection or priority violation in the next 180 days?
    """
    if not 0 < k_frac <= 1:
        raise ValueError(f"k_frac must be in (0, 1]; got {k_frac}")
    y_true_arr = _as_array(y_true)
    y_score_arr = _as_array(y_score)
    n = len(y_true_arr)
    k = max(1, int(np.ceil(n * k_frac)))
    # Order indices by descending score; tie-breaking via index order is fine.
    order = np.argsort(-y_score_arr, kind="stable")
    top_k = order[:k]
    return float(np.mean(y_true_arr[top_k]))


def recall_at_k(
    y_true: ArrayLike, y_score: ArrayLike, k_frac: float = 0.10
) -> float:
    """Recall (coverage) in the top ``k_frac`` fraction of predicted scores.

    Of ALL restaurants that actually fail / incur a priority violation in the
    window, what fraction land in the top K% we'd surface to an inspector?
    The complement to ``precision_at_k`` for a capacity-limited triage tool:
    precision = "how clean is the flagged list", recall = "how much of the
    real risk did we catch".
    """
    if not 0 < k_frac <= 1:
        raise ValueError(f"k_frac must be in (0, 1]; got {k_frac}")
    y_true_arr = _as_array(y_true)
    y_score_arr = _as_array(y_score)
    total_pos = float(y_true_arr.sum())
    if total_pos == 0:
        return float("nan")
    n = len(y_true_arr)
    k = max(1, int(np.ceil(n * k_frac)))
    order = np.argsort(-y_score_arr, kind="stable")
    return float(y_true_arr[order[:k]].sum() / total_pos)


def top_decile_lift(y_true: ArrayLike, y_score: ArrayLike) -> float:
    """precision@10% divided by the base positive rate.

    Lift > 1 means the model is doing better than random ranking. Lift of 2
    means the top decile contains 2× the base rate of positives.
    """
    base = float(np.mean(_as_array(y_true)))
    if base == 0:
        return float("nan")
    return precision_at_k(y_true, y_score, 0.10) / base


def decile_lift_table(y_true: ArrayLike, y_score: ArrayLike) -> pd.DataFrame:
    """Per-decile lift table — the rank-quality eyeball-test.

    Bins instances by predicted score into deciles (decile 1 = top scores)
    and reports the positive rate per bin. A well-ranked model has decile 1
    >> decile 10.
    """
    y_true_arr = _as_array(y_true)
    y_score_arr = _as_array(y_score)
    df = pd.DataFrame({"y": y_true_arr, "score": y_score_arr})
    df["decile"] = pd.qcut(
        df["score"].rank(method="first", ascending=False),
        10,
        labels=range(1, 11),
    )
    grouped = df.groupby("decile", observed=True).agg(
        n=("y", "size"),
        positive_rate=("y", "mean"),
        mean_score=("score", "mean"),
    )
    base = float(df["y"].mean())
    grouped["lift_vs_base"] = grouped["positive_rate"] / base if base > 0 else np.nan
    return grouped.round(4)


def calibration_table(
    y_true: ArrayLike, y_score: ArrayLike, n_bins: int = 10
) -> pd.DataFrame:
    """Predicted vs observed positive rate per probability bin.

    A perfectly calibrated model has ``predicted == observed`` in every bin.
    Off-diagonal means the score doesn't mean "probability"; it means "rank".
    """
    prob_true, prob_pred = calibration_curve(
        _as_array(y_true), _as_array(y_score), n_bins=n_bins, strategy="quantile"
    )
    return pd.DataFrame(
        {
            "bin": range(1, len(prob_pred) + 1),
            "mean_predicted": prob_pred.round(4),
            "mean_observed": prob_true.round(4),
        }
    )


@dataclass(frozen=True)
class EvalReport:
    """All-in-one eval bundle for one (model, split) pair.

    Frozen so it's safe to log / serialize. ``to_dict`` produces a JSON-safe
    payload for ``reports/metrics/*.json``.
    """

    n: int
    positive_rate: float
    pr_auc: float
    roc_auc: float
    precision_at_5pct: float
    precision_at_10pct: float
    precision_at_20pct: float
    recall_at_5pct: float
    recall_at_10pct: float
    recall_at_20pct: float
    top_decile_lift: float
    brier_score: float
    log_loss: float

    def to_dict(self) -> dict[str, float | int]:
        return {
            "n": int(self.n),
            "positive_rate": round(self.positive_rate, 6),
            "pr_auc": round(self.pr_auc, 6),
            "roc_auc": round(self.roc_auc, 6),
            "precision_at_5pct": round(self.precision_at_5pct, 6),
            "precision_at_10pct": round(self.precision_at_10pct, 6),
            "precision_at_20pct": round(self.precision_at_20pct, 6),
            "recall_at_5pct": round(self.recall_at_5pct, 6),
            "recall_at_10pct": round(self.recall_at_10pct, 6),
            "recall_at_20pct": round(self.recall_at_20pct, 6),
            "top_decile_lift": round(self.top_decile_lift, 6),
            "brier_score": round(self.brier_score, 6),
            "log_loss": round(self.log_loss, 6),
        }


def evaluate(y_true: ArrayLike, y_score: ArrayLike) -> EvalReport:
    """Compute the full eval suite for one (y_true, y_score) pair."""
    y_t = _as_array(y_true)
    y_s = _as_array(y_score)
    return EvalReport(
        n=len(y_t),
        positive_rate=float(np.mean(y_t)),
        pr_auc=float(average_precision_score(y_t, y_s)),
        roc_auc=float(roc_auc_score(y_t, y_s)),
        precision_at_5pct=precision_at_k(y_t, y_s, 0.05),
        precision_at_10pct=precision_at_k(y_t, y_s, 0.10),
        precision_at_20pct=precision_at_k(y_t, y_s, 0.20),
        recall_at_5pct=recall_at_k(y_t, y_s, 0.05),
        recall_at_10pct=recall_at_k(y_t, y_s, 0.10),
        recall_at_20pct=recall_at_k(y_t, y_s, 0.20),
        top_decile_lift=top_decile_lift(y_t, y_s),
        brier_score=float(brier_score_loss(y_t, y_s)),
        log_loss=float(log_loss(y_t, np.clip(y_s, 1e-15, 1 - 1e-15))),
    )
