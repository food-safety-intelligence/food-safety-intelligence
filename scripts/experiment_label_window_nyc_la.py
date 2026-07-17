"""Feasibility experiment: does Chicago's day-window forward label extend to
NYC/LA?

Chicago's 2026-07-16 label-window study (`experiment_label_window.py`) found
short-term risk structurally easier to predict than the served 180d window.
That study is Chicago-only: NYC/LA's served label (`y_next_bc`/`y_next_bad`)
is event-anchored ("is this facility's literal next inspection, whenever it
happens, graded B/C"), with no day-count window to vary.

This experiment builds a Chicago-style day-window label for NYC/LA — reusing
`foodsafety.data.labels.compute_forward_window_label` (promoted from Chicago's
private `_compute_forward_labels`, generalized with a `flag_col` param) — and
checks whether it's viable, before any decision to redesign the served label.

**Cadence caveat that shapes the window choice.** NYC/LA facilities are
reinspected far less often than Chicago's (median days between consecutive
inspections at the same facility: Chicago 232d, 10th pct 7d [complaint-driven
re-inspections happen fast]; NYC 320d, 10th pct 39d; LA 347d, 10th pct 98d).
Chicago's 30/60/90d windows work because a real share of facilities get
reinspected within days/weeks; NYC/LA mostly don't, so short windows there
will be dominated by "no inspection happened yet," not a risk signal. Windows
here are lengthened to 90/180/365d accordingly. The data's own recency also
bounds window size: NYC's raw pull ends 2026-07-14 and LA's ends 2026-06-30,
so windows beyond ~365d would right-truncate most or all of the test set
(anchor + window > dataset max) given each city's served VAL_END.

Reuses each city's own production code so numbers are directly comparable to
what's served: `build_events()`, `fit_xgb_platt`, `xgb_proba` from
`build_nyc_scores.py`/`build_la_scores.py`, and `fit_logreg_sigmoid` from
`run_city_ablations.py`. Fits + evaluates only — never touches committed app
JSON or the served label.

Run:
    PYTHONPATH=src uv run python scripts/experiment_label_window_nyc_la.py [nyc|la|all]
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from foodsafety.data.labels import compute_forward_window_label
from foodsafety.models.evaluate import evaluate
from foodsafety.utils.time import temporal_split

REPO = Path(__file__).resolve().parent.parent
# Import the city producers + the ablation runner's LogReg comparator as
# modules so this reuses the exact feature-build + fit code that ships to
# production, rather than re-deriving it (module import has no side effects;
# the raw pull only happens when build_events/build_raw are called).
sys.path.insert(0, str(REPO / "scripts"))
import build_la_scores as la  # noqa: E402
import build_nyc_scores as nyc  # noqa: E402
from run_city_ablations import fit_logreg_sigmoid  # noqa: E402

METRICS_DIR = REPO / "reports" / "metrics" / "experiments"
WINDOWS_DAYS = [90, 180, 365]


def _fit_and_eval(train, val, test, feats, label, fit_xgb, xgb_proba) -> dict:
    y_test = test[label].astype(int).to_numpy()

    xgb, coef, inter = fit_xgb(train, val, feats, label=label)
    p_xgb = xgb_proba(xgb, coef, inter, test[feats])

    cal = fit_logreg_sigmoid(train, val, feats, label)
    p_lr = cal.predict_proba(test[feats])[:, 1]

    return {
        "xgb": evaluate(y_test, p_xgb).to_dict(),
        "logreg": evaluate(y_test, p_lr).to_dict(),
        "n_train": len(train),
        "n_val": len(val),
        "n_test": len(test),
        "base_rate": round(float(y_test.mean()), 4),
    }


def _print_row(tag: str, m: dict) -> None:
    print(f"  [{tag}] base={m['base_rate']:.4f} n_train={m['n_train']:,} n_test={m['n_test']:,}")
    for name in ("xgb", "logreg"):
        r = m[name]
        pr_per_prev = r["pr_auc"] / m["base_rate"] if m["base_rate"] > 0 else float("nan")
        print(
            f"    {name:6s} PR-AUC={r['pr_auc']:.4f} (PR/prev={pr_per_prev:.3f}) "
            f"ROC-AUC={r['roc_auc']:.4f} P@10={r['precision_at_10pct']:.4f} "
            f"lift@10={r['top_decile_lift']:.3f}"
        )
        m[name]["pr_auc_per_prevalence"] = round(pr_per_prev, 4)


def run_city(city: str) -> dict:
    if city == "nyc":
        ev, PRIOR, CURRENT, _theme, _sev, _raw = nyc.build_events()
        train_start, train_end, val_end = nyc.NYC_TRAIN_START, nyc.TRAIN_END, nyc.VAL_END
        served_label = "y_next_bc"
        fit_xgb, xgb_proba = nyc.fit_xgb_platt, nyc.xgb_proba
    elif city == "la":
        raw = la.build_raw()
        ev, PRIOR, CURRENT, _theme, _sev = la.build_events(raw)
        train_start, train_end, val_end = la.LA_TRAIN_START, la.TRAIN_END, la.VAL_END
        served_label = "y_next_bad"
        fit_xgb, xgb_proba = la.fit_xgb_platt, la.xgb_proba
    else:
        raise ValueError(f"unknown city {city!r}")

    feats = PRIOR + CURRENT
    dataset_max = ev["inspection_date"].max()
    print(f"\n[{city}] scored events {len(ev):,} | dataset max date {dataset_max.date()}")

    results: dict = {}

    # ---- reference row: the currently-served event-anchored label, same
    # features + models, so the day-window variants have a same-city baseline.
    served_anch = ev[ev["next_score"].notna() & (ev["inspection_date"] >= train_start)].copy()
    sp = temporal_split(
        served_anch, date_col="inspection_date", train_end=train_end, val_end=val_end
    )
    m = _fit_and_eval(sp.train, sp.val, sp.test, feats, served_label, fit_xgb, xgb_proba)
    results["served_event_anchored"] = m
    _print_row(f"served:{served_label}", m)

    # ---- day-window variants ----
    for w in WINDOWS_DAYS:
        label_col = f"y_bad_within_{w}d"
        ev[label_col] = compute_forward_window_label(ev, window_days=w, flag_col="cur_is_bad")
        rt_col = f"right_truncated_{w}d"
        ev[rt_col] = (ev["inspection_date"] + pd.Timedelta(days=w)) > dataset_max

        anch = ev[ev["inspection_date"] >= train_start].copy()
        sp = temporal_split(anch, date_col="inspection_date", train_end=train_end, val_end=val_end)
        # Drop right-truncated rows from train/val (their window runs past the
        # data, so the label is under-counted); test stays full for an honest read.
        train = sp.train[~sp.train[rt_col]].copy()
        val = sp.val[~sp.val[rt_col]].copy()
        test = sp.test.copy()

        m = _fit_and_eval(train, val, test, feats, label_col, fit_xgb, xgb_proba)
        m["test_right_truncated_share"] = round(float(test[rt_col].mean()), 4)
        results[str(w)] = m
        _print_row(f"{w}d", m)
        print(f"    right_truncated(test)={m['test_right_truncated_share']:.3f}")

    return results


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    cities = ["nyc", "la"] if which == "all" else [which]

    all_results = {city: run_city(city) for city in cities}

    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = METRICS_DIR / f"label_window_study_nyc_la_{date.today().isoformat()}.json"
    out_path.write_text(
        json.dumps(
            {
                "experiment": "label_window_feasibility_nyc_la",
                "date": date.today().isoformat(),
                "windows_days": WINDOWS_DAYS,
                "results": all_results,
            },
            indent=2,
        )
    )
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
