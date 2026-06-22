"""Routine-only target reframe — predict/evaluate on CANVASS inspections only.

The model's top risk decile is ~91% places that JUST FAILED (docs/experiments.md):
a failed inspection mandates a re-inspection that lands inside the 180-day label
window, so the model largely relearns the re-inspection cycle rather than
forecasting risk. Re-inspection anchors are, by construction, conditioned on a
recent failure — so scoring them is close to circular.

This reframe removes those anchors from the *target population*: train and
evaluate on routine ``Canvass`` inspections only, the operationally meaningful
question ("which place NOT already on our radar should we proactively visit?").
Re-inspection / complaint / license rows stay in the feature build as HISTORY —
they already feed the ``prior_*`` aggregates — they're just never anchors here.

Honest read of what this can and cannot do:
  * It drops the re-inspection anchors that the v36 top decile is mostly built
    from. It does NOT remove the ``was_fail`` -> mandated-re-inspection mechanism
    for a failing *canvass* (that re-inspection still lands in the window). So
    this is a partial deconfound; the script MEASURES the residual via the
    top-decile ``was_fail`` composition rather than assuming it away.
  * Headline PR-AUC / P@10 will LOOK lower than v36 because we deleted the
    easiest-to-rank rows. That is not a regression. The honest comparison is
    routine-only vs the SAME current model evaluated on the SAME canvass test
    set (``full_on_canvass``) — NOT vs the v36 full-test numbers. The script
    reports all three so the population effect and the model effect are separable.

Three arms per model (LogReg served baseline + XGBoost):
  1. ``full_baseline``    — train on ALL anchors, eval on the FULL test. Should
                            reproduce the published v36 honest-test numbers; a
                            harness sanity check.
  2. ``full_on_canvass``  — the SAME full-trained model, eval on the CANVASS test
                            subset. The honest baseline the reframe must beat:
                            "how good is today's model on the non-circular slice?"
  3. ``routine_only``     — train on CANVASS anchors, eval on the CANVASS test.
                            The reframe. Both-metrics gate is vs arm 2 (same test).

Eval discipline (unchanged): chronological split (train < 2024-07 / val < 2025-07
/ test >= 2025-07); honest protocol (train/val drop right_truncated; score the
full test set, matching run_exposure_ipw_experiment.py). A promising single-split
result is NOT final — the next step is expanding_year_folds CV (single-split wins
get killed by CV throughout this project).

Run:
  FOODSAFETY_DATA_DIR=/abs/path/to/data PYTHONPATH=src \
    uv run python scripts/run_routine_only_experiment.py
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
METRICS_DIR = REPO_ROOT / "reports" / "metrics"

TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"

# Published v36 honest-test (FULL-test) baseline (docs/experiments.md) — only a
# reference for the full_baseline sanity arm; the gate for the reframe is the
# same-test full_on_canvass arm, NOT these.
V36_FULL_TEST = {"logreg": (0.332, 0.370), "xgb": (0.338, 0.376)}
VULNERABLE_GROUPS = {
    "Children's Services Facility",
    "Daycare",
    "School",
    "Long Term Care",
    "Hospital",
    "Shelter",
}


def canvass_mask(df: pd.DataFrame) -> pd.Series:
    """Routine ``Canvass`` anchors only — exact match, case/space-insensitive.

    Excludes ``Canvass Re-Inspection`` (and every other re-inspection / complaint
    / license type): those are the anchors selected on a recent failure that this
    reframe is removing from the target population.
    """
    it = df["inspection_type"].astype("string").str.strip().str.casefold()
    return it.eq("canvass").fillna(False)


def _train_logreg(train: pd.DataFrame):
    """Fit the served LogReg baseline, return a scorer over any frame.

    Uncalibrated probabilities: PR-AUC / precision@k are rank metrics and
    calibration-invariant, so the gate is unaffected (same choice as the IPW run).
    """
    pipe = build_baseline_pipeline()
    pipe.fit(train, train[LABEL_COL])
    return lambda X: pipe.predict_proba(X)[:, 1]


def _train_xgb(train: pd.DataFrame, val: pd.DataFrame):
    """Fit XGBoost (early-stop on ``val``), return a scorer over any frame."""
    Xtr = prepare_xgb_features(train)
    cat_dtypes = extract_categorical_dtypes(Xtr)
    Xva = prepare_xgb_features(val, categorical_dtypes=cat_dtypes)
    spw = compute_scale_pos_weight(train[LABEL_COL])
    clf = build_xgb_estimator(scale_pos_weight=spw)
    clf.fit(Xtr, train[LABEL_COL], eval_set=[(Xva, val[LABEL_COL])], verbose=False)
    return lambda X: clf.predict_proba(prepare_xgb_features(X, categorical_dtypes=cat_dtypes))[:, 1]


def _top_decile_diag(test: pd.DataFrame, scores: np.ndarray) -> dict:
    """Does the was_fail -> re-inspection circularity persist in the top decile?

    ``frac_was_fail`` near the overall rate means the ranking is NOT just
    surfacing recent failers; near 0.9 (the v36 full-test value) means the
    circularity carried over even onto canvass anchors.
    """
    k = max(1, int(np.ceil(len(scores) * 0.10)))
    top = np.argsort(-scores, kind="stable")[:k]
    return {
        "top_decile_frac_was_fail": round(float(test["was_fail"].to_numpy()[top].mean()), 4),
        "overall_frac_was_fail": round(float(test["was_fail"].mean()), 4),
        "spearman_score_vs_was_fail": round(
            float(spearmanr(scores, test["was_fail"].to_numpy()).statistic), 4
        ),
    }


def _gate(m: dict, base_pr: float, base_p10: float) -> bool:
    return bool(m["pr_auc"] > base_pr and m["precision_at_10pct"] > base_p10)


def main() -> None:
    df = pd.read_parquet(FEATURES_PATH)
    df["inspection_date"] = pd.to_datetime(df["inspection_date"])
    is_canvass = canvass_mask(df)
    print(
        f"rows {len(df):,}  canvass {int(is_canvass.sum()):,} ({is_canvass.mean():.1%})  "
        f"label base-rate full {df[LABEL_COL].astype(float).mean():.3f} / "
        f"canvass {df.loc[is_canvass, LABEL_COL].astype(float).mean():.3f}"
    )

    # --- honest split: train/val drop right_truncated; score the FULL test ---
    split = temporal_split(df, train_end=TRAIN_END, val_end=VAL_END)
    train_full = split.train[~split.train["right_truncated"]].copy()
    val_full = split.val[~split.val["right_truncated"]].copy()
    test_full = split.test.copy()

    # Routine-only target population = canvass anchors within each split. Same
    # right_truncated honesty on train/val; canvass test is the canvass slice of
    # the full test (kept whole for an apples-to-apples vs full_on_canvass).
    train_can = train_full[canvass_mask(train_full)].copy()
    val_can = val_full[canvass_mask(val_full)].copy()
    test_can = test_full[canvass_mask(test_full)].copy()
    print(
        f"train_full {len(train_full):,} / val_full {len(val_full):,} / test_full {len(test_full):,}\n"
        f"train_can  {len(train_can):,} / val_can  {len(val_can):,} / test_can  {len(test_can):,}  "
        f"(canvass test base-rate {test_can[LABEL_COL].astype(float).mean():.3f})"
    )

    y_full = test_full[LABEL_COL].to_numpy()
    y_can = test_can[LABEL_COL].to_numpy()

    results: dict = {}
    for name, train_fn in (("logreg", _train_logreg), ("xgb", _train_xgb)):
        # full-trained scorer (LogReg ignores val; XGB early-stops on val_full)
        score_full = train_fn(train_full) if name == "logreg" else train_fn(train_full, val_full)
        # canvass-trained scorer (the reframe)
        score_can = train_fn(train_can) if name == "logreg" else train_fn(train_can, val_can)

        m_full = evaluate(y_full, score_full(test_full)).to_dict()
        s_full_on_can = score_full(test_can)
        m_full_on_can = evaluate(y_can, s_full_on_can).to_dict()
        s_routine = score_can(test_can)
        m_routine = evaluate(y_can, s_routine).to_dict()

        base_pr, base_p10 = m_full_on_can["pr_auc"], m_full_on_can["precision_at_10pct"]
        v36_pr, v36_p10 = V36_FULL_TEST[name]
        results[name] = {
            "full_baseline": m_full,
            "full_baseline_reproduces_v36": _gate(m_full, v36_pr - 1e-9, v36_p10 - 1e-9)
            or (
                abs(m_full["pr_auc"] - v36_pr) < 0.01
                and abs(m_full["precision_at_10pct"] - v36_p10) < 0.01
            ),
            "full_on_canvass": m_full_on_can,
            "routine_only": m_routine,
            "delta_routine_vs_full_on_canvass": {
                "pr_auc": round(m_routine["pr_auc"] - base_pr, 6),
                "precision_at_10pct": round(m_routine["precision_at_10pct"] - base_p10, 6),
            },
            "routine_clears_gate_vs_full_on_canvass": _gate(m_routine, base_pr, base_p10),
            "diagnostic_full_test": _top_decile_diag(test_full, score_full(test_full)),
            "diagnostic_routine_on_canvass": _top_decile_diag(test_can, s_routine),
        }
        r = results[name]
        print(
            f"\n[{name}]\n"
            f"  full_baseline   (full test n={m_full['n']:,})  "
            f"PR-AUC {m_full['pr_auc']:.4f}  P@10 {m_full['precision_at_10pct']:.4f}  "
            f"lift {m_full['top_decile_lift']:.2f}\n"
            f"  full_on_canvass (canv test n={m_full_on_can['n']:,})  "
            f"PR-AUC {base_pr:.4f}  P@10 {base_p10:.4f}  lift {m_full_on_can['top_decile_lift']:.2f}\n"
            f"  routine_only    (canv test n={m_routine['n']:,})  "
            f"PR-AUC {m_routine['pr_auc']:.4f} (Δ{r['delta_routine_vs_full_on_canvass']['pr_auc']:+.4f})  "
            f"P@10 {m_routine['precision_at_10pct']:.4f} "
            f"(Δ{r['delta_routine_vs_full_on_canvass']['precision_at_10pct']:+.4f})  "
            f"lift {m_routine['top_decile_lift']:.2f}  gate:{r['routine_clears_gate_vs_full_on_canvass']}\n"
            f"  top-decile was_fail: full-test {r['diagnostic_full_test']['top_decile_frac_was_fail']} "
            f"-> routine-on-canvass {r['diagnostic_routine_on_canvass']['top_decile_frac_was_fail']} "
            f"(overall canvass {r['diagnostic_routine_on_canvass']['overall_frac_was_fail']})"
        )

    # --- Fairness: LogReg, recall@10% by vulnerable group, full_on_canvass vs routine_only ---
    groups_can = test_can["facility_type"].map(normalize_facility_type)
    score_full_lr = _train_logreg(train_full)
    score_can_lr = _train_logreg(train_can)
    fair_base = group_performance_audit(y_can, score_full_lr(test_can), groups_can).set_index(
        "group"
    )
    fair_routine = group_performance_audit(y_can, score_can_lr(test_can), groups_can).set_index(
        "group"
    )
    fairness: dict = {}
    print("\nFairness — recall@10% by vulnerable group (LogReg, full_on_canvass -> routine_only):")
    for g in sorted(VULNERABLE_GROUPS):
        if g in fair_routine.index:
            rb = float(fair_base.loc[g, "recall_at_k"]) if g in fair_base.index else None
            rr = float(fair_routine.loc[g, "recall_at_k"])
            fairness[g] = {
                "n": int(fair_routine.loc[g, "n"]),
                "recall_full_on_canvass": rb,
                "recall_routine": rr,
            }
            print(f"  {g:32s} n={fairness[g]['n']:4d}  {rb} -> {rr}")

    out = {
        "experiment": "routine_only_target_reframe",
        "date": date.today().isoformat(),
        "config": {
            "routine_type": "Canvass (exact, case-insensitive)",
            "train_end": TRAIN_END,
            "val_end": VAL_END,
            "n_train_full": int(len(train_full)),
            "n_train_canvass": int(len(train_can)),
            "n_test_full": int(len(test_full)),
            "n_test_canvass": int(len(test_can)),
        },
        "v36_full_test_reference": V36_FULL_TEST,
        "gate_note": (
            "The reframe's gate is routine_only vs full_on_canvass (SAME canvass "
            "test set), NOT vs the v36 full-test numbers — removing re-inspection "
            "anchors lowers headline metrics by construction. A single-split pass "
            "is not final: confirm any win with expanding_year_folds CV."
        ),
        "results": results,
        "fairness_vulnerable_groups": fairness,
    }
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = METRICS_DIR / f"routine_only_experiment_{date.today().isoformat()}.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
