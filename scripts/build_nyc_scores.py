"""Build NYC's scores.json in the exact Chicago schema (Phase 1, DR 0016).

NYC served model mirrors Chicago's production model: an XGBoost risk model
(depth-3) + Platt-on-margin calibration + native TreeSHAP drivers, so the
SHAP-waterfall + calibration-triple + tier machinery in `foodsafety.serve` /
`foodsafety.explain` reuse unchanged. Model 1 (risk) and Model 2 (forecast-only
trend basis) are both XGBoost; the forecast model uses a regularized shallow
config suited to its thin prior-history feature set. Both beat the LogReg
baseline on both gate metrics on NYC's own temporal splits.

Label: event-anchored — predict whether an establishment's NEXT scored
inspection is graded B/C (score >= 14). Post-COVID training window (NYC halted
inspections Mar 2020; usable data resumes 2022) — the direct analog of Chicago's
2019 cutoff. Trend: last-K-visits slope of a forecast-only model (DR 0011),
because NYC's ~annual cadence makes the 90-day window empty.

Run:  PYTHONPATH=src .venv/bin/python scripts/build_nyc_scores.py
Pulls NYC DOHMH data from SODA (cached under data/raw/), reads the committed
reference/violation_crosswalk.csv, and writes app/public/data/nyc/{scores,
inspection_history,methodology}.json. Rerun the app-side gen-search-index.mjs +
build-detail-data.mjs on the nyc/ files to produce the client search index and
per-establishment detail bundles (both build-time, gitignored).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.special import expit
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier

from foodsafety.config import RANDOM_STATE
from foodsafety.explain.shap_drivers import top_drivers_for_row, tree_contributions
from foodsafety.models.evaluate import evaluate, operating_point_table
from foodsafety.serve.predict_batch import assign_risk_tiers, write_scores_json
from foodsafety.tracking import snapshot_provenance
from foodsafety.utils.time import temporal_split

REPO = Path(__file__).resolve().parent.parent
CW = REPO / "reference" / "violation_crosswalk.csv"
# Raw pull cache — gitignored data/ dir (self-contained: pulled from SODA if absent).
RAW = REPO / "data" / "raw" / "nyc_inspections.parquet"
OUT = REPO / "app" / "public" / "data" / "nyc"
NYC_SODA = "https://data.cityofnewyork.us/resource/43nn-pn8j.json"
NYC_COLS = [
    "camis",
    "dba",
    "building",
    "street",
    "boro",
    "zipcode",
    "latitude",
    "longitude",
    "inspection_date",
    "action",
    "score",
    "grade",
    "critical_flag",
    "violation_code",
    "violation_description",
]


def load_nyc_raw() -> pd.DataFrame:
    """Full NYC DOHMH pull (43nn-pn8j), cached locally so reruns don't re-pull."""
    if RAW.exists():
        return pd.read_parquet(RAW)
    import urllib.parse
    import urllib.request

    rows, off, page = [], 0, 50000
    while True:
        q = urllib.parse.urlencode(
            {
                "$select": ",".join(NYC_COLS),
                "$order": "camis,inspection_date",
                "$limit": page,
                "$offset": off,
            },
            safe="(),$'*:,",
        )
        with urllib.request.urlopen(f"{NYC_SODA}?{q}", timeout=180) as r:
            batch = json.load(r)
        if not batch:
            break
        rows.extend(batch)
        off += page
        print(f"  pulled {len(rows):,} rows...")
        if len(batch) < page:
            break
    df = pd.DataFrame(rows)
    RAW.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(RAW, index=False)
    return df


BC_THRESHOLD = 14
# NYC halted inspections Mar 2020; grades/scores only normalise from 2022. Train
# on 2022-07-01+ anchors (post-COVID steady state) — the analog of Chicago's 2019
# cutoff. Earlier scored events are still used as burn-in for prior_* history.
# NYC label prevalence (P next graded B/C) on the held-out test set — the base
# rate the unified tier rule anchors on (DR 0017). Fixed so tier cutoffs stay
# stable across rescores; printed at runtime (test base) to spot large drift.
NYC_BASE_RATE = 0.41
NYC_TRAIN_START = "2022-07-01"
TRAIN_END = "2024-10-01"
VAL_END = "2025-04-01"
TREND_K = 5
MODEL_VERSION = "nyc_xgb_sigmoid"


