"""Spike (Phase-2, Layer-C structured NLP): do LLM hazard/severity labels add signal?

Controlled A/B: the v36 feature contract (control) vs v36 + the four LLM-extracted
violation labels (treatment): hazard type (categorical), severity 1-3 (numeric),
imminent-health-hazard and corrected-on-site (boolean), plus a has_violation_text
flag. Same chronological split, same training procedure per arm, both models — so
any metric delta is attributable to the labels.

Eval follows the both-metrics gate (decision 0002): a feature clears only if it
lifts BOTH PR-AUC and precision@10% on the honest test for the production LogReg,
with no vulnerable-population fairness regression. Even a flat PR-AUC leaves an
open question — are the labels good enough to improve the detail-page "what's
driving the signal" UI? — which the fairness/label-distribution print informs.

CIRCULARITY WATCH: llm_corrected_on_site / severity describe the current visit's
own outcome (leak-free, but can lean on the re-inspection dynamic like was_fail).

Inputs:
  - data/processed/features.parquet
  - data/interim/violation_labels_novalite.parquet (from build_violation_labels.py)

Run:
  PYTHONPATH=src uv run python scripts/run_violation_label_experiment.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from foodsafety.config import RANDOM_STATE
from foodsafety.features.license_features import normalize_facility_type
from foodsafety.features.violation_labels import (
    HAS_TEXT_COL,
    LABEL_COLS,
    add_violation_label_features,
)
from foodsafety.models.baseline import (
    BOOLEAN_FEATURES,
    CATEGORICAL_FEATURES,
    LABEL_COL,
    NUMERIC_FEATURES,
)
from foodsafety.models.evaluate import evaluate, group_performance_audit
from foodsafety.models.xgb import (
    build_xgb_estimator,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    prepare_xgb_features,
)
from foodsafety.utils.time import temporal_split

REPO_ROOT = Path(__file__).resolve().parent.parent
FEATURES_PATH = REPO_ROOT / "data" / "processed" / "features.parquet"
LABELS_PATH = REPO_ROOT / "data" / "interim" / "violation_labels_novalite.parquet"
METRICS_DIR = REPO_ROOT / "reports" / "metrics"

TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"

# Published v36 honest-test baseline (docs/model-experiments.md) — the gate reference.
V36_BASELINE = {"logreg": (0.332, 0.370), "xgb": (0.338, 0.376)}
VULNERABLE_GROUPS = {
    "Children's Services Facility",
    "Daycare",
    "School",
    "Long Term Care",
    "Hospital",
    "Shelter",
}

# How the LLM label columns map onto the model's three feature families.
EXTRA_NUMERIC = ["llm_severity", HAS_TEXT_COL]
EXTRA_CATEGORICAL = ["llm_hazard"]
EXTRA_BOOLEAN = ["llm_imminent_health_hazard", "llm_corrected_on_site"]


def _logreg_pipeline(extra_num, extra_cat, extra_bool) -> Pipeline:
    """Baseline LogReg pipeline; ``extra_*=[]`` reproduces the control exactly."""
    preprocess = ColumnTransformer(
        transformers=[
            (
                "num",
                Pipeline(
                    [("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]
                ),
                NUMERIC_FEATURES + extra_num,
            ),
            (
                "cat",
                OneHotEncoder(
                    handle_unknown="infrequent_if_exist", min_frequency=30, sparse_output=True
                ),
                CATEGORICAL_FEATURES + extra_cat,
            ),
            ("bool", "passthrough", BOOLEAN_FEATURES + extra_bool),
        ],
        sparse_threshold=0.5,
    )
    model = LogisticRegression(
        class_weight="balanced", solver="liblinear", max_iter=3000, random_state=RANDOM_STATE
    )
    return Pipeline([("preprocess", preprocess), ("model", model)])


def _fit_logreg(train, val, test, treat: bool):
    pipe = (
        _logreg_pipeline(EXTRA_NUMERIC, EXTRA_CATEGORICAL, EXTRA_BOOLEAN)
        if treat
        else _logreg_pipeline([], [], [])
    )
    pipe.fit(train, train[LABEL_COL])
    return pipe.predict_proba(test)[:, 1]


def _fit_xgb(train, val, test, treat: bool):
    Xtr = prepare_xgb_features(train)
    cat_dtypes = extract_categorical_dtypes(Xtr)
    Xva = prepare_xgb_features(val, categorical_dtypes=cat_dtypes)
    Xte = prepare_xgb_features(test, categorical_dtypes=cat_dtypes)
    if treat:
        # Pin the hazard categories from TRAIN so val/test codes line up (an unseen
        # level would otherwise get a different code); XGBoost reads them natively.
        hazard_cats = sorted(train["llm_hazard"].astype(str).unique())
        for frame, src in ((Xtr, train), (Xva, val), (Xte, test)):
            frame["llm_severity"] = src["llm_severity"].astype("float32").to_numpy()
            frame[HAS_TEXT_COL] = src[HAS_TEXT_COL].astype("int8").to_numpy()
            for c in EXTRA_BOOLEAN:
                frame[c] = src[c].astype("int8").to_numpy()
            frame["llm_hazard"] = pd.Categorical(
                src["llm_hazard"].astype(str), categories=hazard_cats
            )
    spw = compute_scale_pos_weight(train[LABEL_COL])
    clf = build_xgb_estimator(scale_pos_weight=spw)
    clf.fit(Xtr, train[LABEL_COL], eval_set=[(Xva, val[LABEL_COL])], verbose=False)
    return clf.predict_proba(Xte)[:, 1]


def _gate(m, base_pr, base_p10):
    return bool(m["pr_auc"] > base_pr and m["precision_at_10pct"] > base_p10)


def main() -> None:
    if not LABELS_PATH.exists():
        sys.exit(f"missing {LABELS_PATH} — run scripts/build_violation_labels.py first")

    df = pd.read_parquet(FEATURES_PATH)
    df["inspection_date"] = pd.to_datetime(df["inspection_date"])
    labels = pd.read_parquet(LABELS_PATH)
    df = add_violation_label_features(df, labels)
    print(
        f"rows: {len(df):,}  text-coverage: {df[HAS_TEXT_COL].mean():.1%}  "
        f"hazard coverage: {(df['llm_hazard'] != 'none').mean():.1%}"
    )
    print("hazard mix:", df.loc[df[HAS_TEXT_COL] == 1, "llm_hazard"].value_counts().to_dict())

    # Honest-test protocol: train/val drop right-truncated, score the FULL test.
    split = temporal_split(df, train_end=TRAIN_END, val_end=VAL_END)
    train = split.train[~split.train["right_truncated"]].copy()
    val = split.val[~split.val["right_truncated"]].copy()
    test = split.test.copy()
    print(f"train {len(train):,} / val {len(val):,} / test {len(test):,} (honest, full test)")

    y_test = test[LABEL_COL].to_numpy()
    results, scores = {}, {}
    for name, fit in (("logreg", _fit_logreg), ("xgb", _fit_xgb)):
        s_ctrl = fit(train, val, test, False)
        s_treat = fit(train, val, test, True)
        scores[name] = (s_ctrl, s_treat)
        ctrl = evaluate(y_test, s_ctrl).to_dict()
        treat = evaluate(y_test, s_treat).to_dict()
        base_pr, base_p10 = V36_BASELINE[name]
        results[name] = {
            "control": ctrl,
            "treatment": treat,
            "delta_pr_auc": round(treat["pr_auc"] - ctrl["pr_auc"], 6),
            "delta_precision_at_10pct": round(
                treat["precision_at_10pct"] - ctrl["precision_at_10pct"], 6
            ),
            "clears_gate_vs_control": _gate(treat, ctrl["pr_auc"], ctrl["precision_at_10pct"]),
            "clears_gate_vs_v36_published": _gate(treat, base_pr, base_p10),
        }
        print(
            f"\n[{name}] PR-AUC {ctrl['pr_auc']:.4f} -> {treat['pr_auc']:.4f} "
            f"(Δ{results[name]['delta_pr_auc']:+.4f}) | "
            f"P@10 {ctrl['precision_at_10pct']:.4f} -> {treat['precision_at_10pct']:.4f} "
            f"(Δ{results[name]['delta_precision_at_10pct']:+.4f}) | "
            f"gate-vs-control: {results[name]['clears_gate_vs_control']}"
        )

    # Fairness: production LogReg, recall@10% by vulnerable group (reuse fits).
    groups = test["facility_type"].map(normalize_facility_type)
    s_ctrl, s_treat = scores["logreg"]
    fair_ctrl = group_performance_audit(y_test, s_ctrl, groups).set_index("group")
    fair_treat = group_performance_audit(y_test, s_treat, groups).set_index("group")
    fairness = {}
    print("\nFairness — recall@10% by vulnerable group (LogReg, control -> treatment):")
    for g in sorted(VULNERABLE_GROUPS):
        if g in fair_treat.index:
            rc = float(fair_ctrl.loc[g, "recall_at_k"]) if g in fair_ctrl.index else None
            rt = float(fair_treat.loc[g, "recall_at_k"])
            fairness[g] = {"n": int(fair_treat.loc[g, "n"]), "recall_ctrl": rc, "recall_treat": rt}
            print(f"  {g:32s} n={fairness[g]['n']:4d}  {rc} -> {rt}")

    # Label-fairness: is the LLM assigning hazard TYPES differently across groups?
    # A skew can be legitimate (a daycare genuinely has different hazards than a
    # grocery) — but it's the check the handoff calls for, surfacing whether the
    # extractor encodes group-correlated bias rather than pure observed conduct.
    # We compare each vulnerable group's hazard mix to the overall mix on the
    # text-bearing test rows, and flag the largest share gap (in percentage points).
    print("\nLabel fairness — hazard-mix skew vs overall (text-bearing test rows):")
    text_test = test[test[HAS_TEXT_COL] == 1].copy()
    text_groups = text_test["facility_type"].map(normalize_facility_type)
    overall_mix = (
        text_test["llm_hazard"].astype(str).value_counts(normalize=True).round(4).to_dict()
    )
    hazard_skew = {"overall_mix": overall_mix, "by_group": {}}
    for g in sorted(VULNERABLE_GROUPS):
        sub = text_test[text_groups == g]
        if len(sub) < 50:  # same small-group noise floor as the recall audit
            continue
        mix = sub["llm_hazard"].astype(str).value_counts(normalize=True).to_dict()
        gaps = {h: round(mix.get(h, 0.0) - overall_mix.get(h, 0.0), 4) for h in overall_mix}
        top_hz = max(gaps, key=lambda h: abs(gaps[h]))
        hazard_skew["by_group"][g] = {
            "n": int(len(sub)),
            "mix": {h: round(v, 4) for h, v in mix.items()},
            "largest_gap_hazard": top_hz,
            "largest_gap_pp": round(gaps[top_hz] * 100, 1),
        }
        print(
            f"  {g:32s} n={len(sub):4d}  largest skew: {top_hz} "
            f"{hazard_skew['by_group'][g]['largest_gap_pp']:+.1f}pp vs overall"
        )

    out = {
        "experiment": "violation_label_layer_c_structured",
        "date": date.today().isoformat(),
        "config": {
            "model_id": "amazon.nova-lite-v1:0",
            "label_cols": list(LABEL_COLS),
            "train_end": TRAIN_END,
            "val_end": VAL_END,
            "n_test": int(len(test)),
            "test_text_coverage": round(float(test[HAS_TEXT_COL].mean()), 4),
        },
        "v36_published_baseline": V36_BASELINE,
        "results": results,
        "fairness_vulnerable_groups": fairness,
        "label_fairness_hazard_skew": hazard_skew,
    }
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = METRICS_DIR / f"violation_label_experiment_{date.today().isoformat()}.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
