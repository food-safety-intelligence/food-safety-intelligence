"""Feature-family + model-class ablations for the NYC and LA served models.

Chicago's model log (`docs/model-experiments.md`) already answers "which feature
family carries the signal" and "LogReg vs XGBoost" for Chicago. The two new
cities shipped as single served configs (DR 0016) with no comparable ablation
record. This runner closes that gap: it reuses each city's own `build_events` +
`fit_xgb_platt` so the numbers are apples-to-apples with production, holds the
temporal split fixed, and evaluates every variant on the SAME held-out test set.

Each variant is written as its own tracked run under
`reports/metrics/<city>/<city>_<variant>_<run_id>.json`, stamped with
`snapshot_provenance` (git SHA + raw-pull content hash) exactly like the served
build. This does NOT touch any committed app JSON — it only fits + evaluates.

Variants (all share the served temporal split; XGB uses the served depth-3
config, LogReg mirrors Chicago's baseline: median-impute + scale + balanced
logistic, sigmoid-calibrated on val):
  - served_xgb_full   XGB on PRIOR + CURRENT (the production feature set)
  - xgb_prior_only    XGB on prior-history features only (no current inspection)
  - xgb_current_only  XGB on current-inspection features only
  - xgb_no_theme_sev  XGB on the set minus the crosswalk theme + severity-tier
                      columns (cur_theme_*, cur_sev_T1/T2/T3, and their prior_*
                      rollups) — these are derived from the violation CODE via
                      reference/violation_crosswalk.csv, not from free text
  - xgb_plus_keywords XGB on PRIOR + CURRENT + Chicago's 12 Layer-B keyword flags
                      (regex on the violation free text) — does regex-on-text add
                      anything on top of the served set? (NYC/LA don't ship this)
  - logreg_full       LogReg + sigmoid on PRIOR + CURRENT (model-class comparator)

Run:  PYTHONPATH=src .venv/bin/python scripts/run_city_ablations.py [nyc|la|all]
Reads the cached raw pull under data/raw/ (pulled fresh if absent, like the
served build).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.frozen import FrozenEstimator
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from foodsafety.config import RANDOM_STATE
from foodsafety.features.keyword_flags import add_keyword_flags
from foodsafety.models.evaluate import evaluate
from foodsafety.tracking import snapshot_provenance
from foodsafety.utils.time import temporal_split

REPO = Path(__file__).resolve().parent.parent
# Import the city producers as modules so the ablations reuse the exact
# feature-build + fit code that ships to production (module import has no side
# effects; the raw pull only happens when build_events/build_raw are called).
sys.path.insert(0, str(REPO / "scripts"))
import build_la_scores as la  # noqa: E402
import build_nyc_scores as nyc  # noqa: E402

HEADLINE = ("pr_auc", "roc_auc", "precision_at_10pct", "top_decile_lift", "brier_score")


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
        if kind == "xgb":
            clf, coef, inter = fit_xgb(sp.train, sp.val, feats, label=label)
            p_test = xgb_proba(clf, coef, inter, sp.test[feats])
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
        }
        (out_dir / f"{city}_{name}_{run_id}.json").write_text(json.dumps(report, indent=2))
        rows.append({"variant": name, "n_feat": len(feats), **{k: metrics[k] for k in HEADLINE}})
        print(
            f"  {name:18s} feats={len(feats):3d}  "
            + "  ".join(f"{k}={metrics[k]:.4f}" for k in HEADLINE)
        )

    print(f"[{city}] wrote {len(rows)} tracked runs → {out_dir}/{city}_*_{run_id}.json")
    return rows


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    cities = ["nyc", "la"] if which == "all" else [which]
    summary: dict[str, list[dict]] = {}
    for c in cities:
        summary[c] = run_city(c)

    print("\n===== ABLATION SUMMARY (test set) =====")
    for c, rows in summary.items():
        print(f"\n{c.upper()}")
        print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