# ----------------------------------------------------------------- feature build
def _grade_from_score(score: float) -> str:
    if pd.isna(score):
        return ""
    return "A" if score <= 13 else "B" if score <= 27 else "C"


def _short_action(a: object) -> str:
    s = str(a or "").lower()
    if "closed" in s and "re-open" not in s:
        return "Closed by DOHMH"
    if "re-open" in s:
        return "Re-opened"
    if "no violation" in s:
        return "Inspection (no violations)"
    if "cited" in s:
        return "Cycle Inspection"
    return "Inspection"


def _violation_lines(grp: pd.DataFrame) -> str:
    """Full cited-violation list for one inspection, critical first, one per line,
    deduped by code. Critical citations are flagged. This is the comment-shard text
    the detail-page timeline expands to (Chicago-parity); `headline` is just its
    first line, truncated. Empty when the inspection cited nothing."""
    v = grp.dropna(subset=["violation_description"])
    best: dict[str, tuple[str, bool]] = {}  # code -> (description, is_critical)
    order: list[str] = []
    for code, desc, cf in zip(
        v["violation_code"], v["violation_description"], v["critical_flag"], strict=False
    ):
        c = str(code)
        crit = str(cf) == "Critical"
        if c not in best:
            best[c] = (str(desc), crit)
            order.append(c)
        elif crit and not best[c][1]:
            best[c] = (best[c][0], True)
    # Critical first; stable within each group so the grp's own ordering is kept.
    order.sort(key=lambda c: not best[c][1])
    return "\n".join(f"{best[c][0]} (critical)" if best[c][1] else best[c][0] for c in order)


def _shard_of(license_id: str) -> str:
    # md5 first two hex chars → 256 even buckets. Must match the web app's shard
    # scheme (scores-server.ts / prebuild-sync-s3.mjs) so the build reads the right file.
    return hashlib.md5(license_id.encode()).hexdigest()[:2]


def write_comment_shards(comments: dict[str, list[str]], out_dir: Path) -> int:
    """Write the full violation text as 256 md5 shards ({license: [text_per_event]}),
    mirroring Chicago's export_inspection_history.py so prebuild-sync-s3.mjs re-shards
    them per license at build. Licenses whose every inspection cited nothing are
    skipped (a missing shard entry → the timeline falls back to the headline)."""
    shards: dict[str, dict[str, list[str]]] = {}
    for lid, arr in comments.items():
        if any(arr):
            shards.setdefault(_shard_of(lid), {})[lid] = arr
    out_dir.mkdir(parents=True, exist_ok=True)
    for sh, by_license in shards.items():
        (out_dir / f"{sh}.json").write_text(json.dumps(by_license, separators=(",", ":")))
    return sum(len(m) for m in shards.values())


