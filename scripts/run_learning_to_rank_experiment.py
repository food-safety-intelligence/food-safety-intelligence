"""Learning-to-rank objective — optimize the top-K worklist directly.

The product is a capacity-limited triage worklist: an inspector works the top-K%
by risk. But every model so far trained a CLASSIFIER (log-loss / aucpr) and only
*measured* precision@10 after the fact. This spike asks the never-tested question:
does training XGBoost with a ranking objective (which optimizes ordering directly)
beat the log-loss classifier at the operating point we actually ship?

Tempered expectations (read the routine-only null first): the model is at an
INFORMATION ceiling — the top decile is ~97-99% `was_fail==1`. A ranking loss
reorders the SAME signal; it cannot manufacture risk signal beyond `was_fail`. So
the realistic outcome is flat, which would close the last free lever: "even
optimizing the shipped metric directly doesn't beat log-loss — the ceiling is
information." A genuine P@10 gain would only be a marginal re-ordering win and
would still need expanding_year_folds CV before anything ships.

EVAL-ONLY by design. A ranker emits ordering scores, not calibrated probabilities;
the served LogReg (which feeds the gauge / tiers / trend in scores.json) is NOT
touched. This script only measures whether the ranking objective wins the gate —
no UI / serve plumbing until a win is proven.

Arms (all XGBoost):
  * ``classifier``     — binary:logistic + scale_pos_weight (the v36 XGB baseline).
  * ``rank_pairwise``  — XGBRanker objective=rank:pairwise.
  * ``rank_ndcg``      — XGBRanker objective=rank:ndcg (LambdaMART).

Two setup details the ranker NEEDS (a naive "objective swap, same params" silently
trains a CONSTANT model that scores at the base rate):
  * ``min_child_weight`` must be LOWER for ranking. The classifier's default of 10
    is calibrated to the logistic Hessian (~p(1-p)≈0.25 per row); LambdaMART's
    per-row Hessians are far smaller, so min_child_weight=10 blocks every split and
    no trees grow. We use 1.0 for the ranker.
  * Ranking needs MULTIPLE query groups. One giant group (rank the whole pool at
    once) is degenerate — the pair sampler early-stops at iteration ~1. We bucket
    the rows into contiguous groups of ``GROUP_SIZE`` (a global ranking expressed
    as many local ranking problems, the standard LTR practice for a single feed).
PR-AUC / precision@k are invariant to monotone score scaling, so the ranker's raw
scores are min-max scaled to [0,1] only so the shared eval bundle runs; brier /
log_loss are meaningless for the ranker arms and are ignored.

Eval discipline: chronological split (train < 2024-07 / val < 2025-07 / test >=
2025-07), honest protocol (train/val drop right_truncated; score the full test),
both-metrics gate vs the in-run classifier control AND the published v36 XGB.

Run:
  FOODSAFETY_DATA_DIR=/abs/path/to/data PYTHONPATH=src \
    uv run python scripts/run_learning_to_rank_experiment.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBRanker

from foodsafety.config import PROCESSED_DIR, RANDOM_STATE
from foodsafety.features.license_features import normalize_facility_type
from foodsafety.models.baseline import LABEL_COL
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

# Published v36 honest-test (full test n=13,812) XGB baseline (docs/experiments.md).
V36_XGB = (0.338, 0.376)
VULNERABLE_GROUPS = {
    "Children's Services Facility",
    "Daycare",
    "School",
    "Long Term Care",
    "Hospital",
    "Shelter",
}

# Rows per query group — the ranker is given many local ranking problems rather
# than one degenerate global group (see the module docstring).
GROUP_SIZE = 256

# Ranker hyperparameters match build_xgb_estimator EXCEPT min_child_weight (1.0 vs
# the classifier's 10.0): LambdaMART's per-row Hessians are far smaller than the
# logistic Hessian, so the classifier's regularization scale blocks every split.
# scale_pos_weight does not apply to a ranking loss (the pair structure handles
# imbalance). Objective is set per arm below.
_RANKER_PARAMS = dict(
    n_estimators=800,
    max_depth=6,
    learning_rate=0.05,
    subsample=0.85,
    colsample_bytree=0.85,
    min_child_weight=1.0,
    reg_lambda=1.0,
    tree_method="hist",
    enable_categorical=True,
    random_state=RANDOM_STATE,
    n_jobs=-1,
    early_stopping_rounds=40,
    eval_metric="aucpr",  # stable early-stop signal across both rank objectives
    verbosity=0,
)


def _qid(n: int, size: int = GROUP_SIZE) -> np.ndarray:
    """Contiguous query-group ids of ~``size`` rows each (sorted, as XGBoost needs)."""
    return np.repeat(np.arange((n + size - 1) // size), size)[:n].astype(np.int32)


def _unit(s: np.ndarray) -> np.ndarray:
    """Min-max to [0,1]. PR-AUC / precision@k are monotone-invariant, so this does
    not change the ranking metrics; it only lets the shared eval bundle (which
    computes brier/log_loss) run on ranker scores without erroring."""
    s = np.asarray(s, dtype=float)
    lo, hi = float(s.min()), float(s.max())
    return (s - lo) / (hi - lo) if hi > lo else np.zeros_like(s)


def _score_classifier(train, val, test):
    Xtr = prepare_xgb_features(train)
    cat = extract_categorical_dtypes(Xtr)
    Xva = prepare_xgb_features(val, categorical_dtypes=cat)
    Xte = prepare_xgb_features(test, categorical_dtypes=cat)
    clf = build_xgb_estimator(scale_pos_weight=compute_scale_pos_weight(train[LABEL_COL]))
    clf.fit(Xtr, train[LABEL_COL], eval_set=[(Xva, val[LABEL_COL])], verbose=False)
    return clf.predict_proba(Xte)[:, 1]


def _score_ranker(train, val, test, objective):
    Xtr = prepare_xgb_features(train)
    cat = extract_categorical_dtypes(Xtr)
    Xva = prepare_xgb_features(val, categorical_dtypes=cat)
    Xte = prepare_xgb_features(test, categorical_dtypes=cat)
    # Many local ranking problems (groups of GROUP_SIZE) — a single global group
    # is degenerate and trains a constant model. See the module docstring.
    qid_tr = _qid(len(Xtr))
    qid_va = _qid(len(Xva))
    rk = XGBRanker(objective=objective, **_RANKER_PARAMS)
    rk.fit(
        Xtr,
        train[LABEL_COL].astype(int),
        qid=qid_tr,
        eval_set=[(Xva, val[LABEL_COL].astype(int))],
        eval_qid=[qid_va],
        verbose=False,
    )
    return rk.predict(Xte)


def _gate(m, base_pr, base_p10):
    return bool(m["pr_auc"] > base_pr and m["precision_at_10pct"] > base_p10)


def main() -> None:
    df = pd.read_parquet(FEATURES_PATH)
    df["inspection_date"] = pd.to_datetime(df["inspection_date"])
    split = temporal_split(df, train_end=TRAIN_END, val_end=VAL_END)
    train = split.train[~split.train["right_truncated"]].copy()
    val = split.val[~split.val["right_truncated"]].copy()
    test = split.test.copy()
    y = test[LABEL_COL].to_numpy()
    print(
        f"train {len(train):,} / val {len(val):,} / test {len(test):,}  test base-rate {y.mean():.3f}"
    )

    s_clf = _score_classifier(train, val, test)
    scores = {
        "classifier": s_clf,
        "rank_pairwise": _unit(_score_ranker(train, val, test, "rank:pairwise")),
        "rank_ndcg": _unit(_score_ranker(train, val, test, "rank:ndcg")),
    }

    m_ctrl = evaluate(y, scores["classifier"]).to_dict()
    base_pr, base_p10 = m_ctrl["pr_auc"], m_ctrl["precision_at_10pct"]
    v36_pr, v36_p10 = V36_XGB
    results = {"classifier": m_ctrl}
    print(
        f"\n[classifier control] PR-AUC {base_pr:.4f}  P@10 {base_p10:.4f}  "
        f"P@5 {m_ctrl['precision_at_5pct']:.4f}  P@20 {m_ctrl['precision_at_20pct']:.4f}  "
        f"lift {m_ctrl['top_decile_lift']:.2f}  (v36 ref {v36_pr}/{v36_p10})"
    )
    for arm in ("rank_pairwise", "rank_ndcg"):
        m = evaluate(y, scores[arm]).to_dict()
        results[arm] = {
            **m,
            "delta_vs_classifier": {
                "pr_auc": round(m["pr_auc"] - base_pr, 6),
                "precision_at_10pct": round(m["precision_at_10pct"] - base_p10, 6),
            },
            "clears_gate_vs_classifier": _gate(m, base_pr, base_p10),
            "clears_gate_vs_v36": _gate(m, v36_pr, v36_p10),
        }
        d = results[arm]["delta_vs_classifier"]
        print(
            f"[{arm:13s}] PR-AUC {m['pr_auc']:.4f} (Δ{d['pr_auc']:+.4f})  "
            f"P@10 {m['precision_at_10pct']:.4f} (Δ{d['precision_at_10pct']:+.4f})  "
            f"P@5 {m['precision_at_5pct']:.4f}  P@20 {m['precision_at_20pct']:.4f}  "
            f"lift {m['top_decile_lift']:.2f}  "
            f"gate vs ctrl:{results[arm]['clears_gate_vs_classifier']} "
            f"vs v36:{results[arm]['clears_gate_vs_v36']}"
        )

    # --- Fairness: best ranker arm vs the classifier, recall@10% by vulnerable group ---
    best = max(("rank_pairwise", "rank_ndcg"), key=lambda a: results[a]["precision_at_10pct"])
    groups = test["facility_type"].map(normalize_facility_type)
    fair_ctrl = group_performance_audit(y, scores["classifier"], groups).set_index("group")
    fair_best = group_performance_audit(y, scores[best], groups).set_index("group")
    fairness = {}
    print(f"\nFairness — recall@10% by vulnerable group (classifier -> {best}):")
    for g in sorted(VULNERABLE_GROUPS):
        if g in fair_best.index:
            rc = float(fair_ctrl.loc[g, "recall_at_k"]) if g in fair_ctrl.index else None
            rb = float(fair_best.loc[g, "recall_at_k"])
            fairness[g] = {"n": int(fair_best.loc[g, "n"]), "recall_ctrl": rc, "recall_best": rb}
            print(f"  {g:32s} n={fairness[g]['n']:4d}  {rc} -> {rb}")

    out = {
        "experiment": "learning_to_rank_objective",
        "date": date.today().isoformat(),
        "config": {
            "train_end": TRAIN_END,
            "val_end": VAL_END,
            "n_test": int(len(test)),
            "objectives": ["binary:logistic", "rank:pairwise", "rank:ndcg"],
            "query_group_size": GROUP_SIZE,
            "ranker_min_child_weight": 1.0,
            "ranker_params_note": "matches build_xgb_estimator except min_child_weight (1.0 vs 10.0, ranking Hessian scale)",
        },
        "v36_xgb_reference": {"pr_auc": v36_pr, "precision_at_10pct": v36_p10},
        "note": (
            "Eval-only. Ranker scores min-max scaled for the shared bundle; brier/"
            "log_loss are meaningless for the rank arms. A win needs expanding_year_"
            "folds CV before any serve/UI change; served LogReg untouched."
        ),
        "results": results,
        "fairness_vulnerable_groups": fairness,
    }
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = METRICS_DIR / f"learning_to_rank_experiment_{date.today().isoformat()}.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
