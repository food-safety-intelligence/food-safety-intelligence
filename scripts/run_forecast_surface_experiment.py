"""Forecast surface — risk WITHOUT the current inspection's own outcome.

The v36 model's top decile is ~97-99% `was_fail==1`: it is dominated by places
whose most recent inspection just failed (a mandated re-inspection then lands in
the label window). That is a strong "current-state" risk score, but it mostly
*confirms known-bad places* — a clean place that is quietly becoming risky never
reaches the worklist.

This spike measures a complementary FORECAST model: drop the three current-outcome
features (`was_fail`, `n_priority_this_inspection`, `n_core_this_inspection`) and
predict risk from history / context only — i.e. before today's verdict is known.
Its raw accuracy is lower, but it answers a question the main model cannot:
"which place we have NOT just caught failing is rising in risk?"

The headline isn't PR-AUC (the forecast model will lose on that by construction).
It is the EARLY-WARNING analysis:
  * the main worklist (top decile) is almost all recent failers, so CLEAN places
    (was_fail==0) get ~no attention;
  * on the clean slice, does the forecast model rank real risk — i.e. is its
    top-decile fail-rate among clean places lifted over the clean base rate?
  * how many clean places does the forecast surface that the main worklist misses,
    and do they actually fail?

XGBoost for both arms (the production estimator is LogReg, but its pipeline hard-
codes the feature list; XGB is the clean instrument for a drop-features spike and
the conclusion transfers — the never-failed-rows gap was XGB-measured too). Honest
split: train < 2024-07 / val < 2025-07 / test >= 2025-07; train/val drop
right_truncated; score the full test.

Run:
  FOODSAFETY_DATA_DIR=/abs/path/to/data PYTHONPATH=src \
    uv run python scripts/run_forecast_surface_experiment.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from foodsafety.config import PROCESSED_DIR
from foodsafety.models.baseline import LABEL_COL
from foodsafety.models.evaluate import evaluate, precision_at_k, top_decile_lift
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

# The current inspection's own outcome — the features that make the main model a
# "current-state" score rather than a forecast. Dropping them is the whole spike.
CURRENT_OUTCOME = ["was_fail", "n_priority_this_inspection", "n_core_this_inspection"]


def _train_score(train, val, test, drop):
    Xtr = prepare_xgb_features(train)
    cat = extract_categorical_dtypes(Xtr)  # categoricals unaffected (drops are numeric)
    Xva = prepare_xgb_features(val, categorical_dtypes=cat)
    Xte = prepare_xgb_features(test, categorical_dtypes=cat)
    if drop:
        Xtr, Xva, Xte = (X.drop(columns=drop) for X in (Xtr, Xva, Xte))
    clf = build_xgb_estimator(scale_pos_weight=compute_scale_pos_weight(train[LABEL_COL]))
    clf.fit(Xtr, train[LABEL_COL], eval_set=[(Xva, val[LABEL_COL])], verbose=False)
    return clf.predict_proba(Xte)[:, 1]


def _topk_idx(scores, k_frac=0.10):
    k = max(1, int(np.ceil(len(scores) * k_frac)))
    return set(np.argsort(-scores, kind="stable")[:k].tolist())


def main() -> None:
    df = pd.read_parquet(FEATURES_PATH)
    df["inspection_date"] = pd.to_datetime(df["inspection_date"])
    split = temporal_split(df, train_end=TRAIN_END, val_end=VAL_END)
    train = split.train[~split.train["right_truncated"]].copy()
    val = split.val[~split.val["right_truncated"]].copy()
    test = split.test.reset_index(drop=True).copy()
    y = test[LABEL_COL].to_numpy().astype(int)
    was_fail = test["was_fail"].to_numpy().astype(bool)
    base = float(y.mean())
    print(
        f"train {len(train):,} / val {len(val):,} / test {len(test):,}  "
        f"base-rate {base:.3f}  clean(was_fail==0) {int((~was_fail).sum()):,} "
        f"({(~was_fail).mean():.1%})"
    )

    s_main = _train_score(train, val, test, drop=[])
    s_fore = _train_score(train, val, test, drop=CURRENT_OUTCOME)

    # --- overall metrics + how recent-failer-dominated each top decile is ---
    def _summ(s):
        m = evaluate(y, s).to_dict()
        top = _topk_idx(s)
        m["top_decile_frac_was_fail"] = round(float(was_fail[list(top)].mean()), 4)
        m["top_decile_n_clean"] = int((~was_fail[list(top)]).sum())
        return m

    m_main, m_fore = _summ(s_main), _summ(s_fore)
    print(
        f"\n[main  ] PR-AUC {m_main['pr_auc']:.4f}  P@10 {m_main['precision_at_10pct']:.4f}  "
        f"lift {m_main['top_decile_lift']:.2f}  top-decile was_fail {m_main['top_decile_frac_was_fail']}  "
        f"clean-in-top {m_main['top_decile_n_clean']}"
    )
    print(
        f"[forecast] PR-AUC {m_fore['pr_auc']:.4f}  P@10 {m_fore['precision_at_10pct']:.4f}  "
        f"lift {m_fore['top_decile_lift']:.2f}  top-decile was_fail {m_fore['top_decile_frac_was_fail']}  "
        f"clean-in-top {m_fore['top_decile_n_clean']}"
    )

    # --- the early-warning case: ranking on the CLEAN slice (was_fail==0) ---
    clean = ~was_fail
    y_clean = y[clean]
    clean_base = float(y_clean.mean())
    clean_eval = {
        "n": int(clean.sum()),
        "base_rate": round(clean_base, 4),
        "main": {
            "pr_auc": round(float(evaluate(y_clean, s_main[clean]).pr_auc), 4),
            "precision_at_10pct": round(precision_at_k(y_clean, s_main[clean], 0.10), 4),
            "top_decile_lift": round(top_decile_lift(y_clean, s_main[clean]), 3),
        },
        "forecast": {
            "pr_auc": round(float(evaluate(y_clean, s_fore[clean]).pr_auc), 4),
            "precision_at_10pct": round(precision_at_k(y_clean, s_fore[clean], 0.10), 4),
            "top_decile_lift": round(top_decile_lift(y_clean, s_fore[clean]), 3),
        },
    }
    print(
        f"\nCLEAN slice (was_fail==0, n={clean_eval['n']:,}, base {clean_base:.3f}) — "
        "can the forecast rank rising risk among clean places?"
    )
    print(
        f"  main      P@10 {clean_eval['main']['precision_at_10pct']:.4f}  "
        f"lift {clean_eval['main']['top_decile_lift']:.2f}"
    )
    print(
        f"  forecast  P@10 {clean_eval['forecast']['precision_at_10pct']:.4f}  "
        f"lift {clean_eval['forecast']['top_decile_lift']:.2f}"
    )

    # --- clean places the FORECAST surfaces that the MAIN worklist misses ---
    top_main, top_fore = _topk_idx(s_main), _topk_idx(s_fore)
    newly = np.array(sorted(top_fore - top_main))
    newly_clean = newly[clean[newly]] if len(newly) else newly
    surfaced = {
        "forecast_topdecile_n": len(top_fore),
        "newly_vs_main": int(len(newly)),
        "newly_and_clean": int(len(newly_clean)),
        "newly_clean_fail_rate": round(float(y[newly_clean].mean()), 4)
        if len(newly_clean)
        else None,
        "newly_clean_lift_vs_base": round(float(y[newly_clean].mean() / base), 2)
        if len(newly_clean)
        else None,
    }
    print(
        f"\nForecast surfaces {surfaced['newly_and_clean']} CLEAN places in its top decile "
        f"that the main worklist misses — their actual fail-rate "
        f"{surfaced['newly_clean_fail_rate']} (lift {surfaced['newly_clean_lift_vs_base']}× vs base {base:.3f})."
    )

    # --- a few concrete examples (enrich with dba_name/address if available) ---
    examples = []
    if len(newly_clean):
        order = newly_clean[np.argsort(-s_fore[newly_clean], kind="stable")]
        hits = [i for i in order if y[i] == 1][:8]
        cols = [c for c in ("license_id", "dba_name", "address") if c in test.columns]
        if "dba_name" not in test.columns:
            insp = pd.read_parquet(INSPECTIONS_PATH)
            namecols = [
                c
                for c in ("license_id", "inspection_date", "dba_name", "address")
                if c in insp.columns
            ]
            if "dba_name" in namecols:
                test_named = test.merge(
                    insp[namecols].drop_duplicates(["license_id", "inspection_date"]),
                    on=["license_id", "inspection_date"],
                    how="left",
                )
                cols = [c for c in ("license_id", "dba_name", "address") if c in test_named.columns]
                src = test_named
            else:
                src = test
        else:
            src = test
        for i in hits:
            examples.append({c: str(src.iloc[i][c]) for c in cols})
        print("\nExample clean places the forecast flagged that then FAILED:")
        for e in examples:
            print("  " + "  ".join(f"{k}={v}" for k, v in e.items()))

    out = {
        "experiment": "forecast_surface_drop_current_outcome",
        "date": date.today().isoformat(),
        "config": {
            "dropped_features": CURRENT_OUTCOME,
            "estimator": "xgboost (both arms)",
            "train_end": TRAIN_END,
            "val_end": VAL_END,
            "n_test": int(len(test)),
        },
        "overall": {"main": m_main, "forecast": m_fore},
        "clean_slice": clean_eval,
        "early_warning_surfaced": surfaced,
        "examples": examples,
    }
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = METRICS_DIR / f"forecast_surface_experiment_{date.today().isoformat()}.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