def build_history(
    raw: pd.DataFrame, forecast_by_event: dict | None = None
) -> tuple[dict, dict[str, list[str]]]:
    """(history, comments). history is keyed by camis ->
    [{date, type, result, headline, score}] newest-first; comments is keyed the
    same, each an event-aligned list of the full cited-violation text.

    Mirrors Chicago's inspection_history.json shape. NYC `result` is the letter
    grade (A/B/C, derived from the score when the grade cell is blank on the
    initial visit); `headline` is the inspection's most-severe violation text;
    `score` is the forecast-only model's calibrated probability for that
    inspection (drives the detail-page trend chart, DR 0011). null for events
    that weren't scored.
    """
    forecast_by_event = forecast_by_event or {}
    r = raw.copy()
    r["_crit_rank"] = (r["critical_flag"].astype("string") == "Critical").astype(int)
    r = r.sort_values(["camis", "inspection_date", "_crit_rank"], ascending=[True, False, False])
    hist: dict[str, list[dict]] = {}
    for (camis, date), grp in r.groupby(["camis", "inspection_date"], sort=False):
        g0 = grp.iloc[0]
        grade = g0.get("grade")
        grade = (
            str(grade)
            if pd.notna(grade) and str(grade) in ("A", "B", "C")
            else _grade_from_score(g0.get("score"))
        )
        score = g0.get("score")
        result = f"Grade {grade}" if grade else ""
        if pd.notna(score):
            result = (result + f" (score {int(score)})").strip()
        desc = grp["violation_description"].dropna()
        headline = ""
        if len(desc):
            h = str(desc.iloc[0])
            headline = h[:100] + "…" if len(h) > 100 else h
        date_str = pd.Timestamp(date).strftime("%Y-%m-%d")
        fc = forecast_by_event.get((str(camis), date_str))
        hist.setdefault(str(camis), []).append(
            {
                "date": date_str,
                "type": _short_action(g0.get("action")),
                "result": result,
                "headline": headline,
                "score": None if fc is None else round(float(fc), 6),
                # Rides along on the event so the date-sort below keeps it aligned;
                # popped into `comments` (and out of the history payload) after.
                "_comment": _violation_lines(grp),
            }
        )
    comments: dict[str, list[str]] = {}
    for k in hist:
        hist[k].sort(key=lambda e: e["date"], reverse=True)
        comments[k] = [e.pop("_comment") for e in hist[k]]
    return hist, comments


