"""Feature-family + model-class ablations for all three cities' served models.

The cities shipped without a comparable, tracked ablation record. This runner
closes that gap so Chicago, NYC, and LA sit in one parallel frame. Each city
reuses its OWN production code (so numbers match the served model), holds the
served temporal split fixed, and evaluates every variant on the same held-out
test set. Each variant is written as its own tracked run under
`reports/metrics/<city>/<city>_<variant>_<run_id>.json`. Fits + evaluates only —
never touches committed app JSON.

The cities do NOT share a pipeline, label, or feature taxonomy, so the frames are
parallel by analogy, not identical numbers (a caveat repeated in the doc):

NYC / LA (event-anchored "next inspection graded B/C", built inline from a raw
SODA/ArcGIS snapshot via each city's `build_events` + `fit_xgb_platt`):
  - served_xgb_full   XGB on PRIOR + CURRENT (the production feature set)
  - xgb_prior_only    XGB on prior-history features only (no current inspection)
  - xgb_current_only  XGB on current-inspection features only
  - xgb_no_theme_sev  XGB minus the crosswalk theme + severity-tier columns
                      (cur_theme_*, cur_sev_T*, prior_* rollups) — derived from
                      the violation CODE via reference/violation_crosswalk.csv
  - xgb_plus_keywords XGB + Chicago's 12 Layer-B keyword flags (regex on the
                      violation free text) — NYC/LA don't ship this
  - logreg_full       LogReg + sigmoid (model-class comparator)

Chicago (forward-180d fail-or-critical, from features.parquet via its depth-3
monotone production XGB + the LogReg baseline). Analogous variants:
  - served_xgb_full            ALL_FEATURES (production XGB)
  - xgb_forecast_only          FORECAST_FEATURES; ≈ prior_only
  - xgb_current_outcome_only   CURRENT_OUTCOME_FEATURES; ≈ current_only
  - xgb_no_keywords            ALL minus the 12 flag_kw_*; ≈ no_theme_sev, and
                               measures the keyword flags' value IN Chicago
  - logreg_full                the served LogReg baseline + sigmoid

Run:  PYTHONPATH=src .venv/bin/python scripts/run_city_ablations.py [chicago|nyc|la|all]
NYC/LA read the cached raw pull under data/raw/ (pulled fresh if absent, like the
served build).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.frozen import FrozenEstimator
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score, recall_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from foodsafety.config import FEATURES_PATH, RANDOM_STATE
from foodsafety.explain.shap_drivers import tree_contributions
from foodsafety.features.keyword_flags import add_keyword_flags
from foodsafety.io import storage
from foodsafety.models.baseline import (
    ALL_FEATURES,
    CURRENT_OUTCOME_FEATURES,
    FORECAST_FEATURES,
    LABEL_COL,
    build_baseline_pipeline,
)
from foodsafety.models.evaluate import evaluate
from foodsafety.models.xgb import (
    build_production_xgb,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    prepare_xgb_features,
)
from foodsafety.tracking import provenance, snapshot_provenance
from foodsafety.utils.time import temporal_split

# Chicago's served temporal cutoffs (scripts/retrain_xgb_sigmoid.py).
CHI_TRAIN_END, CHI_VAL_END = "2024-07-01", "2025-07-01"

REPO = Path(__file__).resolve().parent.parent
# Import the city producers as modules so the ablations reuse the exact
# feature-build + fit code that ships to production (module import has no side
# effects; the raw pull only happens when build_events/build_raw are called).
sys.path.insert(0, str(REPO / "scripts"))
import build_la_scores as la  # noqa: E402
import build_nyc_scores as nyc  # noqa: E402

HEADLINE = ("pr_auc", "roc_auc", "precision_at_10pct", "top_decile_lift", "brier_score")


def threshold_metrics(y, p, thr: float = 0.5) -> dict:
    """Precision / recall / F1 at a fixed decision threshold on the calibrated
    probability. Complements the ranking metrics (pr@10, recall@10, lift) in
    evaluate(): those need no threshold; these are the 0.5-cutoff classification
    view. Under heavy imbalance (LA base 8.7%) a 0.5 cutoff is stringent, so
    recall runs low — read it alongside the @10% operating point, not instead.
    """
    yhat = (p >= thr).astype(int)
    return {
        "threshold": thr,
        "precision": round(float(precision_score(y, yhat, zero_division=0)), 6),
        "recall": round(float(recall_score(y, yhat, zero_division=0)), 6),
        "f1": round(float(f1_score(y, yhat, zero_division=0)), 6),
    }


def operating_points(y, p, fracs=(0.05, 0.10, 0.20)) -> list[dict]:
    """Ranking operating points — inspect the top `frac` riskiest and read
    precision / recall / lift there. This, not a 0.5 cutoff, is how a
    capacity-limited triage tool is actually used; `frac` = the worklist depth.
    Lift = precision / base rate (>1 means the top slice concentrates positives).
    """
    y = np.asarray(y)
    n, pos, base = len(y), max(int(y.sum()), 1), (float(y.mean()) or 1.0)
    order = np.argsort(-p)
    out = []
    for f in fracs:
        k = max(1, int(round(f * n)))
        top = y[order[:k]]
        prec = float(top.mean())
        out.append(
            {
                "frac": f,
                "k": k,
                "precision": round(prec, 6),
                "recall": round(float(top.sum()) / pos, 6),
                "lift": round(prec / base, 4),
            }
        )
    return out


def f1_optimal_threshold(y, p) -> dict:
    """The threshold that maximises F1 — a principled single cutoff for the
    classification-metric view, vs the arbitrary 0.5. Reported as a diagnostic
    (best the model can do as a hard classifier), not a served knob: the product
    uses ranked tiers, not a binary flag. Swept over the distinct rounded scores.
    """
    y = np.asarray(y)
    best = {"threshold": 0.5, "precision": 0.0, "recall": 0.0, "f1": -1.0}
    for t in np.unique(np.round(p, 3)):
        yhat = (p >= t).astype(int)
        f = f1_score(y, yhat, zero_division=0)
        if f > best["f1"]:
            best = {
                "threshold": round(float(t), 4),
                "precision": round(float(precision_score(y, yhat, zero_division=0)), 6),
                "recall": round(float(recall_score(y, yhat, zero_division=0)), 6),
                "f1": round(float(f), 6),
            }
    return best


def global_shap_importance(clf, x_df, feats: list[str], top: int = 15) -> list[dict]:
    """Global feature importance for a served XGB = mean |TreeSHAP| per feature
    over the test set (margin space), the same explainability the app's per-row
    driver waterfalls are built on. Ranked descending; top `top` returned.
    """
    contribs, _ = tree_contributions(clf, x_df, feats)
    imp = contribs.abs().mean().sort_values(ascending=False)
    total = float(imp.sum()) or 1.0
    return [
        {"feature": f, "mean_abs_shap": round(float(v), 6), "share": round(float(v) / total, 4)}
        for f, v in imp.head(top).items()
    ]


def fit_logreg_sigmoid(
    train: pd.DataFrame, val: pd.DataFrame, feats: list[str], label: str
) -> Pipeline:
    """Chicago-baseline-style comparator: median-impute + scale + balanced
    logistic, then sigmoid (Platt) calibration on val without refitting the base.

    XGBoost consumes NaNs natively; logistic regression can't, so the numeric
    prior_* features (NaN on an establishment's first inspection) are median-
    imputed. class_weight='balanced' mirrors the served baseline's imbalance
    handling (no SMOTE on time-split data).
    """
    pre = ColumnTransformer(
        [
            (
                "num",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler()),
                    ]
                ),
                feats,
            )
        ]
    )
    base = Pipeline(
        [
            ("pre", pre),
            (
                "model",
                LogisticRegression(
                    class_weight="balanced", max_iter=1000, random_state=RANDOM_STATE
                ),
            ),
        ]
    )
    base.fit(train[feats], train[label].astype(int))
    cal = CalibratedClassifierCV(FrozenEstimator(base), method="sigmoid")
    cal.fit(val[feats], val[label].astype(int))
    return cal


def event_keyword_flags(raw: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Chicago's Layer-B keyword flags, rolled up to one row per inspection event.

    Reuses `keyword_flags.add_keyword_flags` (the same 12 hand-picked hazard
    regexes served on Chicago) on each violation row's free text, then OR-reduces
    to the event grain (a flag fires if any violation at that inspection matched).
    Same observation basis as the cur_* current-inspection features (observed at
    the anchor date, label strictly after), so it's leak-free. Chicago's own
    caveat applies: the regexes are tuned to Chicago phrasing, so on NYC/LA this
    tests the transferred set, not a re-tuned one.
    """
    df = raw.rename(columns={"violation_description": "violations"})
    flagged = add_keyword_flags(df)
    kw_cols = list(flagged.filter(like="flag_kw_").columns)
    ev_flags = flagged.groupby(keys, dropna=False)[kw_cols].max().astype("int8")
    return ev_flags.reset_index()


def run_city(city: str) -> list[dict]:
    """Build events once, then fit + evaluate every variant on the fixed split."""
    if city == "nyc":
        ev, PRIOR, CURRENT, theme_cols, sev_cols, raw = nyc.build_events()
        label, base_rate = "y_next_bc", nyc.NYC_BASE_RATE
        train_start, train_end, val_end = nyc.NYC_TRAIN_START, nyc.TRAIN_END, nyc.VAL_END
        raw_paths, kw_keys = [nyc.RAW], ["camis", "inspection_date"]
        fit_xgb, xgb_proba = nyc.fit_xgb_platt, nyc.xgb_proba
    elif city == "la":
        raw = la.build_raw()
        ev, PRIOR, CURRENT, theme_cols, sev_cols = la.build_events(raw)
        label, base_rate = "y_next_bad", la.LA_BASE_RATE
        train_start, train_end, val_end = la.LA_TRAIN_START, la.TRAIN_END, la.VAL_END
        raw_paths, kw_keys = [la.RAW_INSP, la.RAW_VIOL], ["facility_id", "date"]
        fit_xgb, xgb_proba = la.fit_xgb_platt, la.xgb_proba
    else:
        raise ValueError(f"unknown city {city!r}")

    feats_full = PRIOR + CURRENT
    # The violation theme + severity-tier features (cur_theme_*, cur_sev_T*, and
    # their prior_* rollups) are mapped from the native violation CODE via
    # reference/violation_crosswalk.csv — structured categorization, not text
    # mining. Dropping all of them isolates their marginal value.
    theme_sev = set(theme_cols) | set(sev_cols) | {f"prior_{c}" for c in sev_cols}
    feats_no_theme_sev = [f for f in feats_full if f not in theme_sev]

    # Chicago's Layer-B keyword flags on the current inspection's violation text,
    # merged onto ev BEFORE the split so every fold carries them. Tests whether
    # regex-on-text adds signal on top of the served set — the thing NYC/LA don't
    # currently do. Left-join + fill 0 (an event with no matching violation text).
    kw = event_keyword_flags(raw, kw_keys)
    kw_cols = [c for c in kw.columns if c.startswith("flag_kw_")]
    ev = ev.merge(kw, on=kw_keys, how="left")
    ev[kw_cols] = ev[kw_cols].fillna(0).astype("int8")

    # Same anchoring + temporal split as the served build, so every variant is
    # scored on an identical held-out test set (comparability is the point).
    anch = ev[ev["next_score"].notna() & (ev["inspection_date"] >= train_start)].copy()
    sp = temporal_split(anch, date_col="inspection_date", train_end=train_end, val_end=val_end)
    y_test = sp.test[label].astype(int).to_numpy()
    print(
        f"\n[{city}] train {len(sp.train):,} | val {len(sp.val):,} | test {len(sp.test):,} "
        f"| test base {y_test.mean():.3f}"
    )

    variants = [
        ("served_xgb_full", "xgb", feats_full),
        ("xgb_prior_only", "xgb", PRIOR),
        ("xgb_current_only", "xgb", CURRENT),
        ("xgb_no_theme_sev", "xgb", feats_no_theme_sev),
        ("xgb_plus_keywords", "xgb", feats_full + kw_cols),
        ("logreg_full", "logreg", feats_full),
    ]

    prov = snapshot_provenance(raw_paths, feats_full, REPO)
    run_id = prov["run_id"]
    vintage = pd.Timestamp(ev["inspection_date"].max()).strftime("%Y%m%d")
    out_dir = REPO / "reports" / "metrics" / city
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for name, kind, feats in variants:
        importance = None
        if kind == "xgb":
            clf, coef, inter = fit_xgb(sp.train, sp.val, feats, label=label)
            p_test = xgb_proba(clf, coef, inter, sp.test[feats])
            # Global feature importance for the DEPLOYED model (served config).
            if name == "served_xgb_full":
                importance = global_shap_importance(clf, sp.test[feats], feats)
        else:
            cal = fit_logreg_sigmoid(sp.train, sp.val, feats, label)
            p_test = cal.predict_proba(sp.test[feats])[:, 1]
        metrics = evaluate(y_test, p_test).to_dict()

        report = {
            "model": f"{city}_{name}",
            "city": city,
            "variant": name,
            "estimator": kind,
            "calibration": "sigmoid (platt)",
            "label": label,
            "n_features": len(feats),
            "data_vintage": vintage,
            **prov,
            "train_window": {
                "train_start": train_start,
                "train_end": train_end,
                "val_end": val_end,
            },
            "split": {
                "train_n": int(len(sp.train)),
                "val_n": int(len(sp.val)),
                "test_n": int(len(sp.test)),
                "test_prevalence": round(float(y_test.mean()), 4),
            },
            "base_rate": base_rate,
            "test": metrics,
            "threshold_0p5": threshold_metrics(y_test, p_test),
        }
        if importance is not None:  # served model → richer operating-point record
            report["operating_points"] = operating_points(y_test, p_test)
            report["f1_optimal_threshold"] = f1_optimal_threshold(y_test, p_test)
            report["feature_importance"] = importance
        (out_dir / f"{city}_{name}_{run_id}.json").write_text(json.dumps(report, indent=2))
        rows.append({"variant": name, "n_feat": len(feats), **{k: metrics[k] for k in HEADLINE}})
        print(
            f"  {name:18s} feats={len(feats):3d}  "
            + "  ".join(f"{k}={metrics[k]:.4f}" for k in HEADLINE)
        )

    print(f"[{city}] wrote {len(rows)} tracked runs → {out_dir}/{city}_*_{run_id}.json")
    return rows


def _fit_chicago_xgb(x_train, x_val, x_test, feats, y_train, y_val):
    """Chicago's production XGB fit for a feature subset — depth-3 monotone
    estimator + Platt on the raw val margin, mirroring retrain_xgb_sigmoid.py.

    Takes the already-`prepare_xgb_features`-prepped full frames (static_risk_tier
    / static_inspection_type as pandas-categorical) and selects `feats` — the same
    prepare-full-then-subset pattern the served forecast model uses, because
    `prepare_xgb_features` expects the full ALL_FEATURES frame. `build_production_xgb`
    derives monotone constraints over `feats`. Returns test-set probabilities.
    """
    est = build_production_xgb(scale_pos_weight=compute_scale_pos_weight(y_train), features=feats)
    est.fit(x_train[feats], y_train, verbose=False)
    margin = est.predict(x_val[feats], output_margin=True)
    platt = LogisticRegression(C=1e10, solver="lbfgs").fit(margin.reshape(-1, 1), y_val)
    coef, inter = float(platt.coef_[0, 0]), float(platt.intercept_[0])
    p_test = expit(coef * est.predict(x_test[feats], output_margin=True) + inter)
    return p_test, est


def run_chicago() -> list[dict]:
    """Chicago's parallel ablation frame, on its OWN production pipeline
    (features.parquet + depth-3 monotone XGB + the LogReg baseline), so numbers
    match the served Chicago model. Variants analogous to the NYC/LA frame:

      served_xgb_full           ALL_FEATURES (production XGB)
      xgb_forecast_only         FORECAST_FEATURES — drop the current-inspection
                                outcome (Chicago's Model-2 split); ≈ prior_only
      xgb_current_outcome_only  CURRENT_OUTCOME_FEATURES; ≈ current_only
      xgb_no_keywords           ALL minus the 12 flag_kw_*; ≈ no_theme_sev (drop
                                the text layer) AND measures the keyword flags'
                                value IN Chicago, where they ARE served
      logreg_full               the served LogReg baseline + sigmoid

    Dataset identity is the features.parquet content hash (provenance), not a raw
    snapshot — Chicago has a real features pipeline, unlike NYC/LA.
    """
    if not storage.exists(FEATURES_PATH):
        raise SystemExit(f"Missing {FEATURES_PATH}; run `make features` or stage the parquet.")
    feats_df = storage.read_parquet(FEATURES_PATH)
    # Same discipline as the served retrain: drop right-truncated rows (their
    # 180-day label window runs past the data, so labels are under-counted) from
    # modeling — otherwise the most-recent test slice is biased toward y=0.
    modelable = (
        feats_df.loc[~feats_df["right_truncated"]].reset_index(drop=True)
        if "right_truncated" in feats_df.columns
        else feats_df
    )
    sp = temporal_split(modelable, train_end=CHI_TRAIN_END, val_end=CHI_VAL_END)
    y_train = sp.train[LABEL_COL].astype(int).to_numpy()
    y_val = sp.val[LABEL_COL].astype(int).to_numpy()
    y_test = sp.test[LABEL_COL].astype(int).to_numpy()
    print(
        f"\n[chicago] train {len(sp.train):,} | val {len(sp.val):,} | test {len(sp.test):,} "
        f"| test base {y_test.mean():.3f}"
    )

    no_kw = [f for f in ALL_FEATURES if not f.startswith("flag_kw_")]
    variants = [
        ("served_xgb_full", "xgb", list(ALL_FEATURES)),
        ("xgb_forecast_only", "xgb", list(FORECAST_FEATURES)),
        ("xgb_current_outcome_only", "xgb", list(CURRENT_OUTCOME_FEATURES)),
        ("xgb_no_keywords", "xgb", no_kw),
        ("logreg_full", "logreg", list(ALL_FEATURES)),
    ]

    prov = provenance(FEATURES_PATH, list(ALL_FEATURES), REPO)
    run_id = prov["run_id"]
    vintage = pd.Timestamp(modelable["inspection_date"].max()).strftime("%Y%m%d")
    out_dir = REPO / "reports" / "metrics" / "chicago"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Prepare the XGB frames once on the full feature set (prepare_xgb_features
    # expects ALL_FEATURES); each variant selects its own columns from these.
    xtr = prepare_xgb_features(sp.train[ALL_FEATURES])
    cat = extract_categorical_dtypes(xtr)
    xval = prepare_xgb_features(sp.val[ALL_FEATURES], categorical_dtypes=cat)
    xtest = prepare_xgb_features(sp.test[ALL_FEATURES], categorical_dtypes=cat)

    rows = []
    for name, kind, feats in variants:
        importance = None
        if kind == "xgb":
            p_test, est = _fit_chicago_xgb(xtr, xval, xtest, feats, y_train, y_val)
            # Global feature importance for the DEPLOYED model (served config).
            if name == "served_xgb_full":
                importance = global_shap_importance(est, xtest[feats], feats)
        else:
            base = build_baseline_pipeline()
            base.fit(sp.train[feats], y_train)
            cal = CalibratedClassifierCV(FrozenEstimator(base), method="sigmoid")
            cal.fit(sp.val[feats], y_val)
            p_test = cal.predict_proba(sp.test[feats])[:, 1]
        metrics = evaluate(y_test, p_test).to_dict()

        report = {
            "model": f"chicago_{name}",
            "city": "chicago",
            "variant": name,
            "estimator": kind,
            "calibration": "sigmoid (platt)",
            "label": LABEL_COL,
            "n_features": len(feats),
            "data_vintage": vintage,
            **prov,
            "train_window": {"train_end": CHI_TRAIN_END, "val_end": CHI_VAL_END},
            "split": {
                "train_n": int(len(sp.train)),
                "val_n": int(len(sp.val)),
                "test_n": int(len(sp.test)),
                "test_prevalence": round(float(y_test.mean()), 4),
            },
            "test": metrics,
            "threshold_0p5": threshold_metrics(y_test, p_test),
        }
        if importance is not None:  # served model → richer operating-point record
            report["operating_points"] = operating_points(y_test, p_test)
            report["f1_optimal_threshold"] = f1_optimal_threshold(y_test, p_test)
            report["feature_importance"] = importance
        (out_dir / f"chicago_{name}_{run_id}.json").write_text(json.dumps(report, indent=2))
        rows.append({"variant": name, "n_feat": len(feats), **{k: metrics[k] for k in HEADLINE}})
        print(
            f"  {name:24s} feats={len(feats):3d}  "
            + "  ".join(f"{k}={metrics[k]:.4f}" for k in HEADLINE)
        )

    print(f"[chicago] wrote {len(rows)} tracked runs → {out_dir}/chicago_*_{run_id}.json")
    return rows


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    cities = ["chicago", "nyc", "la"] if which == "all" else [which]
    summary: dict[str, list[dict]] = {}
    for c in cities:
        summary[c] = run_chicago() if c == "chicago" else run_city(c)

    print("\n===== ABLATION SUMMARY (test set) =====")
    for c, rows in summary.items():
        print(f"\n{c.upper()}")
        for r in rows:
            metrics = "  ".join(f"{k}={r[k]:.4f}" for k in HEADLINE)
            print(f"  {r['variant']:24s} feats={r['n_feat']:3d}  {metrics}")


if __name__ == "__main__":
    main()
