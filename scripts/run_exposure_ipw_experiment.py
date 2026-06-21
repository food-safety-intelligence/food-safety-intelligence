"""3A — Deconfound the label via exposure / inverse-propensity weighting (IPW).

The target ``y_fail_or_critical_next_180d`` is only *observable through an
inspection*: an event is recorded only if the city visits within the 180-day
window. So the label conflates "risky" with "frequently inspected" — a
heavily-visited place gets more chances to record a Fail/priority. This is the
last untried lever in docs/experiments.md (the modeling ceiling is INFORMATION,
not capacity): instead of adding features, we sharpen what the existing model
is trained to predict.

What this script does (diagnostic-first, per the 3A handoff):
  1. Build a leak-free EXPOSURE target — per (license_id, inspection_date), did
     a *next* inspection occur within 180 days? Built from the FULL inspection
     feed (inspections_labeled, includes non-modelable visits like "No Entry"
     that still represent the city showing up), then joined onto features.
  2. DIAGNOSE the cadence confound on the v36 served LogReg: how strongly does
     the risk score track inspection cadence / exposure propensity, and is the
     top decile over-represented by frequently-inspected licenses?
  3. Fit an exposure-PROPENSITY model p_i = P(next inspection within 180d | x)
     on the same leak-free as_of features the risk model uses.
  4. IPW A/B: refit the risk model with stabilized sample_weight = p_bar / p_i
     (down-weight high-cadence rows whose label-1 is partly an exposure
     artifact), A/B vs the unweighted v36 baseline, both models, same gate.

METHODOLOGICAL WRINKLE — read before judging the gate. The TEST labels are
themselves censored: a test-window event is only recorded if an inspection
happened there. IPW deconfounds the TRAINING set; it does NOT fix test-label
censoring. So the both-metrics gate measures "predicts OBSERVED events," not
"predicts TRUE risk" — deconfounding can LOWER apparent PR-AUC / P@10 while
being MORE correct. Judge partly on the DIAGNOSTIC (does the score's
correlation with exposure shrink, does the top decile stop being a cadence
artifact?), not the gate alone.

Eval discipline (unchanged): chronological split (train < 2024-07 /
val < 2025-07 / test >= 2025-07), honest-test protocol (train/val drop
right_truncated, score the FULL test n=13,812), both-metrics gate vs the frozen
v36 baseline, recall@10% by vulnerable-population group.

Run:
  FOODSAFETY_DATA_DIR=/abs/path/to/data PYTHONPATH=src \
    uv run python scripts/run_exposure_ipw_experiment.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from foodsafety.config import PROCESSED_DIR
from foodsafety.features.license_features import normalize_facility_type
from foodsafety.models.baseline import LABEL_COL, build_baseline_pipeline
from foodsafety.models.evaluate import evaluate, group_performance_audit
from foodsafety.models.xgb import (
    build_xgb_estimator,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    prepare_xgb_features,
)
from foodsafety.utils.time import temporal_split

REPO_ROOT = Path(__file__).resolve().parent.parent
FEATURES_PATH = PROCESSED_DIR / "features.parquet"
INSPECTIONS_PATH = PROCESSED_DIR / "inspections_labeled.parquet"
METRICS_DIR = REPO_ROOT / "reports" / "metrics"

TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"
WINDOW_DAYS = 180  # same forward window as the label

# Published v36 honest-test baseline (docs/experiments.md) — the gate reference.
V36_BASELINE = {"logreg": (0.332, 0.370), "xgb": (0.338, 0.376)}
VULNERABLE_GROUPS = {
    "Children's Services Facility",
    "Daycare",
    "School",
    "Long Term Care",
    "Hospital",
    "Shelter",
}

# Propensity clipping — keep 1/p_i finite and stop a handful of extreme weights
# from dominating the loss. p floored/capped, then the stabilized weight is
# winsorized to its [1st, 99th] percentile.
P_FLOOR, P_CEIL = 0.02, 0.98


def build_exposure_target(insp: pd.DataFrame, window_days: int = WINDOW_DAYS) -> pd.DataFrame:
    """Per (license_id, inspection_date): did a NEXT inspection occur within ``window_days``?

    EXPOSURE, not the risk label: the event is "the city visited again," any
    result (a No-Entry or Out-of-Business visit still counts as exposure — it is
    a chance for the next real inspection). Leak-free by construction: it looks
    strictly FORWARD from the anchor, never at the anchor's own row.

    ``exposure_censored`` marks anchors whose full forward window extends past
    the dataset's last date — exposure is unobservable there (mirrors the
    label's ``right_truncated``); the propensity model drops them.

    Returns one row per distinct (license_id, inspection_date) with
    ``exposure_next_180d`` (int8) and ``exposure_censored`` (bool).
    """
    insp = insp[["license_id", "inspection_date"]].copy()
    insp["inspection_date"] = pd.to_datetime(insp["inspection_date"])
    insp = insp.dropna(subset=["license_id", "inspection_date"])

    win = np.timedelta64(window_days, "D")
    dmax = np.datetime64(insp["inspection_date"].max())

    # Per-license sorted UNIQUE visit dates from the full feed — the forward
    # scan needs every visit, not just the modelable subset in features.parquet.
    sorted_dates = {
        lic: np.sort(s.unique()) for lic, s in insp.groupby("license_id")["inspection_date"]
    }

    anchors = insp.drop_duplicates(["license_id", "inspection_date"]).reset_index(drop=True)
    lic_arr = anchors["license_id"].to_numpy()
    date_arr = anchors["inspection_date"].to_numpy()
    exposure = np.zeros(len(anchors), dtype=np.int8)
    censored = (date_arr + win) > dmax

    for i in range(len(anchors)):
        uds = sorted_dates[lic_arr[i]]
        # First visit date strictly AFTER the anchor (same-day siblings excluded
        # — they are concurrent, not a future visit).
        pos = np.searchsorted(uds, date_arr[i], side="right")
        if pos < len(uds) and (uds[pos] - date_arr[i]) <= win:
            exposure[i] = 1

    anchors["exposure_next_180d"] = exposure
    anchors["exposure_censored"] = censored
    return anchors


def _winsorize(w: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(w, [1, 99])
    return np.clip(w, lo, hi)


def ipw_weights_inv_p(p: np.ndarray, p_bar: float) -> np.ndarray:
    """Handoff-literal ``sample_weight ∝ 1/p_i`` (stabilized by ``p_bar``, winsorized).

    Down-weights high-propensity (frequently-revisited) rows whose label-1 is
    partly an exposure artifact, up-weights rarely-revisited rows — applied to
    EVERY row regardless of its own exposure outcome.
    """
    return _winsorize(p_bar / np.clip(p, P_FLOOR, P_CEIL))


def ipw_weights_two_arm(p: np.ndarray, e: np.ndarray, p_bar: float) -> np.ndarray:
    """Textbook stabilized selection weights — numerator matches the row's exposure.

    ``w = P(E=e_i) / P(E=e_i | x_i)``: exposed rows get ``p_bar/p_i``, unexposed
    get ``(1-p_bar)/(1-p_i)``. Keeps the mean weight ~1 (gentler than inv-p) and
    is the standard inverse-probability-of-selection form — run as a robustness
    arm so the null isn't an artifact of the inv-p estimand.
    """
    pc = np.clip(p, P_FLOOR, P_CEIL)
    w = np.where(e == 1, p_bar / pc, (1.0 - p_bar) / (1.0 - pc))
    return _winsorize(w)


def _fit_logreg(train, val, test, sample_weight=None):
    pipe = build_baseline_pipeline()
    fit_params = {} if sample_weight is None else {"model__sample_weight": sample_weight}
    pipe.fit(train, train[LABEL_COL], **fit_params)
    return pipe.predict_proba(test)[:, 1]


def _fit_xgb(train, val, test, sample_weight=None):
    Xtr = prepare_xgb_features(train)
    cat_dtypes = extract_categorical_dtypes(Xtr)
    Xva = prepare_xgb_features(val, categorical_dtypes=cat_dtypes)
    Xte = prepare_xgb_features(test, categorical_dtypes=cat_dtypes)
    spw = compute_scale_pos_weight(train[LABEL_COL])
    clf = build_xgb_estimator(scale_pos_weight=spw)
    clf.fit(
        Xtr,
        train[LABEL_COL],
        sample_weight=sample_weight,
        eval_set=[(Xva, val[LABEL_COL])],
        verbose=False,
    )
    return clf.predict_proba(Xte)[:, 1]


def _fit_propensity(train, val, test):
    """P(next inspection within 180d | leak-free as_of features), both splits scored.

    Uses the SAME feature contract as the risk model (cadence + history +
    facility type + the current visit's own outcome — a Fail triggers a
    mandated re-inspection, the dominant exposure mechanism, and it is known at
    as_of_date so it is leak-free for predicting a FUTURE visit). No
    ``scale_pos_weight`` — we want calibrated propensities, not balanced ranking.
    """
    Xtr = prepare_xgb_features(train)
    cat_dtypes = extract_categorical_dtypes(Xtr)
    Xva = prepare_xgb_features(val, categorical_dtypes=cat_dtypes)
    Xte = prepare_xgb_features(test, categorical_dtypes=cat_dtypes)
    clf = build_xgb_estimator()  # scale_pos_weight=None → probabilities
    clf.fit(
        Xtr,
        train["exposure_next_180d"],
        eval_set=[(Xva, val["exposure_next_180d"])],
        verbose=False,
    )
    return (
        clf.predict_proba(Xtr)[:, 1],
        clf.predict_proba(Xte)[:, 1],
        evaluate(val["exposure_next_180d"].to_numpy(), clf.predict_proba(Xva)[:, 1]).to_dict(),
    )


def _gate(m, base_pr, base_p10):
    return bool(m["pr_auc"] > base_pr and m["precision_at_10pct"] > base_p10)


def main() -> None:
    df = pd.read_parquet(FEATURES_PATH)
    df["inspection_date"] = pd.to_datetime(df["inspection_date"])

    # --- exposure target, joined on (license_id, inspection_date) ---
    insp = pd.read_parquet(INSPECTIONS_PATH, columns=["license_id", "inspection_date"])
    exposure = build_exposure_target(insp)
    df = df.merge(exposure, on=["license_id", "inspection_date"], how="left")
    miss = df["exposure_next_180d"].isna().sum()
    if miss:
        # Anchors absent from the full feed shouldn't happen — fail loud.
        raise RuntimeError(f"{miss} feature rows have no exposure match")
    df["exposure_next_180d"] = df["exposure_next_180d"].astype("int8")
    print(
        f"rows {len(df):,}  exposure base-rate {df['exposure_next_180d'].mean():.3f}  "
        f"label base-rate {df[LABEL_COL].astype(float).mean():.3f}"
    )

    # --- honest split: train/val drop right_truncated; score the FULL test ---
    split = temporal_split(df, train_end=TRAIN_END, val_end=VAL_END)
    train = split.train[~split.train["right_truncated"]].copy()
    val = split.val[~split.val["right_truncated"]].copy()
    test = split.test.copy()
    print(f"train {len(train):,} / val {len(val):,} / test {len(test):,} (honest, full test)")
    print(
        f"train exposure {train['exposure_next_180d'].mean():.3f}  "
        f"label {train[LABEL_COL].astype(float).mean():.3f}"
    )

    y_test = test[LABEL_COL].to_numpy()

    # --- propensity model + stabilized IPW weights ---
    p_train, p_test, prop_eval = _fit_propensity(train, val, test)
    p_bar = float(train["exposure_next_180d"].mean())
    e_train = train["exposure_next_180d"].to_numpy()
    weight_arms = {
        "inv_p": ipw_weights_inv_p(p_train, p_bar),
        "two_arm": ipw_weights_two_arm(p_train, e_train, p_bar),
    }
    print(
        f"\npropensity (val): ROC-AUC {prop_eval['roc_auc']:.3f}  PR-AUC {prop_eval['pr_auc']:.3f}"
    )
    for arm, w in weight_arms.items():
        print(f"  IPW[{arm}] weights: mean {w.mean():.2f} [{w.min():.2f}, {w.max():.2f}]")

    # ------------------------------------------------------------------
    # DIAGNOSTIC — quantify the cadence confound on the control risk score.
    # ------------------------------------------------------------------
    s_ctrl_lr = _fit_logreg(train, val, test)
    inv_recency = 1.0 / (test["days_since_last_inspection"].fillna(10_000).to_numpy() + 1.0)
    diag = {
        "spearman_score_vs_prior_inspections": round(
            float(spearmanr(s_ctrl_lr, test["prior_inspections"].to_numpy()).statistic), 4
        ),
        "spearman_score_vs_inv_recency": round(
            float(spearmanr(s_ctrl_lr, inv_recency).statistic), 4
        ),
        "spearman_score_vs_exposure_propensity": round(
            float(spearmanr(s_ctrl_lr, p_test).statistic), 4
        ),
    }
    # Top-decile composition: is it a cadence artifact?
    k = max(1, int(np.ceil(len(test) * 0.10)))
    top_idx = np.argsort(-s_ctrl_lr, kind="stable")[:k]
    diag["top_decile"] = {
        "mean_prior_inspections": round(
            float(test["prior_inspections"].to_numpy()[top_idx].mean()), 3
        ),
        "overall_mean_prior_inspections": round(float(test["prior_inspections"].mean()), 3),
        "mean_exposure_propensity": round(float(p_test[top_idx].mean()), 4),
        "overall_mean_exposure_propensity": round(float(p_test.mean()), 4),
        "frac_was_fail": round(float(test["was_fail"].to_numpy()[top_idx].mean()), 4),
        "overall_frac_was_fail": round(float(test["was_fail"].mean()), 4),
    }
    print("\nDIAGNOSTIC — control LogReg score vs cadence/exposure:")
    for kk, vv in diag.items():
        if kk != "top_decile":
            print(f"  {kk}: {vv}")
    print(f"  top-decile composition: {diag['top_decile']}")

    # ------------------------------------------------------------------
    # IPW A/B — refit both risk models under each weight arm, A/B vs the
    # unweighted control. The deconfounding check is corr(score, exposure):
    # if IPW worked it should SHRINK vs control, independent of the gate.
    # ------------------------------------------------------------------
    results, scores = {}, {}
    for name, fit in (("logreg", _fit_logreg), ("xgb", _fit_xgb)):
        s_ctrl = s_ctrl_lr if name == "logreg" else fit(train, val, test)
        ctrl = evaluate(y_test, s_ctrl).to_dict()
        base_pr, base_p10 = V36_BASELINE[name]
        corr_ctrl = round(float(spearmanr(s_ctrl, p_test).statistic), 4)
        results[name] = {
            "control": ctrl,
            "spearman_score_vs_exposure_ctrl": corr_ctrl,
            "arms": {},
        }
        scores[name] = {"control": s_ctrl, "arms": {}}
        print(
            f"\n[{name}] control PR-AUC {ctrl['pr_auc']:.4f} P@10 {ctrl['precision_at_10pct']:.4f}"
        )
        for arm, w in weight_arms.items():
            s_treat = fit(train, val, test, sample_weight=w)
            treat = evaluate(y_test, s_treat).to_dict()
            corr_treat = round(float(spearmanr(s_treat, p_test).statistic), 4)
            results[name]["arms"][arm] = {
                "treatment": treat,
                "delta_pr_auc": round(treat["pr_auc"] - ctrl["pr_auc"], 6),
                "delta_precision_at_10pct": round(
                    treat["precision_at_10pct"] - ctrl["precision_at_10pct"], 6
                ),
                "clears_gate_vs_control": _gate(treat, ctrl["pr_auc"], ctrl["precision_at_10pct"]),
                "clears_gate_vs_v36_published": _gate(treat, base_pr, base_p10),
                "spearman_score_vs_exposure_treat": corr_treat,
            }
            scores[name]["arms"][arm] = s_treat
            print(
                f"  [{arm:7s}] PR-AUC ->{treat['pr_auc']:.4f} "
                f"(Δ{results[name]['arms'][arm]['delta_pr_auc']:+.4f}) | "
                f"P@10 ->{treat['precision_at_10pct']:.4f} "
                f"(Δ{results[name]['arms'][arm]['delta_precision_at_10pct']:+.4f}) | "
                f"gate: {results[name]['arms'][arm]['clears_gate_vs_control']} | "
                f"corr(score,exposure) {corr_ctrl}->{corr_treat}"
            )

    # --- Fairness: production LogReg, recall@10% by vulnerable group ---
    # Audited on the inv_p arm (the handoff-literal weighting).
    groups = test["facility_type"].map(normalize_facility_type)
    s_ctrl = scores["logreg"]["control"]
    s_treat = scores["logreg"]["arms"]["inv_p"]
    fair_ctrl = group_performance_audit(y_test, s_ctrl, groups).set_index("group")
    fair_treat = group_performance_audit(y_test, s_treat, groups).set_index("group")
    fairness = {}
    print("\nFairness — recall@10% by vulnerable group (LogReg, control -> inv_p treatment):")
    for g in sorted(VULNERABLE_GROUPS):
        if g in fair_treat.index:
            rc = float(fair_ctrl.loc[g, "recall_at_k"]) if g in fair_ctrl.index else None
            rt = float(fair_treat.loc[g, "recall_at_k"])
            fairness[g] = {"n": int(fair_treat.loc[g, "n"]), "recall_ctrl": rc, "recall_treat": rt}
            print(f"  {g:32s} n={fairness[g]['n']:4d}  {rc} -> {rt}")

    out = {
        "experiment": "exposure_ipw_deconfound_label_3a",
        "date": date.today().isoformat(),
        "config": {
            "window_days": WINDOW_DAYS,
            "train_end": TRAIN_END,
            "val_end": VAL_END,
            "n_test": int(len(test)),
            "exposure_base_rate_train": round(p_bar, 4),
            "p_clip": [P_FLOOR, P_CEIL],
            "propensity_model": "xgb (no scale_pos_weight)",
            "propensity_val_eval": prop_eval,
            "ipw_weight_summary": {
                arm: {
                    "mean": round(float(w.mean()), 4),
                    "min": round(float(w.min()), 4),
                    "max": round(float(w.max()), 4),
                }
                for arm, w in weight_arms.items()
            },
        },
        "v36_published_baseline": V36_BASELINE,
        "diagnostic": diag,
        "results": results,
        "fairness_vulnerable_groups": fairness,
        "wrinkle": (
            "TEST labels are also censored (event observed only if an inspection "
            "occurred in the test window). IPW deconfounds TRAINING only; the gate "
            "measures predicted OBSERVED events, so a flat/down gate is not proof "
            "deconfounding failed — read the diagnostic (corr(score,exposure)) too."
        ),
    }
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = METRICS_DIR / f"exposure_ipw_experiment_{date.today().isoformat()}.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
