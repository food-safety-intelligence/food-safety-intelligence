"""Trend de-confound experiment — last-K-visits slope on a forecast-only model.

`scores.parquet`'s original trend field — ``trend_slope_90d``, since renamed to
``trend_slope`` (decision 0011) — was an OLS slope of the production model's
``risk_score`` over the 90 days before each license's latest inspection. This
experiment motivated that replacement; the 90-day field had two known failures:

  * **coverage** — it needs >=2 inspections inside a 90-day window, so it is null
    for most licenses (they are not inspected twice in 90 days); the field then
    defaults to "stable" and "stable" really means "unknown".
  * **re-inspection confound** — a Fail triggers a mandated ~30-day re-inspection
    that usually passes. The production score (which sees the current outcome)
    swings high->low across that pair, so the slope reads "improving"
    mechanically, not because the establishment is getting safer.

TWO MODELS (both predict the SAME label — P(fail-or-priority in the next 180
days). The 180-day horizon is identical; only the feature set differs):

  * MODEL 1 — production risk model. All features, including the current
    inspection's own outcome. This is the shipped ``risk_score``; this
    experiment does NOT change it.
  * MODEL 2 — forecast-only model. Same label and horizon, but DROPS the three
    current-outcome features (``was_fail``, ``n_priority_this_inspection``,
    ``n_core_this_inspection``) so its score does not see today's verdict.

The TREND is not predicted by any model: it is the least-squares slope of a
model's score across a restaurant's recent inspections. We compare the slope of
MODEL 1's score (today's confounded basis) against the slope of MODEL 2's score,
and vary the window, to attribute each effect:

  * window:  90-day calendar  vs  last-K VISITS       -> attributes COVERAGE
  * score:   MODEL 1          vs  MODEL 2 (forecast)   -> attributes DE-CONFOUND

Validation:
  1. coverage     — % of test anchors with a computable slope.
  2. de-confound  — corr(slope, last_was_fail). The MODEL 1 slope should be
                    strongly negative (recent fail -> looks "improving"); the
                    MODEL 2 slope should be weaker.
  3. early-warning lift — among CLEAN anchors (was_fail==0), does a steeply-rising
                    MODEL 2 slope select a slice whose FORWARD fail-rate beats the
                    base rate? (the prototype's STRICT watch list was ~1.46x base;
                    a loose slope>0 was ~0.90x, i.e. worse than random.)

Honest split: train < 2024-07 / val < 2025-07 / test >= 2025-07. Both models are
trained on train only; the full inspection history is then scored to build
per-license trajectories. Trajectory points are strictly <= each anchor date and
the forward label is strictly after it, so no model sees the future. XGBoost for
both models (matches run_forecast_surface_experiment; the production estimator is
LogReg but its pipeline hard-codes the feature list, so XGB is the clean
instrument for a drop-features spike and the conclusion transfers).

Run:
  FOODSAFETY_DATA_DIR=/abs/path/to/data PYTHONPATH=src \
    uv run python scripts/run_trend_deconfound_experiment.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from foodsafety.config import PROCESSED_DIR
from foodsafety.models.baseline import LABEL_COL
from foodsafety.models.xgb import (
    build_xgb_estimator,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    prepare_xgb_features,
)
from foodsafety.utils.time import temporal_split

REPO_ROOT = Path(__file__).resolve().parent.parent
FEATURES_PATH = PROCESSED_DIR / "features.parquet"
METRICS_DIR = REPO_ROOT / "reports" / "metrics"

TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"
CURRENT_OUTCOME = ["was_fail", "n_priority_this_inspection", "n_core_this_inspection"]
K_GRID = [3, 4, 5, 6, 8]  # last-K-visits sweep
OLD_WINDOW_DAYS = 90


def _fit(train, val, drop):
    """Fit an XGB model; return (clf, categorical_dtypes). ``drop`` -> MODEL 2."""
    Xtr = prepare_xgb_features(train)
    cat = extract_categorical_dtypes(Xtr)
    Xva = prepare_xgb_features(val, categorical_dtypes=cat)
    if drop:
        Xtr = Xtr.drop(columns=drop)
        Xva = Xva.drop(columns=drop)
    clf = build_xgb_estimator(scale_pos_weight=compute_scale_pos_weight(train[LABEL_COL]))
    clf.fit(Xtr, train[LABEL_COL], eval_set=[(Xva, val[LABEL_COL])], verbose=False)
    return clf, cat


def _slope(days: np.ndarray, ys: np.ndarray) -> float:
    """OLS slope of ys on day-offset; NaN if <2 points or degenerate x."""
    if len(ys) < 2 or np.ptp(days) == 0:
        return np.nan
    try:
        return float(np.polyfit(days - days.min(), ys, deg=1)[0])
    except (np.linalg.LinAlgError, ValueError):
        return np.nan


def _lift(label: np.ndarray, mask: np.ndarray, base: float) -> dict:
    """Forward fail-rate and lift-vs-base for the subset selected by ``mask``."""
    n = int(mask.sum())
    if n == 0:
        return {"n": 0, "fail_rate": None, "lift_vs_base": None}
    fr = float(label[mask].mean())
    return {"n": n, "fail_rate": round(fr, 4), "lift_vs_base": round(fr / base, 2)}


def main() -> None:
    df = pd.read_parquet(FEATURES_PATH)
    df["inspection_date"] = pd.to_datetime(df["inspection_date"])
    df = df.sort_values(["license_id", "inspection_date"]).reset_index(drop=True)

    split = temporal_split(df, train_end=TRAIN_END, val_end=VAL_END)
    train = split.train[~split.train["right_truncated"]].copy()
    val = split.val[~split.val["right_truncated"]].copy()

    print(f"train {len(train):,} / val {len(val):,} / test {len(split.test):,}")
    model_1, cat = _fit(train, val, drop=[])  # production: all features
    model_2, _ = _fit(train, val, drop=CURRENT_OUTCOME)  # forecast-only

    # Score the FULL history with both models (trajectory points).
    Xall = prepare_xgb_features(df, categorical_dtypes=cat)
    df["m1_score"] = model_1.predict_proba(Xall)[:, 1]
    df["m2_score"] = model_2.predict_proba(Xall.drop(columns=CURRENT_OUTCOME))[:, 1]

    # Anchors = each license's latest NON-right-truncated inspection in the test
    # split. Right-truncated rows sit too close to the data end for their 180-day
    # forward label to be observed; anchoring on the latest inspection without
    # this filter selects exactly those rows and collapses the base rate to ~0.
    test = split.test
    cand = test[~test["right_truncated"]]
    anchor_idx = cand.groupby("license_id")["inspection_date"].idxmax()
    anchors = df.loc[anchor_idx].reset_index(drop=True)
    print(
        f"test rows {len(test):,} (label mean {test[LABEL_COL].mean():.3f}) -> "
        f"non-truncated {len(cand):,} -> anchors {len(anchors):,} "
        f"(label mean {anchors[LABEL_COL].mean():.3f})"
    )

    # Per-license trajectory arrays (sorted by date), built once.
    hist = {
        lid: g
        for lid, g in df[["license_id", "inspection_date", "m1_score", "m2_score"]].groupby(
            "license_id"
        )
    }

    label = anchors[LABEL_COL].to_numpy().astype(int)
    was_fail = anchors["was_fail"].to_numpy().astype(bool)
    last_was_fail = anchors["last_was_fail"].to_numpy().astype(float)
    base = float(label.mean())
    clean = ~was_fail
    clean_base = float(label[clean].mean())
    n_anchor = len(anchors)
    print(
        f"\nanchors {n_anchor:,}  base-rate {base:.3f}  "
        f"clean(was_fail==0) {int(clean.sum()):,} ({clean.mean():.1%}) clean-base {clean_base:.3f}"
    )

    def _slopes(score_col: str, window: str, k: int | None = None) -> np.ndarray:
        """Slope per anchor for one (score, window) choice."""
        out: list[float] = []
        for lid, adate in anchors[["license_id", "inspection_date"]].itertuples(index=False):
            upto = hist[lid]
            upto = upto[upto["inspection_date"] <= adate]
            if window == "lastK":
                sel = upto.tail(k)
            else:  # 90-day calendar window, right-inclusive
                sel = upto[upto["inspection_date"] > adate - pd.Timedelta(days=OLD_WINDOW_DAYS)]
            d = sel["inspection_date"].to_numpy(dtype="datetime64[D]").astype(float)
            y = sel[score_col].to_numpy(dtype=float)
            out.append(_slope(d, y))
        return np.array(out, dtype=float)

    def _cov_confound(s: np.ndarray) -> dict:
        ok = ~np.isnan(s)
        if ok.sum() > 2 and np.ptp(last_was_fail[ok]) > 0 and np.nanstd(s[ok]) > 0:
            c = float(np.corrcoef(s[ok], last_was_fail[ok])[0, 1])
        else:
            c = None
        return {
            "coverage": round(float(ok.mean()), 4),
            "n_computable": int(ok.sum()),
            "confound_corr_last_was_fail": round(c, 4) if c is not None else None,
        }

    def _watch(s: np.ndarray) -> dict:
        """Clean-slice early-warning lift for one slope vector."""
        has = ~np.isnan(s)
        clean_has = clean & has
        res = {
            "clean_n_with_slope": int(clean_has.sum()),
            "loose_slope_gt_0": _lift(label, clean_has & (s > 0), base),
        }
        n_pos = int((clean_has & (s > 0)).sum())
        for tag, q in (("top10pct", 0.90), ("top20pct", 0.80)):
            if n_pos > 5:
                thr = float(np.quantile(s[clean_has], q))
                r = _lift(label, clean_has & (s >= thr), base)
                r["slope_threshold"] = round(thr, 6)
            else:
                r = {"n": 0, "fail_rate": None, "lift_vs_base": None}
            res[f"strict_{tag}"] = r
        return res

    # Old baseline: MODEL 1 score, 90-day window (what ships today). K-independent.
    s_old = _slopes("m1_score", "90d")
    baseline = {**_cov_confound(s_old), "clean_early_warning": _watch(s_old)}
    print(
        f"\nOLD baseline (model_1 score, 90d): coverage {baseline['coverage']:.3f}  "
        f"confound {baseline['confound_corr_last_was_fail']}  "
        f"clean strict-top10 lift {baseline['clean_early_warning']['strict_top10pct']['lift_vs_base']}"
    )

    # K sweep: MODEL 2 (forecast) score, last-K visits.
    print(f"\nK sweep (model_2 forecast score, last-K visits), base {base:.3f}:")
    sweep = {}
    for k in K_GRID:
        s = _slopes("m2_score", "lastK", k=k)
        entry = {**_cov_confound(s), "clean_early_warning": _watch(s)}
        sweep[str(k)] = entry
        w = entry["clean_early_warning"]
        print(
            f"  K={k}: coverage {entry['coverage']:.3f}  "
            f"confound {entry['confound_corr_last_was_fail']}  | "
            f"strict-top10 lift {w['strict_top10pct']['lift_vs_base']} "
            f"(n={w['strict_top10pct']['n']})  "
            f"strict-top20 {w['strict_top20pct']['lift_vs_base']}  "
            f"loose {w['loose_slope_gt_0']['lift_vs_base']}"
        )

    out = {
        "experiment": "trend_deconfound_last_k_visits_forecast",
        "date": date.today().isoformat(),
        "models": {
            "model_1_production": {
                "role": "shipped risk_score (unchanged by this experiment)",
                "predicts": "P(fail-or-priority within next 180 days)",
                "features": "all features, including the current inspection's own outcome",
            },
            "model_2_forecast_only": {
                "role": "used only to build the de-confounded trend trajectory",
                "predicts": "P(fail-or-priority within next 180 days)  -- SAME label/horizon",
                "features": "all features EXCEPT the current inspection's own outcome",
                "dropped_features": CURRENT_OUTCOME,
            },
            "trend": (
                "least-squares slope of a model's score over the last K visits; "
                "computed, not predicted by a model"
            ),
        },
        "config": {
            "k_grid": K_GRID,
            "old_window_days": OLD_WINDOW_DAYS,
            "estimator": "xgboost (both models)",
            "train_end": TRAIN_END,
            "val_end": VAL_END,
            "n_anchors": n_anchor,
            "base_rate": round(base, 4),
            "clean_base_rate": round(clean_base, 4),
        },
        "old_baseline_model1_90d": baseline,
        "k_sweep_model2_lastK": sweep,
    }
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = METRICS_DIR / f"trend_deconfound_experiment_{date.today().isoformat()}.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
