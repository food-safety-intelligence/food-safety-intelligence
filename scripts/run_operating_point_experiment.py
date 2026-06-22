"""Operating-point + early-warning worklist prototype.

Improvement here is not a higher PR-AUC (the model is at an information ceiling) —
it is making the WORKLIST better for how inspectors actually use it. Two moves,
both decision-layers on top of the existing v36 scores (no model change, no change
to the scores.parquet / scores.json contract — exposing this in the app is a
separate, owner-signed step):

1. **Stakes weighting (operating point).** The city inspects a fixed number of
   places per cycle (~1,529 inspections/month in the recent feed). At that
   capacity, ranking by raw risk treats a daycare/hospital/school failure the same
   as a corner store. Re-rank by ``risk x stakes`` where stakes = a multiplier for
   vulnerable-population facilities (daycare, school, children's, long-term-care,
   hospital, shelter). Measure, at a fixed capacity K: total events caught,
   events caught AT vulnerable facilities, and vulnerable-event coverage.

2. **Early-warning watch list (segmentation).** The raw top-K worklist is ~96%
   places that just failed (a re-inspection cycle already scheduled by mandate),
   so clean-but-rising places never appear. Reserve a slice of capacity for a
   WATCH list: the highest-risk places whose last inspection PASSED. The main model
   already ranks clean places well (top-decile lift ~3.8x over the clean base) — we
   just choose to show them. Measure how many clean rising-risk places this catches
   that the pure top-K misses, and the cost in total events.

Defaults below are a starting POLICY, not a fixed truth — tune ``VULN_MULTIPLIER``
and ``WATCH_FRAC`` with the PM / label owner.

Honest split: train < 2024-07 / val < 2025-07 / test >= 2025-07; train/val drop
right_truncated; the held-out test is the candidate pool to triage.

Run:
  FOODSAFETY_DATA_DIR=/abs/path/to/data PYTHONPATH=src \
    uv run python scripts/run_operating_point_experiment.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from foodsafety.config import PROCESSED_DIR
from foodsafety.features.license_features import normalize_facility_type
from foodsafety.models.baseline import LABEL_COL
from foodsafety.models.xgb import (
    build_xgb_estimator,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    prepare_xgb_features,
)
from foodsafety.utils.time import temporal_split

REPO_ROOT = Path(__file__).resolve().parent.parent
FEATURES_PATH = PROCESSED_DIR / "features.parquet"
METRICS_DIR = REPO_ROOT / "reports" / "metrics"

TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"

VULNERABLE_GROUPS = {
    "Children's Services Facility",
    "Daycare",
    "School",
    "Long Term Care",
    "Hospital",
    "Shelter",
}
# POLICY KNOBS (tune with PM / label owner) ---------------------------------
VULN_MULTIPLIER = 3.0  # stakes weight for a vulnerable-population facility
WATCH_FRAC = 0.20  # share of worklist capacity reserved for the early-warning list
K_FRACS = (0.05, 0.10, 0.20)  # operating points to report


def _score_main(train, val, test):
    Xtr = prepare_xgb_features(train)
    cat = extract_categorical_dtypes(Xtr)
    Xva = prepare_xgb_features(val, categorical_dtypes=cat)
    Xte = prepare_xgb_features(test, categorical_dtypes=cat)
    clf = build_xgb_estimator(scale_pos_weight=compute_scale_pos_weight(train[LABEL_COL]))
    clf.fit(Xtr, train[LABEL_COL], eval_set=[(Xva, val[LABEL_COL])], verbose=False)
    return clf.predict_proba(Xte)[:, 1]


def _worklist(rank_score, k, y, vuln):
    """Top-k by ``rank_score``; report total + vulnerable-facility event capture."""
    order = np.argsort(-rank_score, kind="stable")[:k]
    caught = int(y[order].sum())
    vuln_caught = int((y[order] & vuln[order]).sum())
    total_vuln = int((y & vuln).sum())
    return {
        "k": int(k),
        "events_caught": caught,
        "precision": round(caught / k, 4),
        "vuln_events_caught": vuln_caught,
        "vuln_event_recall": round(vuln_caught / total_vuln, 4) if total_vuln else None,
    }


def main() -> None:
    df = pd.read_parquet(FEATURES_PATH)
    df["inspection_date"] = pd.to_datetime(df["inspection_date"])
    split = temporal_split(df, train_end=TRAIN_END, val_end=VAL_END)
    train = split.train[~split.train["right_truncated"]].copy()
    val = split.val[~split.val["right_truncated"]].copy()
    test = split.test.reset_index(drop=True).copy()

    y = test[LABEL_COL].to_numpy().astype(int)
    was_fail = test["was_fail"].to_numpy().astype(bool)
    groups = test["facility_type"].map(normalize_facility_type)
    vuln = groups.isin(VULNERABLE_GROUPS).to_numpy()
    base = float(y.mean())
    n = len(test)
    s = _score_main(train, val, test)
    stakes = np.where(vuln, VULN_MULTIPLIER, 1.0)
    weighted = s * stakes
    print(
        f"test pool n={n:,}  base {base:.3f}  vulnerable-facility rows {int(vuln.sum()):,} "
        f"({vuln.mean():.1%}); their events {int((y & vuln).sum()):,}"
    )

    # --- 1. Stakes weighting at each operating point ---------------------------
    operating = {}
    print("\n(1) STAKES WEIGHTING — unweighted vs risk x stakes, per capacity K:")
    for kf in K_FRACS:
        k = max(1, int(np.ceil(n * kf)))
        unw = _worklist(s, k, y, vuln)
        wtd = _worklist(weighted, k, y, vuln)
        rand_events = round(base * k, 1)
        operating[f"top_{int(kf * 100)}pct"] = {
            "k": k,
            "random_events": rand_events,
            "unweighted": unw,
            "stakes_weighted": wtd,
        }
        print(
            f"  K={k:>4} (top {int(kf * 100)}%):  events {unw['events_caught']}→{wtd['events_caught']} "
            f"(random ~{rand_events})   vulnerable events {unw['vuln_events_caught']}→{wtd['vuln_events_caught']} "
            f"(recall {unw['vuln_event_recall']}→{wtd['vuln_event_recall']})"
        )

    # --- 2. Early-warning watch list at the 10% operating point ----------------
    k = max(1, int(np.ceil(n * 0.10)))
    clean = ~was_fail
    pure = _worklist(s, k, y, vuln)
    pure_order = np.argsort(-s, kind="stable")[:k]
    pure_clean_events = int((y[pure_order] & clean[pure_order]).sum())

    # Reserve WATCH_FRAC of K for the highest-risk CLEAN (last-inspection-passed)
    # places, filling the rest from the overall ranking.
    k_watch = int(np.floor(k * WATCH_FRAC))
    k_main = k - k_watch
    main_order = np.argsort(-s, kind="stable")[:k_main]
    main_set = set(main_order.tolist())
    clean_ranked = [i for i in np.argsort(-s, kind="stable") if clean[i] and i not in main_set]
    watch_order = np.array(clean_ranked[:k_watch], dtype=int)
    reserved = np.concatenate([main_order, watch_order])
    reserved_events = int(y[reserved].sum())
    reserved_clean_events = int((y[reserved] & clean[reserved]).sum())
    watch_only_events = int(y[watch_order].sum())

    early_warning = {
        "k": k,
        "pure_topk": {
            "events_caught": pure["events_caught"],
            "clean_events_caught": pure_clean_events,
            "clean_places_shown": int(clean[pure_order].sum()),
        },
        "reserved": {
            "watch_slots": int(k_watch),
            "events_caught": reserved_events,
            "clean_events_caught": reserved_clean_events,
            "watch_slot_events": watch_only_events,
            "watch_slot_fail_rate": round(watch_only_events / k_watch, 4) if k_watch else None,
        },
    }
    print(f"\n(2) EARLY-WARNING watch list at top 10% (K={k}, reserving {k_watch} watch slots):")
    print(
        f"  pure top-K:  {pure['events_caught']} events, of which {pure_clean_events} at clean places "
        f"({int(clean[pure_order].sum())} clean places shown of {k})"
    )
    print(
        f"  reserved:    {reserved_events} events, of which {reserved_clean_events} at clean places; "
        f"the {k_watch} watch slots catch {watch_only_events} "
        f"(fail-rate {early_warning['reserved']['watch_slot_fail_rate']} vs base {base:.3f})"
    )
    print(
        f"  → trade: {pure['events_caught'] - reserved_events} fewer total events to surface "
        f"{reserved_clean_events - pure_clean_events} more clean rising-risk places."
    )

    out = {
        "experiment": "operating_point_and_early_warning_worklist",
        "date": date.today().isoformat(),
        "config": {
            "estimator": "xgboost v36 (main model scores)",
            "train_end": TRAIN_END,
            "val_end": VAL_END,
            "n_test_pool": n,
            "base_rate": round(base, 4),
            "policy": {
                "vuln_multiplier": VULN_MULTIPLIER,
                "watch_frac": WATCH_FRAC,
                "vulnerable_groups": sorted(VULNERABLE_GROUPS),
            },
            "context_city_capacity_per_month": 1529,
        },
        "stakes_weighting": operating,
        "early_warning": early_warning,
        "note": (
            "Decision-layer prototype on existing v36 scores — no model change, no "
            "scores.parquet/json contract change. Exposing the watch list + stakes "
            "ranking in the app is a separate owner-signed step (Jun/Aurelia) needing "
            "a /verify pass. Policy knobs (vuln_multiplier, watch_frac) are defaults "
            "to tune with the PM / label owner."
        ),
    }
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = METRICS_DIR / f"operating_point_experiment_{date.today().isoformat()}.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
