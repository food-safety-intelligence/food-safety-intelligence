"""Disparity metrics engine — city-agnostic, reads only the ``AuditFrame``.

For one grouping axis this computes, per group: flag rate, false-positive rate,
false-negative rate, and calibration error, then the across-group gaps, each with
a bootstrap confidence interval and a verdict against the tolerance bands in
``config``. A gap is only called a *finding* when it is both **material** (point
estimate past the band) and **confident** (the CI stays past the band) — small,
low-prevalence groups otherwise trip false alarms on base-rate artifacts alone
(decision 0005).

"Flagged" = the deployed risk tier(s) in ``config.FLAGGED_TIERS_PRIMARY`` (High).
Everything here is measurement only — no census column is ever a model input.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from foodsafety.audit import config
from foodsafety.config import RANDOM_STATE

# --------------------------------------------------------------------------- #
# Low-level metric helpers (operate on numpy arrays for the bootstrap loop).
# --------------------------------------------------------------------------- #


def flagged_mask(risk_tier: pd.Series, flagged_tiers=config.FLAGGED_TIERS_PRIMARY) -> pd.Series:
    """Boolean: is this establishment flagged at the given operating point."""
    return risk_tier.isin(flagged_tiers)


def _ece(y: np.ndarray, score: np.ndarray, *, n_bins: int = 10) -> float:
    """Expected calibration error: weighted mean |mean predicted - mean observed|
    over ``n_bins`` equal-width score bins. NaN for an empty slice."""
    if len(y) == 0:
        return float("nan")
    idx = np.clip((score * n_bins).astype(int), 0, n_bins - 1)
    total = 0.0
    for b in range(n_bins):
        m = idx == b
        if m.any():
            total += m.mean() * abs(score[m].mean() - y[m].mean())
    return float(total)


def _range(vals: np.ndarray) -> float:
    """max - min ignoring NaN; NaN if fewer than two groups have a value."""
    v = vals[~np.isnan(vals)]
    return float(v.max() - v.min()) if v.size >= 2 else float("nan")


def _gaps_from_arrays(
    y: np.ndarray, flagged: np.ndarray, score: np.ndarray, g: np.ndarray, n_groups: int
) -> dict[str, float]:
    """The four across-group gaps for one axis, from raw arrays (bootstrap-hot)."""
    flag_rate = np.full(n_groups, np.nan)
    fpr = np.full(n_groups, np.nan)
    fnr = np.full(n_groups, np.nan)
    ece = np.full(n_groups, np.nan)
    for k in range(n_groups):
        mk = g == k
        if not mk.any():
            continue
        yk, flk, sck = y[mk], flagged[mk], score[mk]
        flag_rate[k] = flk.mean()
        neg, pos = yk == 0, yk == 1
        if neg.any():
            fpr[k] = flk[neg].mean()
        if pos.any():
            fnr[k] = 1.0 - flk[pos].mean()
        ece[k] = _ece(yk, sck)
    valid_fr = flag_rate[~np.isnan(flag_rate)]
    top = valid_fr.max() if valid_fr.size else np.nan
    di_ratio = (valid_fr.min() / top) if (valid_fr.size >= 2 and top > 0) else float("nan")
    return {
        "disparate_impact_ratio": di_ratio,
        "fpr_gap": _range(fpr),
        "fnr_gap": _range(fnr),
        "ece_gap": _range(ece),
    }


# --------------------------------------------------------------------------- #
# Per-group point-estimate table (for display / JSON) and the axis result.
# --------------------------------------------------------------------------- #


@dataclass
class AxisResult:
    """One axis's audit: the per-group table, the gaps + verdicts, and coverage."""

    axis: str
    column: str
    group_table: pd.DataFrame
    gaps: pd.DataFrame
    n_audited_groups: int
    coverage: float  # fraction of rows with a known, above-floor group value

    @property
    def any_finding(self) -> bool:
        return bool(self.gaps["finding"].any()) if len(self.gaps) else False


# Tolerance band + verdict direction per gap metric.
#   "min": worse when smaller (disparate-impact ratio) -> finding if value < band
#          AND ci_high < band.
#   "max": worse when larger (rate/error gaps) -> finding if value > band
#          AND ci_low > band.
_GAP_SPEC: dict[str, tuple[float, str]] = {
    "disparate_impact_ratio": (config.DISPARATE_IMPACT_RATIO_MIN, "min"),
    "fpr_gap": (config.FPR_GAP_MAX, "max"),
    "fnr_gap": (config.FNR_GAP_MAX, "max"),
    "ece_gap": (config.ECE_GAP_MAX, "max"),
}