def build_events() -> tuple[pd.DataFrame, list[str], list[str], list[str], list[str], pd.DataFrame]:
    raw = load_nyc_raw()
    cw = pd.read_csv(CW)
    nyc_theme = cw[cw.city == "NYC"].set_index("native_code")["theme"].to_dict()
    nyc_sev = cw[cw.city == "NYC"].set_index("native_code")["severity_tier"].to_dict()

    raw["inspection_date"] = pd.to_datetime(raw["inspection_date"], errors="coerce")
    raw["score"] = pd.to_numeric(raw["score"], errors="coerce")
    raw = raw[raw["inspection_date"] > "2010-01-01"].copy()
    raw["theme"] = raw["violation_code"].map(nyc_theme)
    raw["sev"] = raw["violation_code"].map(nyc_sev)
    raw["is_viol"] = raw["violation_code"].notna().astype("int8")
    raw["is_critical"] = (raw["critical_flag"].astype("string") == "Critical").astype("int8")

    keys = ["camis", "inspection_date"]
    theme_ct = raw.pivot_table(
        index=keys, columns="theme", values="is_viol", aggfunc="sum", fill_value=0
    )
    theme_ct.columns = [f"cur_theme_{c}" for c in theme_ct.columns]
    sev_ct = raw.pivot_table(
        index=keys, columns="sev", values="is_viol", aggfunc="sum", fill_value=0
    )
    sev_ct.columns = [f"cur_sev_{c}" for c in sev_ct.columns]

    def first(s):
        s = s.dropna()
        return s.iloc[0] if len(s) else None

    agg = (
        raw.groupby(keys)
        .agg(
            cur_score=("score", "max"),
            cur_n_viol=("is_viol", "sum"),
            cur_n_critical=("is_critical", "sum"),
            dba_name=("dba", first),
            building=("building", first),
            street=("street", first),
            boro=("boro", first),
            zip=("zipcode", first),
            lat=("latitude", first),
            lon=("longitude", first),
        )
        .reset_index()
    )
    ev = agg.join(theme_ct, on=keys).join(sev_ct, on=keys)
    ct_cols = list(theme_ct.columns) + list(sev_ct.columns)
    ev[ct_cols] = ev[ct_cols].fillna(0).astype("int32")
    ev = ev[ev["cur_score"].notna()].copy()
    ev = ev.sort_values(["camis", "inspection_date"], kind="mergesort").reset_index(drop=True)
    ev["cur_is_bad"] = (ev["cur_score"] >= BC_THRESHOLD).astype("int8")

    theme_cols = [c for c in ev.columns if c.startswith("cur_theme_")]
    sev_cols = [c for c in ev.columns if c.startswith("cur_sev_")]

    g = ev.groupby("camis", sort=False)
    ev["prior_inspections"] = g.cumcount().astype("int32")
    ev["prior_bad"] = (g["cur_is_bad"].cumsum() - ev["cur_is_bad"]).astype("int32")
    ev["prior_n_critical"] = (g["cur_n_critical"].cumsum() - ev["cur_n_critical"]).astype("int32")
    _cum = g["cur_score"].cumsum() - ev["cur_score"]
    ev["prior_mean_score"] = (_cum / ev["prior_inspections"].replace(0, np.nan)).astype("float32")
    ev["prior_bad_rate"] = (ev["prior_bad"] / ev["prior_inspections"].replace(0, np.nan)).astype(
        "float32"
    )
    ev["prev_score"] = g["cur_score"].shift(1).astype("float32")
    ev["prev_is_bad"] = g["cur_is_bad"].shift(1).astype("float32")
    ev["days_since_last_inspection"] = (
        ev["inspection_date"] - g["inspection_date"].shift(1)
    ).dt.days.astype("float32")
    for c in sev_cols:
        ev[f"prior_{c}"] = (g[c].cumsum() - ev[c]).astype("int32")

    ev["next_score"] = g["cur_score"].shift(-1).astype("float32")
    ev["next_date"] = g["inspection_date"].shift(-1)
    ev["y_next_bc"] = (ev["next_score"] >= BC_THRESHOLD).astype("float32")

    # display fields
    ev["dba_name"] = ev["dba_name"].fillna("").astype(str).str.strip()
    ev["address"] = (
        ev["building"].fillna("").astype(str).str.strip()
        + " "
        + ev["street"].fillna("").astype(str).str.strip()
    ).str.strip()
    ev["license_id"] = ev["camis"].astype(str)
    ev["lat"] = pd.to_numeric(ev["lat"], errors="coerce")
    ev["lon"] = pd.to_numeric(ev["lon"], errors="coerce")

    prior_sev = [f"prior_{c}" for c in sev_cols]
    PRIOR = [
        "prior_inspections",
        "prior_bad",
        "prior_n_critical",
        "prior_mean_score",
        "prior_bad_rate",
        "prev_score",
        "prev_is_bad",
        "days_since_last_inspection",
    ] + prior_sev
    CURRENT = ["cur_score", "cur_n_viol", "cur_n_critical", "cur_is_bad"] + sev_cols + theme_cols
    return ev, PRIOR, CURRENT, theme_cols, sev_cols, raw


# ------------------------------------------------------------------ NYC driver labels
def nyc_labels(theme_cols, sev_cols) -> dict:
    sev_name = {"T1": "imminent-hazard", "T2": "critical", "T3": "general"}
    lab = {
        "cur_score": "Current inspection score: {value}",
        "cur_n_viol": "{value} violations at this inspection",
        "cur_n_critical": "{value} critical violations at this inspection",
        "cur_is_bad": {
            True: "Current inspection scored in the B/C range",
            False: "Current inspection scored in the A range",
        },
        "prior_inspections": "{value} prior inspections on record",
        "prior_bad": "{value} prior inspections graded B/C",
        "prior_n_critical": "{value} critical violations in prior inspections",
        "prior_mean_score": "Average past inspection score: {value:.1f}",
        "prior_bad_rate": "Past B/C rate: {value}",
        "prev_score": "Previous inspection score: {value}",
        "prev_is_bad": {True: "Previous inspection was B/C", False: "Previous inspection was A"},
        "days_since_last_inspection": "{value} days since the last inspection",
    }
    for c in sev_cols:
        t = c.replace("cur_sev_", "")
        lab[c] = f"{{value}} {sev_name.get(t, t)}-tier violations now"
        lab[f"prior_{c}"] = f"{{value}} prior {sev_name.get(t, t)}-tier violations"
    for c in theme_cols:
        pretty = c.replace("cur_theme_", "").replace("_", " ")
        lab[c] = f"{{value}} {pretty} violations at this inspection"
    return lab


