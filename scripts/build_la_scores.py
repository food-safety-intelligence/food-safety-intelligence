"""Build Los Angeles County's scores.json in the current Chicago/NYC schema (DR 0016).

LA served model mirrors Chicago's production model: a LogisticRegression pipeline
+ sigmoid (Platt) calibration, so the SHAP-waterfall + calibration-triple + tier
machinery in `foodsafety.serve` / `foodsafety.explain` reuse unchanged. XGBoost
stays only as the feasibility comparator (not served).

Two things make LA different from Chicago/NYC (see DR 0016):

1. LA County left Socrata; the fresh feed is a bulk CSV on ArcGIS Hub (item
   19b6607a…), not a queryable SODA endpoint. We download and cache it like the
   SODA pulls. Violations are a separate feed (5eaea9f8…) joined on serial_number.
2. Grade DIRECTION is FLIPPED. LA grades A/B/C on a 0-100 scale where HIGHER is
   cleaner (A = 90-100). So the label is `next inspection graded B or C`, i.e.
   next score < 90 — the opposite of Chicago (fail/priority) and NYC (score ≥ 14).
   Every "bad = ..." comparison below is written for LA's direction.

The LA feed carries no coordinates, so we geocode facility addresses once via the
free US Census batch geocoder, cache the result in reference/la_facility_coords.csv
(committed → rebuilds are offline), and fall back to each address's zip centroid
(computed from the geocoded set) for the few the geocoder can't place.

Label window: LA County's fresh feed starts 2023-04-01, already post-COVID, so
there is no pre-cutoff burn-in to carve out (unlike Chicago's 2019 / NYC's 2022).

Run:  PYTHONPATH=src .venv/bin/python scripts/build_la_scores.py
Writes app/public/data/la/{scores,inspection_history,methodology,search-index}.json.
Rerun the app-side gen-search-index.mjs + build-detail-data.mjs on the la/ files
to produce the client detail bundles (build-time, gitignored).
"""

from __future__ import annotations

import csv
import io
import json
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.frozen import FrozenEstimator
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from foodsafety.config import RANDOM_STATE
from foodsafety.explain.shap_drivers import linear_contributions, top_drivers_for_row
from foodsafety.models.evaluate import evaluate, operating_point_table
from foodsafety.serve.predict_batch import write_scores_json
from foodsafety.utils.time import temporal_split

REPO = Path(__file__).resolve().parent.parent
CW = REPO / "reference" / "violation_crosswalk.csv"
COORDS = REPO / "reference" / "la_facility_coords.csv"  # committed geocode cache
# Raw pull cache — gitignored data/ dir (self-contained: downloaded if absent).
RAW_INSP = REPO / "data" / "raw" / "la_inspections.parquet"
RAW_VIOL = REPO / "data" / "raw" / "la_violations.parquet"
OUT = REPO / "app" / "public" / "data" / "la"

# LA County Environmental Health, ArcGIS Hub bulk-CSV items (2023-04-01 → 2026-03-31)
ARCGIS_ITEM = "https://www.arcgis.com/sharing/rest/content/items/{item}/data"
INSP_ITEM = "19b6607ac82c4512b10811870975dbdc"
VIOL_ITEM = "5eaea9f89b7549ee841da7617d3a9cba"

# LA grades A/B/C on 0-100 where HIGHER is cleaner. "Bad" = graded B or C = score < 90.
BAD_BELOW = 90
# The fresh feed is entirely post-COVID (starts 2023-04) with no abrupt grading or
# procedure change inside the window (mean score is flat ~94.5 across 2023-2026; the
# B/C rate drifts up gradually, not a step-change) — so no burn-in cutoff is needed,
# unlike Chicago's July-2018 change or NYC's 2020 COVID halt.
# Cadence note: LA facilities are inspected ~annually, so a facility's *latest*
# inspection is its serving anchor and never carries a forward label — the labelled
# anchors skew to 2023-2024. Split boundaries are set so val/test still get a few
# thousand late-window anchors each.
LA_TRAIN_START = "2023-04-01"
TRAIN_END = "2024-07-01"
VAL_END = "2025-01-01"
TREND_K = 5
MODEL_VERSION = "la_logreg_sigmoid"

