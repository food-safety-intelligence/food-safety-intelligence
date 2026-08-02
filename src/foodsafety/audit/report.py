"""Turn raw audit results into a reviewable report + a ``fairness_audit_<city>.json``.

Adds the interpretation the bare metrics don't carry:
  * **direction** — which group is least / most flagged, with prevalence alongside;
  * a **prevalence-tracking** check — the correlation between a group's flag rate
    and its actual failure rate. A parity gap that tracks prevalence is the model
    flagging genuinely higher-risk areas, not bias; the equalized-odds and
    calibration lenses are what catch bias, because they condition on the truth;
  * a **secondary operating point** (Elevated+High) so a thin High-tier count
    doesn't decide the verdict alone;
  * a plain-English **verdict** per axis.

Same batch-to-JSON pattern as the rest of the pipeline: this writes a static
artifact; nothing here is a runtime dependency and no census column is a feature.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from foodsafety.audit import config, fairness
from foodsafety.io import storage

# A parity gap whose flag rate tracks prevalence at least this strongly is treated
# as prevalence-driven rather than biased (reported, not alarmed).
PREVALENCE_TRACKING_CORR: float = 0.5


def _to_native(x):
    """Recursively convert numpy/pandas scalars and NaN/inf into JSON-safe values."""
    if isinstance(x, dict):
        return {k: _to_native(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_to_native(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if (math.isnan(x) or math.isinf(x)) else float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if x is pd.NA or x is None:
        return None
    return x


def _flag_prevalence_corr(gt: pd.DataFrame) -> float:
    """Correlation between per-group flag rate and prevalence over audited groups."""
    a = gt[gt["audited"]]
    if len(a) < 2:
        return float("nan")
    fr = a["flag_rate"].to_numpy(dtype=float)
    pv = a["prevalence"].to_numpy(dtype=float)
    if fr.std() == 0 or pv.std() == 0:
        return float("nan")
    return float(np.corrcoef(fr, pv)[0, 1])


def _direction(gt: pd.DataFrame) -> dict:
    """Least- and most-flagged audited groups with their prevalence."""
    a = gt[gt["audited"]]
    if a.empty:
        return {}
    lo = a.loc[a["flag_rate"].idxmin()]
    hi = a.loc[a["flag_rate"].idxmax()]
    keys = ["group", "flag_rate", "prevalence", "n"]
    return {"least_flagged": {k: lo[k] for k in keys}, "most_flagged": {k: hi[k] for k in keys}}


def _verdict(res: fairness.AxisResult, corr: float, secondary_findings: list[str]) -> str:
    """Plain-English verdict combining the lenses, prevalence-tracking, and the
    secondary operating point."""
    if len(res.gaps) == 0:
        return "Too few audited groups to compare."
    fired = res.gaps.loc[res.gaps["finding"], "metric"].tolist()
    odds = [m for m in fired if m in ("fpr_gap", "fnr_gap", "ece_gap")]
    if odds:
        return (
            f"Equalized-odds / calibration disparity on {', '.join(odds)} — the model makes "
            "uneven errors across these groups. Investigate."
        )
    if "disparate_impact_ratio" in fired:
        tracks = not math.isnan(corr) and corr >= PREVALENCE_TRACKING_CORR
        base = (
            "Flag-rate parity gap, but no false-positive, false-negative, or calibration disparity."
        )
        if tracks:
            base += (
                f" The flag rate tracks group prevalence (corr {corr:.2f}), consistent with the "
                "model flagging genuinely higher-risk places rather than bias."
            )
        else:
            base += " Flag rate does not clearly track prevalence — worth a closer look."
        if "disparate_impact_ratio" in secondary_findings:
            base += " Persists at the wider Elevated+High operating point."
        else:
            base += " Does not persist at the wider Elevated+High operating point."
        return base
    return "No disparity finding."


def _axis_payload(res: fairness.AxisResult, secondary: fairness.AxisResult | None) -> dict:
    corr = _flag_prevalence_corr(res.group_table)
    secondary_findings = (
        secondary.gaps.loc[secondary.gaps["finding"], "metric"].tolist()
        if secondary and len(secondary.gaps)
        else []
    )
    return {
        "column": res.column,
        "coverage": round(res.coverage, 4),
        "n_audited_groups": res.n_audited_groups,
        "flag_vs_prevalence_corr": None if math.isnan(corr) else round(corr, 3),
        "direction": _direction(res.group_table),
        "group_table": res.group_table.to_dict(orient="records"),
        "gaps_primary_high": res.gaps.to_dict(orient="records"),
        "gaps_secondary_elevated_high": (
            secondary.gaps.to_dict(orient="records") if secondary else []
        ),
        "verdict": _verdict(res, corr, secondary_findings),
    }


def build_report(
    frame: pd.DataFrame,
    city: str,
    *,
    n_bootstrap: int = config.N_BOOTSTRAP,
    acs_year: int | None = None,
) -> dict:
    """Full fairness report for one city's audit frame (Model 1 + Model 2)."""
    from sklearn.metrics import average_precision_score

    primary = fairness.audit(frame, n_bootstrap=n_bootstrap)
    secondary = fairness.audit(
        frame, flagged_tiers=config.FLAGGED_TIERS_SECONDARY, n_bootstrap=n_bootstrap
    )
    forecast = fairness.audit_forecast(frame, n_bootstrap=n_bootstrap)

    y = frame["y_true"].to_numpy()
    model1_pr_auc = float(average_precision_score(y, frame["y_score"])) if y.sum() else None
    model2_pr_auc = (
        float(average_precision_score(y, frame["forecast_score"]))
        if frame["forecast_score"].notna().all() and y.sum()
        else None
    )

    report = {
        "city": city,
        "provenance": {
            "test_rows": int(len(frame)),
            "test_window": [
                str(frame["as_of_date"].min().date()),
                str(frame["as_of_date"].max().date()),
            ],
            "label_prevalence": round(float(y.mean()), 4),
            "model1_test_pr_auc": model1_pr_auc,
            "model2_forecast_test_pr_auc": model2_pr_auc,
            "acs_year": acs_year,
        },
        "operating_points": {"primary": "High", "secondary": "Elevated+High"},
        "tolerances": {
            "disparate_impact_ratio_min": config.DISPARATE_IMPACT_RATIO_MIN,
            "fpr_gap_max": config.FPR_GAP_MAX,
            "fnr_gap_max": config.FNR_GAP_MAX,
            "ece_gap_max": config.ECE_GAP_MAX,
            "min_group_n": config.MIN_GROUP_N,
            "min_group_positives": config.MIN_GROUP_POSITIVES,
        },
        "model1_risk": {
            "axes": {key: _axis_payload(res, secondary.get(key)) for key, res in primary.items()},
            "summary": fairness.summary(primary).to_dict(orient="records"),
        },
        "model2_forecast": {
            "note": "calibration + coverage only; the forecast has no flagging operating point",
            "axes": {
                key: {
                    "column": r.column,
                    "coverage": round(r.coverage, 4),
                    "ece_gap": r.ece_gap,
                    "ece_gap_ci": [r.ci_low, r.ci_high],
                    "finding": r.finding,
                    "group_table": r.group_table.to_dict(orient="records"),
                }
                for key, r in forecast.items()
            },
        },
    }
    return _to_native(report)


def write_report(report: dict, target) -> None:
    """Write the report JSON through ``io.storage`` (local or s3://)."""
    storage.write_text(json.dumps(report, indent=2), target)
