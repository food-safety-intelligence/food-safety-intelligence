"""Leave-one-out feature importance for each city's served RISK model (Model 1).

Refit the served config dropping one feature at a time and measure the PR-AUC it
loses on the held-out test (positive delta = the feature is important). This is
the ablation behind figure 13 in notebooks/09_cross_city_eda.ipynb.

Each city reuses its own production fit — Chicago via ``build_production_xgb``
(depth-3 monotone), NYC/LA via their ``build_{nyc,la}_scores.fit_xgb_platt`` — so
the numbers describe the model that actually ships. PR-AUC is a rank metric, so
the (rank-irrelevant) Platt step is skipped and the raw margin is scored.

Caveats: single-split diagnostic (like the 2026-06-21 leave-one-out in
docs/model-experiments.md); leave-one-out *understates* correlated features (two
redundant columns mask each other, so a small drop does not mean unimportant).

Run:  PYTHONPATH=src FOODSAFETY_DATA_DIR=<data> python scripts/run_leave_one_out.py
Writes reports/metrics/leave_one_out_risk.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from sklearn.metrics import average_precision_score

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import run_city_feature_experiments as fx  # noqa: E402  (load_city for nyc/la)

from foodsafety.config import FEATURES_PATH  # noqa: E402
from foodsafety.models.baseline import ALL_FEATURES, LABEL_COL  # noqa: E402
from foodsafety.models.xgb import (  # noqa: E402
    build_production_xgb,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    prepare_xgb_features,
)
from foodsafety.utils.time import temporal_split  # noqa: E402

TRAIN_END, VAL_END = "2024-07-01", "2025-07-01"


def _leave_one_out(pr_fn, feats: list[str]) -> dict:
    base = pr_fn(feats)
    deltas = {f: round(base - pr_fn([x for x in feats if x != f]), 4) for f in feats}
    return {"baseline_pr_auc": round(base, 4), "deltas": deltas}


def chicago() -> dict:
    feat = pd.read_parquet(FEATURES_PATH)
    feat = feat.loc[~feat["right_truncated"]].reset_index(drop=True)
    sp = temporal_split(feat, train_end=TRAIN_END, val_end=VAL_END)
    ytr = sp.train[LABEL_COL].astype(int).to_numpy()
    yte = sp.test[LABEL_COL].astype(int).to_numpy()
    spw = compute_scale_pos_weight(ytr)
    xtr = prepare_xgb_features(sp.train[ALL_FEATURES])
    cat = extract_categorical_dtypes(xtr)
    xte = prepare_xgb_features(sp.test[ALL_FEATURES], categorical_dtypes=cat)

    def pr(feats):
        est = build_production_xgb(scale_pos_weight=spw, features=list(feats))
        est.set_params(n_jobs=3)
        est.fit(xtr[list(feats)], ytr, verbose=False)
        return float(
            average_precision_score(yte, est.predict(xte[list(feats)], output_margin=True))
        )

    out = _leave_one_out(pr, list(ALL_FEATURES))
    out["n_test"] = int(len(yte))
    return out


def preview_city(city: str) -> dict:
    c = fx.load_city(city)
    ev, label = c["ev"], c["label"]
    feats = list(c["PRIOR"]) + list(c["CURRENT"])
    anch = ev[ev["next_score"].notna() & (ev["inspection_date"] >= c["train_start"])].copy()
    sp = temporal_split(
        anch, date_col="inspection_date", train_end=c["train_end"], val_end=c["val_end"]
    )
    yte = sp.test[label].astype(int).to_numpy()

    def pr(fs):
        clf, _, _ = c["fit"](sp.train, sp.val, list(fs), label=label)  # Platt is rank-irrelevant
        return float(
            average_precision_score(yte, clf.predict(sp.test[list(fs)], output_margin=True))
        )

    out = _leave_one_out(pr, feats)
    out["n_test"] = int(len(yte))
    return out


def main() -> None:
    result = {}
    for name, fn in [
        ("chicago", chicago),
        ("nyc", lambda: preview_city("nyc")),
        ("la", lambda: preview_city("la")),
    ]:
        print(f"[{name}] leave-one-out...", flush=True)
        result[name] = fn()
        top = sorted(result[name]["deltas"].items(), key=lambda kv: -kv[1])[:5]
        print(f"[{name}] base={result[name]['baseline_pr_auc']}  top: {top}", flush=True)
    out = REPO / "reports" / "metrics" / "leave_one_out_risk.json"
    out.write_text(json.dumps(result, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