CENSUS_BATCH = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"


# ------------------------------------------------------------------------- data pull
def _download_csv(item: str) -> pd.DataFrame:
    """Download an ArcGIS Hub CSV item (LA left Socrata → no queryable API)."""
    url = ARCGIS_ITEM.format(item=item)
    with urllib.request.urlopen(url, timeout=300) as r:
        raw = r.read()
    # The LA feed contains a few non-UTF-8 bytes in owner names; latin-1 is lossless.
    df = pd.read_csv(io.StringIO(raw.decode("latin-1")), dtype=str)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    return df


def load_la_raw() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Inspections (one row per inspection) + violations (one row per violation),
    both cached locally so reruns don't re-download the ~65 MB of CSV."""
    if RAW_INSP.exists() and RAW_VIOL.exists():
        return pd.read_parquet(RAW_INSP), pd.read_parquet(RAW_VIOL)
    insp = _download_csv(INSP_ITEM)
    viol = _download_csv(VIOL_ITEM)
    RAW_INSP.parent.mkdir(parents=True, exist_ok=True)
    insp.to_parquet(RAW_INSP, index=False)
    viol.to_parquet(RAW_VIOL, index=False)
    return insp, viol


# --------------------------------------------------------------------------- geocode
def _census_batch_geocode(fac: pd.DataFrame) -> pd.DataFrame:
    """Geocode facilities via the free US Census batch endpoint (no API key).

    fac columns: facility_id, address, city, state, zip. Returns the matched
    subset with facility_id, lat, lon. Unmatched facilities are simply absent
    (the caller fills them with a zip centroid).
    """
    import urllib.request as _r

    matched: list[dict] = []
    rows = fac.itertuples(index=False)
    batch: list[tuple] = []

    def flush(chunk: list[tuple]) -> None:
        if not chunk:
            return
        buf = io.StringIO()
        w = csv.writer(buf)
        for fid, addr, city, state, zc in chunk:
            w.writerow([fid, addr, city, state, zc])
        body, boundary = _multipart(buf.getvalue())
        req = _r.Request(
            f"{CENSUS_BATCH}?benchmark=Public_AR_Current",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        # One flaky/timed-out batch must not sink the whole run: the facilities in
        # a failed batch simply fall through to the zip-centroid fallback.
        try:
            with _r.urlopen(req, timeout=120) as resp:
                text = resp.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 — network hiccup → zip-centroid fallback
            print(f"  batch of {len(chunk)} failed ({e}); those fall back to zip centroid")
            return
        for rec in csv.reader(io.StringIO(text)):
            # id, input, match, matchtype, matched_addr, "lon,lat", tigerline, side
            if len(rec) >= 6 and rec[2] == "Match" and rec[5]:
                lon, lat = rec[5].split(",")
                matched.append({"facility_id": rec[0], "lat": float(lat), "lon": float(lon)})

    for row in rows:
        batch.append((row.facility_id, row.address, row.city, row.state, row.zip))
        if len(batch) >= 1000:  # Census caps a batch at 10k; 1k keeps each request quick
            flush(batch)
            batch = []
            print(f"  geocoded {len(matched):,} so far...", flush=True)
    flush(batch)
    return pd.DataFrame(matched)


def _multipart(csv_text: str) -> tuple[bytes, str]:
    boundary = "----lacountygeocode"
    parts = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="addressFile"; filename="a.csv"\r\n'
        "Content-Type: text/csv\r\n\r\n"
        f"{csv_text}\r\n"
        f"--{boundary}--\r\n"
    )
    return parts.encode("utf-8"), boundary


