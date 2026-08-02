"""Conditional next-inspection label study — is the 180-day window the right target?

Motivation (Korin's censoring critique + instructor feedback, July 2026): the
served label ``y_fail_or_critical_next_180d`` is 1 only when a Fail/priority
event is OBSERVED within 180 days — and ~67% of anchors receive no follow-up
visit inside that window, so most of the 0 class is "nobody came", not
"inspected and clean" (a scheduling artifact; see ``labels.py`` and the 3A
exposure-IPW experiment: scheduling is highly predictable, but IPW reweighting
does not help). This experiment tests the framing the original Chicago model
and the 2019 audit literature use instead: predict the OUTCOME OF THE NEXT
INSPECTION, GIVEN one occurs — anchors without a qualifying successor are
DROPPED (never zeroed).

Arms (label definitions), all on the same feature contract + chronological split:
  control            y_fail_or_critical_next_180d (served label, honest protocol)
  cond_365 (primary) next modelable inspection's fail-or-priority, gap <= 365d
  cond_nocap         same, no gap cap
  cond_365_canvass   successor restricted to non-re-inspection visits, gap <= 365d
                     (~35% of successors are the mandated ~30d re-checks, whose
                     pass rate is systematically higher — "will the re-check
                     clear" is a different question from "is this place risky")

READ-ME-FIRST on metrics: PR-AUC / P@K are NOT comparable across label
definitions — prevalence differs by arm (~13% vs ~37-46%) and PR-AUC scales
with the base rate. Judge arms on LIFT (metric / prevalence) and on the
cross-evaluation (how well the control-trained model already ranks each arm's
outcome). There is deliberately NO promotion gate: this is a target-definition
study, not a feature A/B — promoting a different label is a product/contract
decision (DR 0007 territory), not a metrics call.

Leakage notes:
  * Conditional labels need no ``right_truncated`` analog: an anchor whose
    forward window is cut off by the dataset edge has no observed successor and
    is simply undefined (dropped) — never a fake 0.
  * Train-tail overlap mirrors the single-split scripts' existing posture (a
    train anchor's label may be observed after TRAIN_END). The JSON records the
    overlap fraction per arm so the writeup can quantify it rather than hide it.

Run:
  FOODSAFETY_DATA_DIR=/abs/path/to/data PYTHONPATH=src \
    uv run python scripts/run_conditional_label_experiment.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from foodsafety.config import PROCESSED_DIR
from foodsafety.data.labels import MODELABLE_RESULTS
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
CAP_DAYS = 365  # primary-arm gap cap: bounds staleness + the split-overlap tail

VULNERABLE_GROUPS = {
    "Children's Services Facility",
    "Daycare",
    "School",
    "Long Term Care",
    "Hospital",
    "Shelter",
}

ARMS = ("cond_365", "cond_nocap", "cond_365_canvass")


def build_conditional_labels(insp: pd.DataFrame) -> pd.DataFrame:
    """Per (license_id, inspection_date) anchor: the next modelable inspection's
    outcome and gap, plus the same restricted to non-re-inspection successors.

    Only MODELABLE results (Pass / Pass w/ Conditions / Fail) can be a
    successor — "No Entry" / "Out of Business" visits carry no food-safety
    outcome. Same-day sibling rows collapse to one per-date outcome (any
    fail/priority that day counts); the successor search is strictly-after, so
    same-day siblings are concurrent, not future (mirrors the exposure
    experiment's convention).

    Returns one row per anchor with ``next_gap_days`` / ``next_flag`` and
    ``canvass_gap_days`` / ``canvass_flag`` (NaN where no successor exists).
    """
    cols = ["license_id", "inspection_date", "inspection_type", "results", "is_fail_or_priority"]
    mod = insp[cols].copy()
    mod["inspection_date"] = pd.to_datetime(mod["inspection_date"])
    mod = mod.dropna(subset=["license_id", "inspection_date"])
    mod = mod[mod["results"].isin(MODELABLE_RESULTS)]

    per_date = (
        mod.groupby(["license_id", "inspection_date"], sort=False)
        .agg(flag=("is_fail_or_priority", "max"))
        .reset_index()
        .sort_values(["license_id", "inspection_date"], kind="stable")
    )
    g = per_date.groupby("license_id", sort=False)
    # Unique per-license dates, so shift(-1) IS the strictly-next modelable visit.
    per_date["next_date"] = g["inspection_date"].shift(-1)
    per_date["next_flag"] = g["flag"].shift(-1)
    per_date["next_gap_days"] = (per_date["next_date"] - per_date["inspection_date"]).dt.days

    # Non-re-inspection successors: a mandated ~30d re-check is a different
    # prediction question, so this arm skips over them to the next
    # canvass/complaint/license visit. merge_asof(direction="forward",
    # allow_exact_matches=False) = first such visit strictly after the anchor.
    nonre = mod[~mod["inspection_type"].str.contains("Re-Inspection", case=False, na=False)]
    nonre_pd = (
        nonre.groupby(["license_id", "inspection_date"], sort=False)
        .agg(canvass_flag=("is_fail_or_priority", "max"))
        .reset_index()
        .rename(columns={"inspection_date": "canvass_date"})
        .sort_values("canvass_date", kind="stable")
    )
    anchors = per_date.sort_values("inspection_date", kind="stable")
    merged = pd.merge_asof(
        anchors,
        nonre_pd,
        by="license_id",
        left_on="inspection_date",
        right_on="canvass_date",
        direction="forward",
        allow_exact_matches=False,
    )
    merged["canvass_gap_days"] = (merged["canvass_date"] - merged["inspection_date"]).dt.days
    keep = [
        "license_id",
        "inspection_date",
        "next_gap_days",
        "next_flag",
        "canvass_gap_days",
        "canvass_flag",
    ]
    return merged[keep]


def _fit_logreg(train: pd.DataFrame, test: pd.DataFrame, ycol: str) -> np.ndarray:
    pipe = build_baseline_pipeline()
    pipe.fit(train, train[ycol].astype(int))
    return pipe.predict_proba(test)[:, 1]


def _fit_xgb(train: pd.DataFrame, val: pd.DataFrame, test: pd.DataFrame, ycol: str) -> np.ndarray:
    Xtr = prepare_xgb_features(train)
    cat_dtypes = extract_categorical_dtypes(Xtr)
    Xva = prepare_xgb_features(val, categorical_dtypes=cat_dtypes)
    Xte = prepare_xgb_features(test, categorical_dtypes=cat_dtypes)
    # Per-arm imbalance handling: conditional prevalences (~37-46%) are far
    # milder than the control's ~13%, so spw is recomputed per label.
    spw = compute_scale_pos_weight(train[ycol].astype(int))
    clf = build_xgb_estimator(scale_pos_weight=spw)
    clf.fit(Xtr, train[ycol].astype(int), eval_set=[(Xva, val[ycol].astype(int))], verbose=False)
    return clf.predict_proba(Xte)[:, 1]


def _arm_metrics(y: np.ndarray, s: np.ndarray) -> dict:
    m = evaluate(y, s).to_dict()
    prev = float(y.mean())
    # Lift = metric / prevalence: the only fair basis for comparing label
    # definitions with different base rates (raw PR-AUC scales with prevalence).
    m["prevalence"] = round(prev, 4)
    m["lift_pr_auc"] = round(m["pr_auc"] / prev, 3) if prev > 0 else None
    m["lift_p10"] = round(m["precision_at_10pct"] / prev, 3) if prev > 0 else None
    return m


def main() -> None:
    df = pd.read_parquet(FEATURES_PATH)
    df["inspection_date"] = pd.to_datetime(df["inspection_date"])

    insp = pd.read_parquet(INSPECTIONS_PATH)
    cond = build_conditional_labels(insp)
    df = df.merge(cond, on=["license_id", "inspection_date"], how="left")
    if df["next_gap_days"].isna().all():
        raise RuntimeError("conditional-label join produced no matches — key mismatch?")

    # Arm labels: defined iff a qualifying successor exists — NaN (dropped)
    # otherwise. Never 0 for "nobody came": that is the artifact under study.
    df["y_cond_nocap"] = df["next_flag"]
    df["y_cond_365"] = df["next_flag"].where(df["next_gap_days"] <= CAP_DAYS)
    df["y_cond_365_canvass"] = df["canvass_flag"].where(df["canvass_gap_days"] <= CAP_DAYS)

    coverage = {
        "n_anchors": int(len(df)),
        "frac_with_successor": round(float(df["next_flag"].notna().mean()), 4),
        "frac_successor_within_cap": round(float((df["next_gap_days"] <= CAP_DAYS).mean()), 4),
        "gap_days_quantiles": {
            q: float(df["next_gap_days"].quantile(q)) for q in (0.25, 0.5, 0.75, 0.9)
        },
    }
    print(
        f"anchors {coverage['n_anchors']:,}  with-successor {coverage['frac_with_successor']:.1%}"
    )

    split = temporal_split(df, train_end=TRAIN_END, val_end=VAL_END)

    results: dict[str, dict] = {}
    scores_ctrl: dict[str, np.ndarray] = {}

    # ---- control: the served label under the production honest protocol ----
    tr_c = split.train[~split.train["right_truncated"]].copy()
    va_c = split.val[~split.val["right_truncated"]].copy()
    te_c = split.test.copy()
    y_te_c = te_c[LABEL_COL].astype(int).to_numpy()
    results["control"] = {"n_train": int(len(tr_c)), "n_test": int(len(te_c)), "models": {}}
    for model in ("logreg", "xgb"):
        s = (
            _fit_logreg(tr_c, te_c, LABEL_COL)
            if model == "logreg"
            else _fit_xgb(tr_c, va_c, te_c, LABEL_COL)
        )
        scores_ctrl[model] = s
        results["control"]["models"][model] = _arm_metrics(y_te_c, s)
        m = results["control"]["models"][model]
        print(
            f"[control/{model}] prev {m['prevalence']:.3f}  PR-AUC {m['pr_auc']:.4f} "
            f"(lift {m['lift_pr_auc']})  P@10 {m['precision_at_10pct']:.4f} (lift {m['lift_p10']})"
        )

    # ---- conditional arms: rows with a defined label only ----
    for arm in ARMS:
        ycol = f"y_{arm}"
        tr = split.train[split.train[ycol].notna()].copy()
        va = split.val[split.val[ycol].notna()].copy()
        te = split.test[split.test[ycol].notna()].copy()
        y_te = te[ycol].astype(int).to_numpy()
        # Quantified honestly rather than embargoed away: fraction of train
        # labels observed after each split boundary (the control's 180d window
        # has the same overlap class, just shorter).
        next_dates = tr["inspection_date"] + pd.to_timedelta(tr["next_gap_days"], unit="D")
        overlap = {
            "frac_train_label_observed_after_train_end": round(
                float((next_dates > pd.Timestamp(TRAIN_END)).mean()), 4
            ),
            "frac_train_label_observed_after_val_end": round(
                float((next_dates > pd.Timestamp(VAL_END)).mean()), 4
            ),
        }
        results[arm] = {
            "n_train": int(len(tr)),
            "n_val": int(len(va)),
            "n_test": int(len(te)),
            "train_tail_overlap": overlap,
            "models": {},
        }
        for model in ("logreg", "xgb"):
            s = _fit_logreg(tr, te, ycol) if model == "logreg" else _fit_xgb(tr, va, te, ycol)
            arm_m = _arm_metrics(y_te, s)
            # Cross-eval: the CONTROL-trained model scored against this arm's
            # outcome on the same test rows — if its lift already matches the
            # retrained arm, the served model answers the conditional question
            # without a label change.
            mask = split.test[ycol].notna().to_numpy()
            cross = _arm_metrics(y_te, scores_ctrl[model][mask])
            results[arm]["models"][model] = {"retrained": arm_m, "control_cross_eval": cross}
            print(
                f"[{arm}/{model}] n_test {len(te):,}  prev {arm_m['prevalence']:.3f}  "
                f"PR-AUC {arm_m['pr_auc']:.4f} (lift {arm_m['lift_pr_auc']}) | "
                f"cross-eval lift {cross['lift_pr_auc']}"
            )

    # ---- fairness guard: primary arm vs control, LogReg recall@10% ----
    te_p = split.test[split.test["y_cond_365"].notna()]
    y_p = te_p["y_cond_365"].astype(int).to_numpy()
    tr_p = split.train[split.train["y_cond_365"].notna()]
    s_p = _fit_logreg(tr_p, te_p, "y_cond_365")
    groups = te_p["facility_type"].map(normalize_facility_type)
    fair = group_performance_audit(y_p, s_p, groups).set_index("group")
    fairness = {}
    for grp in sorted(VULNERABLE_GROUPS):
        if grp in fair.index:
            fairness[grp] = {
                "n": int(fair.loc[grp, "n"]),
                "recall_at_10pct": float(fair.loc[grp, "recall_at_k"]),
            }

    out = {
        "experiment": "conditional_next_inspection_label",
        "date": date.today().isoformat(),
        "config": {
            "train_end": TRAIN_END,
            "val_end": VAL_END,
            "cap_days": CAP_DAYS,
            "modelable_results": sorted(MODELABLE_RESULTS),
            "arms": list(ARMS),
        },
        "label_coverage": coverage,
        "results": results,
        "fairness_recall_at_10pct_cond_365_logreg": fairness,
        "read_me": (
            "PR-AUC/P@K are not comparable across arms (prevalence differs); compare "
            "lift_pr_auc / lift_p10. control_cross_eval = control-trained model scored "
            "against the arm's label on the arm's test rows. No promotion gate: label "
            "changes are a product/contract decision (DR 0007)."
        ),
    }
    experiments_dir = METRICS_DIR / "experiments"
    experiments_dir.mkdir(parents=True, exist_ok=True)
    out_path = experiments_dir / f"conditional_label_experiment_{date.today().isoformat()}.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
