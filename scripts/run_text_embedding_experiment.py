"""Spike (Phase-2, Layer-C dense NLP): do violation-text embeddings add signal?

Controlled A/B: the v36 feature contract (control) vs v36 + violation-text
sentence-embeddings reduced to a handful of PCA components (treatment). Same
chronological split, same training procedure per arm, both models. The only
thing that changes between arms is the feature set — so any metric delta is
attributable to the embeddings.

Eval follows the project's both-metrics gate (decision 0002): a feature only
"clears" if it lifts BOTH PR-AUC and precision@10% on the honest (un-truncated)
test, for the production LogReg estimator, without a fairness regression on the
vulnerable-population groups.

Inputs:
  - data/processed/features.parquet              (v36 features + violations text)
  - data/interim/text_embeddings_titanv2.parquet (from build_text_embeddings.py)

Run:
  PYTHONPATH=src uv run python scripts/run_text_embedding_experiment.py

Writes reports/metrics/experiments/text_embedding_experiment_<date>.json. No model artifact,
no contract change — wiring into ALL_FEATURES only happens if this clears.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from foodsafety.config import RANDOM_STATE
from foodsafety.features.license_features import normalize_facility_type
from foodsafety.features.text_features import (
    HAS_TEXT_COL,
    add_text_embedding_features,
    embedding_columns,
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
EMB_PATH = REPO_ROOT / "data" / "interim" / "text_embeddings_titanv2.parquet"
METRICS_DIR = REPO_ROOT / "reports" / "metrics"

TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"
N_PCA = 32  # reduce the 256-dim Titan embeddings to 32 comps, fit on TRAIN only

# Published v36 honest-test baseline (docs/model-experiments.md) — the gate reference.
V36_BASELINE = {"logreg": (0.332, 0.370), "xgb": (0.338, 0.376)}
# Vulnerable-population facility families the fairness gate watches (decision 0004/0005).
VULNERABLE_GROUPS = {
    "Children's Services Facility",
    "Daycare",
    "School",
    "Long Term Care",
    "Hospital",
    "Shelter",
}


def _logreg_pipeline(extra_numeric: list[str]) -> Pipeline:
    """Baseline LogReg pipeline, optionally with extra numeric columns appended.

    Mirrors ``build_baseline_pipeline`` exactly; ``extra_numeric=[]`` reproduces
    the control so both A/B arms run the identical procedure (isolating features).
    """
    numeric = NUMERIC_FEATURES + extra_numeric
    preprocess = ColumnTransformer(
        transformers=[
            (
                "num",
                Pipeline(
                    [("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())]
                ),
                numeric,
            ),
            (
                "cat",
                OneHotEncoder(
                    handle_unknown="infrequent_if_exist", min_frequency=30, sparse_output=True
                ),
                CATEGORICAL_FEATURES,
            ),
            ("bool", "passthrough", BOOLEAN_FEATURES),
        ],
        sparse_threshold=0.5,
    )
    model = LogisticRegression(
        class_weight="balanced", solver="liblinear", max_iter=3000, random_state=RANDOM_STATE
    )
    return Pipeline([("preprocess", preprocess), ("model", model)])


def _fit_logreg(train, val, test, extra_numeric):
    # val is unused for LogReg (no early stopping / calibration here — PR-AUC and
    # precision@k are rank metrics, invariant to the monotonic sigmoid calibrator).
    pipe = _logreg_pipeline(extra_numeric)
    pipe.fit(train, train[LABEL_COL])
    return pipe.predict_proba(test)[:, 1]


def _fit_xgb(train, val, test, extra_cols):
    Xtr = prepare_xgb_features(train)
    cat_dtypes = extract_categorical_dtypes(Xtr)
    Xva = prepare_xgb_features(val, categorical_dtypes=cat_dtypes)
    Xte = prepare_xgb_features(test, categorical_dtypes=cat_dtypes)
    if extra_cols:
        for frame, src in ((Xtr, train), (Xva, val), (Xte, test)):
            for c in extra_cols:
                frame[c] = src[c].astype("float32").to_numpy()
    spw = compute_scale_pos_weight(train[LABEL_COL])
    clf = build_xgb_estimator(scale_pos_weight=spw)
    clf.fit(Xtr, train[LABEL_COL], eval_set=[(Xva, val[LABEL_COL])], verbose=False)
    return clf.predict_proba(Xte)[:, 1]


def _gate(arm_metrics, base_pr, base_p10):
    return bool(arm_metrics["pr_auc"] > base_pr and arm_metrics["precision_at_10pct"] > base_p10)


def main() -> None:
    if not EMB_PATH.exists():
        sys.exit(f"missing {EMB_PATH} — run scripts/build_text_embeddings.py first")

    df = pd.read_parquet(FEATURES_PATH)
    df["inspection_date"] = pd.to_datetime(df["inspection_date"])

    emb = pd.read_parquet(EMB_PATH)
    emb_raw_cols = embedding_columns(emb)
    df = add_text_embedding_features(df, emb)
    print(
        f"rows: {len(df):,}  text-coverage: {df[HAS_TEXT_COL].mean():.1%}  emb dims: {len(emb_raw_cols)}"
    )

    # Honest-test protocol (matches the published v36 baseline, n≈13,812): train
    # and validate on rows whose forward 180-day window is fully observed (drop
    # right-truncated — their under-counted labels bias the fit), but SCORE on the
    # FULL test slice (truncated rows kept). The trainer does exactly this.
    split = temporal_split(df, train_end=TRAIN_END, val_end=VAL_END)
    train = split.train[~split.train["right_truncated"]].copy()
    val = split.val[~split.val["right_truncated"]].copy()
    test = split.test.copy()
    print(f"train {len(train):,} / val {len(val):,} / test {len(test):,} (honest, full test)")

    # PCA on the raw embeddings — FIT ON TRAIN ONLY, then transform every split.
    # Fitting on all rows would leak test-period text covariance into the reducer.
    pca = PCA(n_components=N_PCA, random_state=RANDOM_STATE)
    pca.fit(train[emb_raw_cols].to_numpy())
    pca_cols = [f"emb_pca_{i:02d}" for i in range(N_PCA)]
    for frame in (train, val, test):
        comps = pca.transform(frame[emb_raw_cols].to_numpy())
        frame[pca_cols] = comps
    treat_extra = pca_cols + [HAS_TEXT_COL]
    print(f"PCA({N_PCA}) explained variance: {pca.explained_variance_ratio_.sum():.1%}")

    y_test = test[LABEL_COL].to_numpy()
    results = {}
    scores = {}  # (model -> (control_scores, treatment_scores)); reused for the fairness audit
    for name, fit in (("logreg", _fit_logreg), ("xgb", _fit_xgb)):
        s_ctrl = fit(train, val, test, [])
        s_treat = fit(train, val, test, treat_extra)
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

    # Fairness: production LogReg, recall@10% by vulnerable group. Reuse the
    # LogReg scores already fit above (no re-train).
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

    out = {
        "experiment": "text_embedding_layer_c_dense",
        "date": date.today().isoformat(),
        "config": {
            "model_id": "amazon.titan-embed-text-v2:0",
            "embed_dim": len(emb_raw_cols),
            "n_pca": N_PCA,
            "pca_explained_variance": round(float(pca.explained_variance_ratio_.sum()), 4),
            "train_end": TRAIN_END,
            "val_end": VAL_END,
            "n_test": int(len(test)),
            "test_text_coverage": round(float(test[HAS_TEXT_COL].mean()), 4),
        },
        "v36_published_baseline": V36_BASELINE,
        "results": results,
        "fairness_vulnerable_groups": fairness,
    }
    experiments_dir = METRICS_DIR / "experiments"
    experiments_dir.mkdir(parents=True, exist_ok=True)
    out_path = experiments_dir / f"text_embedding_experiment_{date.today().isoformat()}.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