def load_facility_coords(fac: pd.DataFrame) -> pd.DataFrame:
    """facility_id -> (lat, lon). Reads the committed cache; geocodes anything new
    via Census; fills the rest with the zip centroid of the geocoded set. Writes
    the full result back so a fresh clone rebuilds offline."""
    fac = fac.drop_duplicates("facility_id").copy()
    if COORDS.exists():
        cache = pd.read_csv(COORDS, dtype={"facility_id": str})
        if set(fac.facility_id) <= set(cache.facility_id):
            return cache  # cache already covers every served facility → no network
    else:
        cache = pd.DataFrame(columns=["facility_id", "lat", "lon", "geo_source"])

    todo = fac[~fac.facility_id.isin(set(cache.facility_id))]
    print(f"geocoding {len(todo):,} new facilities via Census (cache had {len(cache):,})...")
    got = _census_batch_geocode(todo) if len(todo) else pd.DataFrame(columns=["facility_id"])
    got["geo_source"] = "census"
    out = pd.concat([cache[["facility_id", "lat", "lon", "geo_source"]], got], ignore_index=True)

    # zip-centroid fallback for facilities Census could not place — derived from the
    # geocoded set itself, so no external zip-centroid table is needed.
    placed = out.dropna(subset=["lat", "lon"]).merge(
        fac[["facility_id", "zip"]], on="facility_id", how="left"
    )
    zc = placed.groupby("zip")[["lat", "lon"]].mean()
    missing = fac[~fac.facility_id.isin(set(out.dropna(subset=["lat"]).facility_id))]
    fill = missing.merge(zc, left_on="zip", right_index=True, how="left")[
        ["facility_id", "lat", "lon"]
    ]
    fill["geo_source"] = "zip_centroid"
    result = pd.concat([out.dropna(subset=["lat"]), fill.dropna(subset=["lat"])], ignore_index=True)
    result = result.drop_duplicates("facility_id")
    COORDS.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(COORDS, index=False)
    print(
        f"coords: {(result.geo_source == 'census').sum():,} census + "
        f"{(result.geo_source == 'zip_centroid').sum():,} zip-centroid"
    )
    return result


# ----------------------------------------------------------------- feature build
def _short_action(desc: object) -> str:
    s = str(desc or "").lower()
    if "owner" in s:
        return "Owner-initiated inspection"
    return "Routine inspection"


def build_raw() -> pd.DataFrame:
    """One row per (inspection, violation), NYC-style. Inspections with a perfect
    score have no violation rows in the feed, so we LEFT-join violations onto the
    inspection headers — a clean inspection keeps one row with a null code."""
    insp, viol = load_la_raw()
    cw = pd.read_csv(CW)
    la_theme = cw[cw.city == "LA"].set_index("native_code")["theme"].to_dict()
    la_sev = cw[cw.city == "LA"].set_index("native_code")["severity_tier"].to_dict()

    insp = insp.rename(columns={"activity_date": "date"})
    keep = [
        "serial_number",
        "date",
        "facility_id",
        "facility_name",
        "facility_address",
        "facility_city",
        "facility_state",
        "facility_zip",
        "service_description",
        "score",
        "grade",
    ]
    insp = insp[keep].copy()
    v = viol[["serial_number", "violation_code", "violation_description", "points"]].copy()
    raw = insp.merge(v, on="serial_number", how="left")

    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw["score"] = pd.to_numeric(raw["score"], errors="coerce")
    raw["theme"] = raw["violation_code"].map(la_theme)
    raw["sev"] = raw["violation_code"].map(la_sev)
    raw["is_viol"] = raw["violation_code"].notna().astype("int8")
    # "Critical" ~ a major/imminent LA violation (crosswalk tier T1/T2), the analog
    # of Chicago's priority codes / NYC's critical_flag.
    raw["is_critical"] = raw["sev"].isin(["T1", "T2"]).astype("int8")
    return raw


