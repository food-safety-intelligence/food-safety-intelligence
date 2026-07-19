"""NYC / LA feature-addition experiments — close the gap to Chicago's feature set.

NYC and LA ship a leaner feature set than Chicago (`PRIOR + CURRENT`): they lack
the time-windowed (recent) priors, calendar/seasonality, recency-to-last-bad,
trend, tenure, and visit-type families that carried Chicago. This harness adds
each MISSING family leak-free and A/Bs it under **expanding-window CV** (same
gate discipline as the Chicago HPO work) so a family is kept only if it clears
the both-metrics gate — not on a single split.

It reuses each city's OWN `build_events` + `fit_xgb_platt` (the served Model-1
config), so the only thing that changes between the control and a candidate is
the feature list. PR-AUC / precision@10% are rank metrics, so per fold we score
the raw XGB margin (the Platt step in fit_xgb_platt doesn't affect ranking).

Deliberately NOT added: Chicago-style keyword text flags (the cross-city ablation
found them flat-to-negative on NYC/LA — the crosswalk theme/severity is their
analog) and inspector id / facility-type / geography (fairness/legal lines).

Run:  PYTHONPATH=src FOODSAFETY_DATA_DIR=<data> python scripts/run_city_feature_experiments.py [nyc|la|all]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from foodsafety.models.evaluate import precision_at_k
from foodsafety.utils.time import expanding_year_folds

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import build_la_scores as la  # noqa: E402
import build_nyc_scores as nyc  # noqa: E402

OUT_DIR = REPO / "reports" / "metrics"


# --------------------------------------------------------------------------- #
# Leak-free candidate feature families (computed on the full event history)
# --------------------------------------------------------------------------- #
def add_families(
    ev: pd.DataFrame, raw: pd.DataFrame, city: str, estab: str
) -> dict[str, list[str]]:
    """Add every candidate family to ``ev`` in place; return {family: [cols]}.

    ``ev`` is already sorted by (estab, inspection_date) with a RangeIndex (both
    build_events do this), so a datetime-indexed groupby-rolling lands back in ev
    row order. Every feature uses only PAST events (shift / cumsum-minus-self /
    rolling-minus-current), so nothing peeks at the current or future outcome.
    """
    fam: dict[str, list[str]] = {}
    dcol = "inspection_date"
    ev["_one"] = 1.0

    # 1) Time-windowed (recent) priors — 365-day rolling, excluding the current row.
    tmp = ev[[estab, dcol, "cur_is_bad", "_one"]].set_index(dcol)
    g = tmp.groupby(estab, sort=False)
    insp365 = g["_one"].rolling("365D").sum().to_numpy()
    bad365 = g["cur_is_bad"].rolling("365D").sum().to_numpy()
    ev["prior_insp_365d"] = (insp365 - 1.0).astype("float32")
    ev["prior_bad_365d"] = (bad365 - ev["cur_is_bad"].to_numpy()).astype("float32")
    ev["prior_bad_rate_365d"] = (
        ev["prior_bad_365d"] / ev["prior_insp_365d"].replace(0, np.nan)
    ).astype("float32")
    fam["recent365"] = ["prior_insp_365d", "prior_bad_365d", "prior_bad_rate_365d"]

    # 2) Recency to last BAD event (Chicago has days_since_last_fail; they only
    #    have days_since_last_inspection).
    bad_date = ev[dcol].where(ev["cur_is_bad"] == 1)
    last_bad = bad_date.groupby(ev[estab]).ffill().groupby(ev[estab]).shift(1)
    ev["days_since_last_bad"] = (ev[dcol] - last_bad).dt.days.astype("float32")
    fam["recency_bad"] = ["days_since_last_bad"]

    # 3) Trend — recent (last up-to-3 visits) bad-rate minus the lifetime rate.
    last3 = ev.groupby(estab)["cur_is_bad"].transform(
        lambda s: s.shift(1).rolling(3, min_periods=1).mean()
    )
    ev["bad_rate_recent3"] = last3.astype("float32")
    ev["bad_rate_trend"] = (last3 - ev["prior_bad_rate"]).astype("float32")
    fam["trend"] = ["bad_rate_recent3", "bad_rate_trend"]

    # 4) Calendar / seasonality.
    ev["insp_month"] = ev[dcol].dt.month.astype("int16")
    ev["insp_quarter"] = ev[dcol].dt.quarter.astype("int16")
    fam["calendar"] = ["insp_month", "insp_quarter"]

    # 5) Tenure — days since the establishment's first inspection on record.
    first = ev.groupby(estab)[dcol].transform("min")
    ev["tenure_days"] = (ev[dcol] - first).dt.days.astype("float32")
    fam["tenure"] = ["tenure_days"]

    # 6) Visit type — city-specific, from the raw feed (observed at as-of).
    if city == "nyc":
        # `action` marks DOHMH enforcement: closed / re-closed vs a normal cite.
        act = (
            raw.groupby(["camis", "inspection_date"])["action"]
            .first()
            .rename("action")
            .reset_index()
        )
        act["cur_closed"] = (
            act["action"]
            .astype("string")
            .str.contains("closed", case=False, na=False)
            .astype("int8")
        )
        ev = ev.merge(
            act[["camis", "inspection_date", "cur_closed"]],
            on=["camis", "inspection_date"],
            how="left",
        )
        ev["cur_closed"] = ev["cur_closed"].fillna(0).astype("int8")
        gc = ev.groupby(estab)["cur_closed"]
        ev["prior_closures"] = (gc.cumsum() - ev["cur_closed"]).astype("int32")
        fam["visit_type"] = ["cur_closed", "prior_closures"]
    elif city == "la":
        # `service_description` = ROUTINE vs OWNER INITIATED (raw date col is "date").
        sd = raw.groupby(["facility_id", "date"])["service_description"].first()
        sd = sd.rename("svc").reset_index().rename(columns={"date": "inspection_date"})
        sd["inspection_date"] = pd.to_datetime(sd["inspection_date"], errors="coerce")
        sd["cur_owner_initiated"] = (
            sd["svc"].astype("string").str.contains("OWNER", case=False, na=False).astype("int8")
        )
        ev = ev.merge(
            sd[["facility_id", "inspection_date", "cur_owner_initiated"]],
            on=["facility_id", "inspection_date"],
            how="left",
        )
        ev["cur_owner_initiated"] = ev["cur_owner_initiated"].fillna(0).astype("int8")
        go = ev.groupby(estab)["cur_owner_initiated"]
        ev["prior_owner_initiated"] = (go.cumsum() - ev["cur_owner_initiated"]).astype("int32")
        fam["visit_type"] = ["cur_owner_initiated", "prior_owner_initiated"]

    ev.drop(columns=["_one"], inplace=True, errors="ignore")
    # the visit_type merge returns a NEW frame, so hand ev back to the caller
    return fam, ev


# --------------------------------------------------------------------------- #
# City loading
# --------------------------------------------------------------------------- #
def load_city(city: str):
    if city == "nyc":
        ev, PRIOR, CURRENT, theme_cols, sev_cols, raw = nyc.build_events()
        return dict(
            ev=ev,
            PRIOR=PRIOR,
            CURRENT=CURRENT,
            raw=raw,
            label="y_next_bc",
            estab="camis",
            train_start=nyc.NYC_TRAIN_START,
            train_end=nyc.TRAIN_END,
            val_end=nyc.VAL_END,
            fit=nyc.fit_xgb_platt,
        )
    if city == "la":
        raw = la.build_raw()
        ev, PRIOR, CURRENT, theme_cols, sev_cols = la.build_events(raw)
        return dict(
            ev=ev,
            PRIOR=PRIOR,
            CURRENT=CURRENT,
            raw=raw,
            label="y_next_bad",
            estab="facility_id",
            train_start=la.LA_TRAIN_START,
            train_end=la.TRAIN_END,
            val_end=la.VAL_END,
            fit=la.fit_xgb_platt,
        )
    raise ValueError(city)


def cv_score(cv_df, feats, folds, label, fit_fn) -> dict:
    pr, p10 = [], []
    y = cv_df[label].astype(int).to_numpy()
    for tr, va in folds:
        tr_df, va_df = cv_df.iloc[tr], cv_df.iloc[va]
        clf, _, _ = fit_fn(tr_df, va_df, feats, label=label)  # Platt on va is rank-irrelevant
        margin = clf.predict(va_df[feats], output_margin=True)
        pr.append(float(average_precision_score(y[va], margin)))
        p10.append(float(precision_at_k(y[va], margin, 0.10)))
    return {
        "pr": float(np.mean(pr)),
        "p10": float(np.mean(p10)),
        "pr_folds": [round(x, 4) for x in pr],
        "p10_folds": [round(x, 4) for x in p10],
    }


def run_city(city: str) -> dict:
    c = load_city(city)
    ev, label, estab = c["ev"], c["label"], c["estab"]
    fam, ev = add_families(ev, c["raw"], city, estab)
    base = list(c["PRIOR"]) + list(c["CURRENT"])

    anch = ev[ev["next_score"].notna() & (ev["inspection_date"] >= c["train_start"])].copy()
    cv_df = anch[anch["inspection_date"] < c["val_end"]].reset_index(drop=True)
    folds = expanding_year_folds(cv_df)
    yrs = [
        int(pd.to_datetime(cv_df["inspection_date"].iloc[va]).dt.year.mode().iloc[0])
        for _, va in folds
    ]
    print(
        f"\n===== {city.upper()} =====  base feats={len(base)}  CV n={len(cv_df):,}  folds(val yrs)={yrs}"
    )

    t0 = time.time()
    b = cv_score(cv_df, base, folds, label, c["fit"])
    print(f"BASELINE  CV pr={b['pr']:.4f} p10={b['p10']:.4f}  ({time.time() - t0:.0f}s)")
    print(f"  pr folds {b['pr_folds']}  p10 folds {b['p10_folds']}")

    results = []
    for name, cols in fam.items():
        cand = base + cols
        s = cv_score(cv_df, cand, folds, label, c["fit"])
        dpr, dp10 = s["pr"] - b["pr"], s["p10"] - b["p10"]
        gate = dpr >= 0 and dp10 >= 0
        results.append(
            {
                "family": name,
                "cols": cols,
                "d_pr": round(dpr, 5),
                "d_p10": round(dp10, 5),
                "cv_pr": round(s["pr"], 5),
                "cv_p10": round(s["p10"], 5),
                "both_gate": bool(gate),
                "pr_folds": s["pr_folds"],
                "p10_folds": s["p10_folds"],
            }
        )
        print(f"  +{name:14s} dPR={dpr:+.4f} dP10={dp10:+.4f}  {'PASS' if gate else ''}  {cols}")

    # combined: all gate-passing families together
    winners = [r for r in results if r["both_gate"]]
    combo_cols = [col for r in winners for col in r["cols"]]
    combo = None
    if combo_cols:
        s = cv_score(cv_df, base + combo_cols, folds, label, c["fit"])
        combo = {
            "cols": combo_cols,
            "cv_pr": round(s["pr"], 5),
            "cv_p10": round(s["p10"], 5),
            "d_pr": round(s["pr"] - b["pr"], 5),
            "d_p10": round(s["p10"] - b["p10"], 5),
        }
        print(
            f"  COMBINED all-passers dPR={combo['d_pr']:+.4f} dP10={combo['d_p10']:+.4f}  ({len(combo_cols)} cols)"
        )

    out = {
        "city": city,
        "baseline": {
            "n_feat": len(base),
            "cv_pr": round(b["pr"], 5),
            "cv_p10": round(b["p10"], 5),
            "pr_folds": b["pr_folds"],
            "p10_folds": b["p10_folds"],
        },
        "families": results,
        "combined": combo,
        "fold_val_years": yrs,
    }
    (OUT_DIR / city).mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / city / f"{city}_feature_experiments.json"
    p.write_text(json.dumps(out, indent=2))
    print(f"  wrote {p}")
    return out


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    cities = ["nyc", "la"] if which == "all" else [which]
    for ct in cities:
        run_city(ct)