# --------------------------------------------------------------------- fit + calibrate
def fit_xgb_platt(train, val, feats, label="y_next_bc", *, regularized=False):
    """Fit XGB + Platt-on-margin calibration, mirroring Chicago's serve path.

    Returns ``(xgb, coef, inter)``: the calibrated risk is
    ``expit(coef * raw_margin + inter)`` (see ``xgb_proba``), and TreeSHAP drivers
    come from ``tree_contributions(xgb, ...)``. The risk model (Model 1) uses the
    gate-validated depth-3 config; ``regularized=True`` gives the forecast-only
    model (Model 2) a shallower, heavily-regularized config for its thin
    prior-history feature set (deeper trees over-fit that set — see gate CV).
    Non-monotone: NYC/LA feature names don't map to Chicago's monotone direction
    conventions, and the non-monotone config is the one that won the gate.
    """
    y = train[label].astype(int)
    spw = (len(y) - float(y.sum())) / max(float(y.sum()), 1.0)
    common = dict(
        scale_pos_weight=spw,
        missing=np.nan,
        random_state=RANDOM_STATE,
        n_jobs=4,
        eval_metric="aucpr",
    )
    if regularized:
        clf = XGBClassifier(
            n_estimators=120,
            max_depth=2,
            learning_rate=0.03,
            subsample=0.7,
            colsample_bytree=0.7,
            reg_lambda=8.0,
            reg_alpha=1.0,
            min_child_weight=30,
            gamma=1.0,
            **common,
        )
    else:
        clf = XGBClassifier(
            n_estimators=400,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            min_child_weight=5,
            **common,
        )
    clf.fit(train[feats], y)
    # Platt on the raw margin (1-D logistic) — the {a, b} the app waterfall expects
    # live in margin space, unlike CalibratedClassifierCV's double-squash.
    margin_val = clf.predict(val[feats], output_margin=True)
    platt = LogisticRegression(C=1e10, solver="lbfgs").fit(
        margin_val.reshape(-1, 1), val[label].astype(int)
    )
    return clf, float(platt.coef_[0, 0]), float(platt.intercept_[0])


def xgb_proba(clf, coef, inter, X):
    """Calibrated positive-class probability: Platt on the raw XGB margin."""
    return expit(coef * clf.predict(X, output_margin=True) + inter)


def last_k_trend(events_scored: pd.DataFrame, anchors: pd.DataFrame, k: int) -> pd.Series:
    """OLS slope of the forecast risk over each camis's last K scored inspections."""
    slopes = []
    idx = events_scored.set_index("license_id")
    for lic, adate in anchors[["license_id", "inspection_date"]].itertuples(index=False):
        try:
            sub = idx.loc[[lic]]
        except KeyError:
            slopes.append(np.nan)
            continue
        sub = sub[sub["inspection_date"] <= adate].sort_values("inspection_date").tail(k)
        if len(sub) < 2:
            slopes.append(np.nan)
            continue
        x = (sub["inspection_date"] - sub["inspection_date"].min()).dt.days.to_numpy(float)
        y = sub["forecast_risk"].to_numpy(float)
        try:
            slopes.append(float(np.polyfit(x, y, 1)[0]))
        except (np.linalg.LinAlgError, ValueError):
            slopes.append(np.nan)
    return pd.Series(slopes, index=anchors.index)