def build_events(raw: pd.DataFrame) -> tuple:
    keys = ["facility_id", "date"]
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
            dba_name=("facility_name", first),
            address=("facility_address", first),
            city=("facility_city", first),
            zip=("facility_zip", first),
            grade=("grade", first),
        )
        .reset_index()
    )
    ev = agg.join(theme_ct, on=keys).join(sev_ct, on=keys)
    ct_cols = list(theme_ct.columns) + list(sev_ct.columns)
    ev[ct_cols] = ev[ct_cols].fillna(0).astype("int32")
    ev = ev[ev["cur_score"].notna()].copy()
    ev = ev.sort_values(["facility_id", "date"], kind="mergesort").reset_index(drop=True)
    # FLIPPED direction: LA "bad" = graded B or C = score below 90 (higher is cleaner).
    ev["cur_is_bad"] = (ev["cur_score"] < BAD_BELOW).astype("int8")

    theme_cols = [c for c in ev.columns if c.startswith("cur_theme_")]
    sev_cols = [c for c in ev.columns if c.startswith("cur_sev_")]

    g = ev.groupby("facility_id", sort=False)
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
    ev["days_since_last_inspection"] = (ev["date"] - g["date"].shift(1)).dt.days.astype("float32")
    for c in sev_cols:
        ev[f"prior_{c}"] = (g[c].cumsum() - ev[c]).astype("int32")

    # next inspection's grade is the label
    ev["next_score"] = g["cur_score"].shift(-1).astype("float32")
    ev["next_date"] = g["date"].shift(-1)
    ev["y_next_bad"] = (ev["next_score"] < BAD_BELOW).astype("float32")

    ev["dba_name"] = ev["dba_name"].fillna("").astype(str).str.strip()
    ev["address"] = ev["address"].fillna("").astype(str).str.strip()
    ev["license_id"] = ev["facility_id"].astype(str)
    ev["inspection_date"] = ev["date"]

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
    return ev, PRIOR, CURRENT, theme_cols, sev_cols


# ------------------------------------------------------------------ LA driver labels
def la_labels(theme_cols, sev_cols) -> dict:
    sev_name = {"T1": "imminent-hazard", "T2": "major", "T3": "minor"}
    lab = {
        "cur_score": "Current inspection score: {value}/100",
        "cur_n_viol": "{value} violations at this inspection",
        "cur_n_critical": "{value} major/critical violations at this inspection",
        "cur_is_bad": {
            True: "Current inspection graded B or C (score below 90)",
            False: "Current inspection graded A (score 90 or above)",
        },
        "prior_inspections": "{value} prior inspections on record",
        "prior_bad": "{value} prior inspections graded B or C",
        "prior_n_critical": "{value} major/critical violations in prior inspections",
        "prior_mean_score": "Average past inspection score: {value}/100",
        "prior_bad_rate": "Past B/C rate: {value}",
        "prev_score": "Previous inspection score: {value}/100",
        "prev_is_bad": {True: "Previous inspection was B or C", False: "Previous inspection was A"},
        "days_since_last_inspection": "{value} days since the last inspection",
    }
    for c in sev_cols:
        t = c.replace("cur_sev_", "")
        lab[c] = f"{{value}} {sev_name.get(t, t)} violations now"
        lab[f"prior_{c}"] = f"{{value}} prior {sev_name.get(t, t)} violations"
    for c in theme_cols:
        pretty = c.replace("cur_theme_", "").replace("_", " ")
        lab[c] = f"{{value}} {pretty} violations at this inspection"
    return lab


# ------------------------------------------------------------ history (detail page)
def build_history(raw: pd.DataFrame, forecast_by_event: dict | None = None) -> dict:
    """dict keyed by facility_id -> [{date, type, result, headline, score}] newest-first.

    `result` is the LA letter grade + score ("Grade A (score 95)"); `headline` is
    the highest-point violation text at that inspection; `score` is the forecast-only
    model's calibrated probability for the inspection (drives the trend chart, DR 0011).
    """
    forecast_by_event = forecast_by_event or {}
    r = raw.copy()
    r["points"] = pd.to_numeric(r["points"], errors="coerce").fillna(0)
    r = r.sort_values(["facility_id", "date", "points"], ascending=[True, False, False])
    hist: dict[str, list[dict]] = {}
    for (fid, date), grp in r.groupby(["facility_id", "date"], sort=False):
        g0 = grp.iloc[0]
        grade = str(g0.get("grade") or "").strip()
        score = g0.get("score")
        # LA assigns a letter only down to C (70-79); an inspection scoring below 70
        # has a blank grade in the feed. Rather than render a bare "(score 59)" that
        # doesn't colour/tally, derive an honest display band from the score: A/B/C
        # for 70+, and "Below C" for sub-70 (no letter exists lower). The model still
        # treats anything below 90 as bad; the app buckets these by score.
        if grade in ("A", "B", "C"):
            result = f"Grade {grade}"
        elif pd.notna(score):
            s = float(score)
            band = "A" if s >= 90 else "B" if s >= 80 else "C" if s >= 70 else ""
            result = f"Grade {band}" if band else "Below C"
        else:
            result = ""
        if pd.notna(score):
            result = (result + f" (score {int(score)})").strip()
        desc = grp.loc[grp["violation_code"].notna(), "violation_description"].dropna()
        headline = ""
        if len(desc):
            h = str(desc.iloc[0])
            headline = h[:100] + "…" if len(h) > 100 else h
        date_str = pd.Timestamp(date).strftime("%Y-%m-%d")
        fc = forecast_by_event.get((str(fid), date_str))
        hist.setdefault(str(fid), []).append(
            {
                "date": date_str,
                "type": _short_action(g0.get("service_description")),
                "result": result,
                "headline": headline,
                "score": None if fc is None else round(float(fc), 6),
            }
        )
    for k in hist:
        hist[k].sort(key=lambda e: e["date"], reverse=True)
    return hist