def group_table(
    frame: pd.DataFrame, column: str, *, flagged_tiers=config.FLAGGED_TIERS_PRIMARY
) -> pd.DataFrame:
    """Per-group metrics for every above-floor group of ``column``.

    Rows with a missing group value are excluded (reported via coverage, never
    imputed). A group is *audited* only when it clears both noise floors.
    """
    df = frame[[column, "y_true", "risk_tier", "y_score"]].copy()
    df = df[df[column].notna()]
    df["_flagged"] = flagged_mask(df["risk_tier"], flagged_tiers).astype(int)

    rows = []
    for name, grp in df.groupby(column, observed=True):
        y = grp["y_true"].to_numpy()
        fl = grp["_flagged"].to_numpy()
        sc = grp["y_score"].to_numpy()
        pos = int((y == 1).sum())
        audited = len(grp) >= config.MIN_GROUP_N and pos >= config.MIN_GROUP_POSITIVES
        rows.append(
            {
                "group": name,
                "n": int(len(grp)),
                "positives": pos,
                "prevalence": round(float(y.mean()), 4),
                "flag_rate": round(float(fl.mean()), 4),
                "fpr": round(float(fl[y == 0].mean()), 4) if (y == 0).any() else float("nan"),
                "fnr": round(1.0 - float(fl[y == 1].mean()), 4) if (y == 1).any() else float("nan"),
                "ece": round(_ece(y, sc), 4),
                "mean_pred": round(float(sc.mean()), 4),
                "mean_obs": round(float(y.mean()), 4),
                "audited": audited,
            }
        )
    out = pd.DataFrame(rows).sort_values("n", ascending=False).reset_index(drop=True)
    return out


def audit_axis(
    frame: pd.DataFrame,
    axis: config.Axis,
    *,
    flagged_tiers=config.FLAGGED_TIERS_PRIMARY,
    n_bootstrap: int = config.N_BOOTSTRAP,
    seed: int = RANDOM_STATE,
) -> AxisResult:
    """Full disparity audit for one axis: group table + gap CIs + verdicts."""
    column = axis.column
    gt = group_table(frame, column, flagged_tiers=flagged_tiers)
    audited = gt[gt["audited"]]["group"].tolist()

    # Restrict to audited groups and factorise for the bootstrap-hot arrays.
    sub = frame[frame[column].isin(audited)]
    coverage = float(len(sub) / len(frame)) if len(frame) else 0.0
    g, _ = pd.factorize(sub[column])
    n_groups = len(audited)
    y = sub["y_true"].to_numpy()
    fl = flagged_mask(sub["risk_tier"], flagged_tiers).to_numpy().astype(int)
    sc = sub["y_score"].to_numpy()

    if n_groups < 2:
        gaps = pd.DataFrame(
            columns=["metric", "value", "ci_low", "ci_high", "tolerance", "direction", "finding"]
        )
        return AxisResult(axis.key, column, gt, gaps, n_groups, coverage)

    point = _gaps_from_arrays(y, fl, sc, g, n_groups)

    # Bootstrap the gaps by resampling rows with replacement.
    rng = np.random.default_rng(seed)
    n = len(y)
    boot: dict[str, list[float]] = {m: [] for m in _GAP_SPEC}
    for _ in range(n_bootstrap):
        idx = rng.integers(0, n, n)
        b = _gaps_from_arrays(y[idx], fl[idx], sc[idx], g[idx], n_groups)
        for m in _GAP_SPEC:
            boot[m].append(b[m])

    rows = []
    for metric, (band, direction) in _GAP_SPEC.items():
        arr = np.asarray(boot[metric], dtype=float)
        arr = arr[~np.isnan(arr)]
        lo, hi = np.percentile(arr, [2.5, 97.5]) if arr.size else (np.nan, np.nan)
        value = point[metric]
        if direction == "min":  # disparate-impact ratio: confident below the band
            finding = bool(value < band and hi < band)
        else:  # rate / error gap: confident above the band
            finding = bool(value > band and lo > band)
        rows.append(
            {
                "metric": metric,
                "value": round(float(value), 4) if not np.isnan(value) else float("nan"),
                "ci_low": round(float(lo), 4) if not np.isnan(lo) else float("nan"),
                "ci_high": round(float(hi), 4) if not np.isnan(hi) else float("nan"),
                "tolerance": band,
                "direction": direction,
                "finding": finding,
            }
        )
    gaps = pd.DataFrame(rows)
    return AxisResult(axis.key, column, gt, gaps, n_groups, coverage)


def audit(
    frame: pd.DataFrame,
    axes: tuple[config.Axis, ...] = config.AXES,
    *,
    flagged_tiers=config.FLAGGED_TIERS_PRIMARY,
    n_bootstrap: int = config.N_BOOTSTRAP,
    seed: int = RANDOM_STATE,
) -> dict[str, AxisResult]:
    """Audit every axis whose column is present in the frame. Returns axis.key ->
    ``AxisResult``. Axes missing from the frame (e.g. a city with no cuisine) are
    skipped, not errored."""
    results: dict[str, AxisResult] = {}
    for ax in axes:
        if ax.column not in frame.columns:
            continue
        if frame[ax.column].notna().sum() == 0:
            continue
        results[ax.key] = audit_axis(
            frame, ax, flagged_tiers=flagged_tiers, n_bootstrap=n_bootstrap, seed=seed
        )
    return results


def summary(results: dict[str, AxisResult]) -> pd.DataFrame:
    """One row per axis: audited-group count, coverage, and any-finding flag with
    the list of which gap metrics fired."""
    rows = []
    for key, res in results.items():
        fired = res.gaps.loc[res.gaps["finding"], "metric"].tolist() if len(res.gaps) else []
        rows.append(
            {
                "axis": key,
                "column": res.column,
                "n_audited_groups": res.n_audited_groups,
                "coverage": round(res.coverage, 3),
                "any_finding": res.any_finding,
                "findings": ", ".join(fired),
            }
        )
    return pd.DataFrame(rows)