def main():
    ev, PRIOR, CURRENT, theme_cols, sev_cols, raw = build_events()
    FEATS_M1 = PRIOR + CURRENT
    labels = nyc_labels(theme_cols, sev_cols)
    print(f"scored events {len(ev):,} | establishments {ev.camis.nunique():,}")

    # ---- train on post-COVID anchors that have a next inspection (label present)
    anch = ev[ev["next_score"].notna() & (ev["inspection_date"] >= NYC_TRAIN_START)].copy()
    sp = temporal_split(anch, date_col="inspection_date", train_end=TRAIN_END, val_end=VAL_END)
    print(
        f"train {len(sp.train):,} | val {len(sp.val):,} | test {len(sp.test):,} "
        f"| test base {sp.test.y_next_bc.mean():.3f}"
    )

    xgb1, coef1, inter1 = fit_xgb_platt(sp.train, sp.val, FEATS_M1)
    # forecast-only trend model: thin PRIOR set -> regularized shallow config
    xgb2, coef2, inter2 = fit_xgb_platt(sp.train, sp.val, PRIOR, regularized=True)
    y_test = sp.test["y_next_bc"].astype(int).values
    p_test = xgb_proba(xgb1, coef1, inter1, sp.test[FEATS_M1])
    test_metrics = evaluate(y_test, p_test).to_dict()
    print(
        "Model 1 test:", {k: test_metrics[k] for k in ("pr_auc", "roc_auc", "precision_at_10pct")}
    )

    # ---- score EVERY establishment's latest scored inspection (serving anchor)
    ev["risk_score"] = xgb_proba(xgb1, coef1, inter1, ev[FEATS_M1])
    ev["forecast_risk"] = xgb_proba(xgb2, coef2, inter2, ev[PRIOR])
    # Collapse reopened establishments: a reopen mints a new record id at the same
    # name+address, which would otherwise render as duplicate map/search pins. Dedup
    # on a normalised name+address key, keeping the most recently inspected; mirrors
    # Chicago serving.
    latest = ev.sort_values("inspection_date").copy()

    def _norm(col: str) -> pd.Series:
        return (
            latest[col]
            .fillna("")
            .astype(str)
            .str.upper()
            .str.replace(r"[^A-Z0-9]+", " ", regex=True)
            .str.strip()
        )

    _estab = _norm("dba_name") + " @ " + _norm("address")
    latest = latest[~_estab.duplicated(keep="last")].copy()
    print(f"serving rows (latest per establishment): {len(latest):,}")

    # SHAP drivers via native TreeSHAP (margin space) — same machinery as Chicago's
    # served XGB. base_margin is shipped as calibration.intercept below.
    contribs, base_margin = tree_contributions(xgb1, latest[FEATS_M1], FEATS_M1)
    contribs.index = latest.index
    drivers = []
    for i, row in latest.iterrows():
        ds = top_drivers_for_row(row[FEATS_M1], contribs.loc[i], k=5, labels=labels)
        drivers.append([d.to_dict() for d in ds])
    latest["top_drivers"] = drivers

    # trend: last-K forecast slope of the forecast-only model (schema 0.5.0)
    latest["trend_slope"] = last_k_trend(
        ev[["license_id", "inspection_date", "forecast_risk"]], latest, TREND_K
    )
    latest["as_of_date"] = latest["inspection_date"]

    # ---- tier with the unified cross-city rule (DR 0017): cutoffs anchored to
    # NYC's own base rate, not per-city quantiles. Same rule as Chicago / LA.
    latest["risk_tier"], thr = assign_risk_tiers(latest["risk_score"], NYC_BASE_RATE)
    print(
        f"NYC risk_score dist: p50={latest.risk_score.median():.3f} "
        f"p90={latest.risk_score.quantile(0.9):.3f} max={latest.risk_score.max():.3f}"
    )
    print(f"NYC tier thresholds (base={NYC_BASE_RATE}): {thr}")
    print("tier counts:", latest["risk_tier"].value_counts().to_dict())

    # App waterfall formula: logit = -(a*margin + b), margin = intercept + Σshap.
    # Platt logit(p) = coef*margin + inter  ->  a = -coef, b = -inter; the intercept
    # is the TreeSHAP base margin (so intercept + Σshap == raw margin).
    calibration = {"a": -coef1, "b": -inter1, "intercept": float(base_margin)}

    # Persist both models for rollback / provenance (S3-archival only; not app-read,
    # scores.json is the served artifact). Versioned by data vintage (the snapshot's
    # latest inspection date) so a rebuild on the same pull is idempotent. Published
    # to S3 by `make publish-cities`; the raw pull snapshot is the reproducibility
    # anchor (the SODA feed drifts over time).
    models_dir = REPO / "data" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    ver = pd.Timestamp(ev["inspection_date"].max()).strftime("%Y%m%d")
    for tag, clf, coef, inter, feats in [
        (MODEL_VERSION, xgb1, coef1, inter1, FEATS_M1),
        ("nyc_xgb_forecast_sigmoid", xgb2, coef2, inter2, PRIOR),
    ]:
        joblib.dump(
            {
                "model": clf,
                "platt_coef": coef,
                "platt_intercept": inter,
                "features": list(feats),
                "model_version": tag,
            },
            models_dir / f"{tag}_{ver}.joblib",
        )
    print(f"Saved models → {models_dir}/{MODEL_VERSION}_{ver}.joblib (+ forecast)")

    cols = [
        "license_id",
        "dba_name",
        "address",
        "lat",
        "lon",
        "as_of_date",
        "risk_score",
        "risk_tier",
        "top_drivers",
        "trend_slope",
    ]
    out = latest[cols].reset_index(drop=True)
    OUT.mkdir(parents=True, exist_ok=True)
    write_scores_json(
        out,
        str(OUT / "scores.json"),
        schema_version="0.5.0",
        model_version=MODEL_VERSION,
        label_window_days=0,
        calibration=calibration,
        risk_tier_thresholds=thr,
    )
    print(f"\nWrote {OUT / 'scores.json'}  ({len(out):,} establishments)")

    # ---- inspection_history.json (detail page) ----
    # per-event forecast score powers the trend chart; key on (camis, YYYY-MM-DD)
    forecast_by_event = {
        (r.license_id, pd.Timestamp(r.inspection_date).strftime("%Y-%m-%d")): r.forecast_risk
        for r in ev.itertuples(index=False)
    }
    hist, comments = build_history(raw, forecast_by_event)
    (OUT / "inspection_history.json").write_text(json.dumps(hist, separators=(",", ":")))
    print(f"Wrote inspection_history.json ({len(hist):,} establishments)")
    # Full violation text, md5-sharded (Chicago-parity). Gitignored; publish.py
    # uploads to web-app-data/nyc/comments/ and prebuild-sync-s3.mjs pulls it.
    n_c = write_comment_shards(comments, OUT / "comments")
    print(f"Wrote comment shards for {n_c:,} establishments → {OUT / 'comments'}")

    # ---- search-index.json (client-side search) ----
    def top_driver(drivers):
        if not drivers:
            return None
        d = drivers[0]
        return {"feature": d["feature"], "label": d["label"], "up": d["shap"] > 0}

    tier_counts = out["risk_tier"].value_counts().to_dict()
    search = {
        "schema_version": "1",
        "generated_at": datetime.now(UTC).isoformat(),
        "total": int(len(out)),
        "tier_counts": {
            t: int(tier_counts.get(t, 0)) for t in ("Low", "Moderate", "Elevated", "High")
        },
        "rows": [
            {
                "license_id": r.license_id,
                "dba_name": r.dba_name,
                "address": r.address,
                "lat": None if pd.isna(r.lat) else float(r.lat),
                "lon": None if pd.isna(r.lon) else float(r.lon),
                "risk_score": round(float(r.risk_score), 4),
                "risk_tier": r.risk_tier,
                "trend_slope": None if pd.isna(r.trend_slope) else round(float(r.trend_slope), 6),
                "top_driver": top_driver(r.top_drivers),
            }
            for r in out.itertuples(index=False)
        ],
    }
    (OUT / "search-index.json").write_text(json.dumps(search, separators=(",", ":")))
    print(f"Wrote search-index.json ({len(search['rows']):,} rows)")

    # ---- methodology.json (how-it-works page, NYC copy) ----
    op = (
        operating_point_table(y_test, p_test)
        .rename(columns={"inspect_top_frac": "frac"})
        .to_dict("records")
    )
    shares = (out["risk_tier"].value_counts(normalize=True)).to_dict()
    methodology = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model_version": MODEL_VERSION,
        "city": "nyc",
        "data_source": "NYC DOHMH Restaurant Inspections (43nn-pn8j)",
        "label": "Probability the establishment's NEXT inspection is graded B or C (score ≥ 14)",
        "train_window": f"post-COVID, {NYC_TRAIN_START} onward (inspections halted Mar 2020)",
        "provenance": {"model_version": MODEL_VERSION, "note": "feasibility build, DR 0016"},
        "test": {
            "n": int(len(y_test)),
            "prevalence": round(float(y_test.mean()), 4),
            "events": int(y_test.sum()),
            "split_from": VAL_END,
        },
        "headline": {
            "pr_auc": round(test_metrics["pr_auc"], 4),
            "roc_auc": round(test_metrics["roc_auc"], 4),
            "top_decile_lift": round(test_metrics["top_decile_lift"], 2),
        },
        "caveat": (
            "NYC is a coverage feature with a weaker signal than Chicago "
            "(ROC-AUC ~0.66 vs ~0.78); its data window is only ~3 post-COVID years."
        ),
        "risk_tiers": [
            {
                "label": name,
                "min": round(lo, 4),
                "max": (None if cut > 1.0 else round(cut, 4)),
                "share": round(shares.get(name, 0), 4),
            }
            for (cut, name), lo in zip(thr, [0.0, thr[0][0], thr[1][0], thr[2][0]], strict=True)
        ],
        "operating_points": op,
    }
    (OUT / "methodology.json").write_text(json.dumps(methodology, indent=2))
    print("Wrote methodology.json")

    # ---- tracked experiment record (reports/metrics/nyc/) ----
    # Diffable, git-committed ledger of the SERVED NYC model, alongside Chicago's
    # baseline/ and xgb/ reports. Dataset identity is the raw-pull snapshot hash
    # (the reproducibility anchor — the SODA feed drifts), stamped via
    # snapshot_provenance so same-commit reruns share a run_id and don't collide.
    prov = snapshot_provenance([RAW], FEATS_M1, REPO)
    run_id = prov["run_id"]
    metrics_dir = REPO / "reports" / "metrics" / "nyc"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "model": MODEL_VERSION,
        "city": "nyc",
        "calibration": "xgboost + platt (sigmoid) on val",
        "label": "y_next_bc (next inspection graded B/C, score >= 14)",
        "data_vintage": ver,
        **prov,
        "train_window": {
            "train_start": NYC_TRAIN_START,
            "train_end": TRAIN_END,
            "val_end": VAL_END,
        },
        "split": {
            "train_n": int(len(sp.train)),
            "val_n": int(len(sp.val)),
            "test_n": int(len(sp.test)),
            "test_prevalence": round(float(sp.test.y_next_bc.mean()), 4),
        },
        "base_rate": NYC_BASE_RATE,
        "tier_thresholds": [c for c, _ in thr[:3]],
        "n_establishments": int(len(out)),
        "test": test_metrics,
        "operating_points": op,
    }
    (metrics_dir / f"nyc_{run_id}.json").write_text(json.dumps(report, indent=2))
    print(f"Saved metrics report → {metrics_dir}/nyc_{run_id}.json")

    # stash the NYC tier thresholds + metrics for the DR / Phase 2 config
    (OUT / "_nyc_build_meta.json").write_text(
        json.dumps(
            {
                "model_version": MODEL_VERSION,
                "tier_thresholds": [c for c, _ in thr[:3]],
                "base_rate": NYC_BASE_RATE,
                "train_start": NYC_TRAIN_START,
                "split": {"train_end": TRAIN_END, "val_end": VAL_END},
                "test_metrics": test_metrics,
                "calibration": calibration,
                "n_establishments": int(len(out)),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