# --------------------------------------------------------------------- fit + calibrate
def fit_calibrated(train, val, feats, label="y_next_bad"):
    num = Pipeline([("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())])
    pre = ColumnTransformer(
        [("num", num, feats)], sparse_threshold=0.0, verbose_feature_names_out=True
    )
    base = Pipeline(
        [
            ("preprocess", pre),
            (
                "model",
                LogisticRegression(
                    class_weight="balanced",
                    solver="liblinear",
                    max_iter=3000,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )
    base.fit(train[feats], train[label].astype(int))
    cal = CalibratedClassifierCV(FrozenEstimator(base), method="sigmoid")
    cal.fit(val[feats], val[label].astype(int))
    return base, cal


def last_k_trend(events_scored: pd.DataFrame, anchors: pd.DataFrame, k: int) -> pd.Series:
    """OLS slope of the forecast risk over each facility's last K scored inspections."""
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
    raw = build_raw()
    ev, PRIOR, CURRENT, theme_cols, sev_cols = build_events(raw)
    FEATS_M1 = PRIOR + CURRENT
    labels = la_labels(theme_cols, sev_cols)
    print(f"scored events {len(ev):,} | facilities {ev.facility_id.nunique():,}")

    anch = ev[ev["next_score"].notna() & (ev["inspection_date"] >= LA_TRAIN_START)].copy()
    sp = temporal_split(anch, date_col="inspection_date", train_end=TRAIN_END, val_end=VAL_END)
    print(
        f"train {len(sp.train):,} | val {len(sp.val):,} | test {len(sp.test):,} "
        f"| test base {sp.test.y_next_bad.mean():.3f}"
    )

    base1, cal1 = fit_calibrated(sp.train, sp.val, FEATS_M1)
    base2, cal2 = fit_calibrated(sp.train, sp.val, PRIOR)  # forecast-only for trend
    y_test = sp.test["y_next_bad"].astype(int).values
    p_test = cal1.predict_proba(sp.test[FEATS_M1])[:, 1]
    test_metrics = evaluate(y_test, p_test).to_dict()
    print(
        "Model 1 test:", {k: test_metrics[k] for k in ("pr_auc", "roc_auc", "precision_at_10pct")}
    )

    # score EVERY facility's latest inspection (serving anchor)
    ev["risk_score"] = cal1.predict_proba(ev[FEATS_M1])[:, 1]
    ev["forecast_risk"] = cal2.predict_proba(ev[PRIOR])[:, 1]
    latest = ev.sort_values("inspection_date").drop_duplicates("license_id", keep="last").copy()
    print(f"serving rows (latest per facility): {len(latest):,}")

    # coordinates (LA feed has none) — geocode + cache + zip-centroid fallback
    fac = latest[["facility_id", "address", "city", "zip"]].copy()
    fac["state"] = "CA"
    fac = fac.rename(columns={"city": "city", "zip": "zip"})
    coords = load_facility_coords(fac)
    latest = latest.merge(
        coords.rename(columns={"facility_id": "license_id"})[["license_id", "lat", "lon"]],
        on="license_id",
        how="left",
    )

    contribs = linear_contributions(cal1, latest[FEATS_M1], original_features=FEATS_M1)
    drivers = []
    for i, row in latest.iterrows():
        ds = top_drivers_for_row(row[FEATS_M1], contribs.loc[i], k=5, labels=labels)
        drivers.append([d.to_dict() for d in ds])
    latest["top_drivers"] = drivers

    latest["trend_slope"] = last_k_trend(
        ev[["license_id", "inspection_date", "forecast_risk"]], latest, TREND_K
    )
    latest["as_of_date"] = latest["inspection_date"]

    q = latest["risk_score"].quantile([0.4, 0.85, 0.98]).round(4).tolist()
    print(
        f"LA risk_score dist: p50={latest.risk_score.median():.3f} "
        f"p90={latest.risk_score.quantile(0.9):.3f} max={latest.risk_score.max():.3f}"
    )
    print(f"LA tier thresholds (p40/p85/p98): {q}")
    thr = [(q[0], "Low"), (q[1], "Moderate"), (q[2], "Elevated"), (1.01, "High")]

    def tier(s):
        for t, name in thr:
            if s < t:
                return name
        return "High"

    latest["risk_tier"] = latest["risk_score"].apply(tier)
    print("tier counts:", latest["risk_tier"].value_counts().to_dict())

    calibration = {
        "a": float(cal1.calibrated_classifiers_[0].calibrators[0].a_),
        "b": float(cal1.calibrated_classifiers_[0].calibrators[0].b_),
        "intercept": float(base1.named_steps["model"].intercept_[0]),
    }

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
    )
    print(f"\nWrote {OUT / 'scores.json'}  ({len(out):,} facilities)")

    forecast_by_event = {
        (r.license_id, pd.Timestamp(r.inspection_date).strftime("%Y-%m-%d")): r.forecast_risk
        for r in ev.itertuples(index=False)
    }
    hist = build_history(raw, forecast_by_event)
    (OUT / "inspection_history.json").write_text(json.dumps(hist, separators=(",", ":")))
    print(f"Wrote inspection_history.json ({len(hist):,} facilities)")

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

    op = (
        operating_point_table(y_test, p_test)
        .rename(columns={"inspect_top_frac": "frac"})
        .to_dict("records")
    )
    shares = (out["risk_tier"].value_counts(normalize=True)).to_dict()
    methodology = {
        "generated_at": datetime.now(UTC).isoformat(),
        "model_version": MODEL_VERSION,
        "city": "la",
        "data_source": "LA County Environmental Health Restaurant and Market Inspections (ArcGIS)",
        "label": "Probability the establishment's NEXT inspection is graded B or C (score below 90)",
        "train_window": f"{LA_TRAIN_START} onward (LA County's fresh feed is post-COVID)",
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
            "LA is a coverage feature. Its grades run the opposite way to Chicago and "
            "NYC (A = 90-100, higher is cleaner), and the B/C base rate is low (~5%). "
            "Facility coordinates are geocoded from the address (the feed carries none)."
        ),
        "risk_tiers": [
            {"label": "Low", "min": 0.0, "max": q[0], "share": round(shares.get("Low", 0), 4)},
            {
                "label": "Moderate",
                "min": q[0],
                "max": q[1],
                "share": round(shares.get("Moderate", 0), 4),
            },
            {
                "label": "Elevated",
                "min": q[1],
                "max": q[2],
                "share": round(shares.get("Elevated", 0), 4),
            },
            {"label": "High", "min": q[2], "max": None, "share": round(shares.get("High", 0), 4)},
        ],
        "operating_points": op,
    }
    (OUT / "methodology.json").write_text(json.dumps(methodology, indent=2))
    print("Wrote methodology.json")

    (OUT / "_la_build_meta.json").write_text(
        json.dumps(
            {
                "model_version": MODEL_VERSION,
                "tier_thresholds": q,
                "train_start": LA_TRAIN_START,
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
