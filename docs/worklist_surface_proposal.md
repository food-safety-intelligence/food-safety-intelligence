# Proposal — inspector worklist surface (stakes weighting + early-warning watch list)

- **Author**: Bella · **Date**: 2026-06-22 · **Status**: proposal, needs owner sign-off
- **For**: Jun (PM), Aurelia (label / app), Arun, Deepak
- **Evidence**: `docs/experiments.md` (2026-06-22 rows) +
  `reports/metrics/forecast_surface_experiment_2026-06-22.json` +
  `reports/metrics/operating_point_experiment_2026-06-22.json`. Scripts:
  `scripts/run_forecast_surface_experiment.py`, `scripts/run_operating_point_experiment.py`.

## Why

The model's accuracy is at an information ceiling (a sweep of feature, label, and
objective experiments all came back flat — see `experiments.md`). But the **worklist**
— what we hand an inspector — can still get materially better without any model change,
because two things are wrong with ranking purely by `risk_score`:

1. **Vulnerable places are under-served at capacity.** Ranking by raw risk treats a
   daycare/hospital/school failure the same as a corner store. At the top 5% of the
   worklist, that catches only **23%** of the events at vulnerable-population facilities.
2. **The list is ~96% places that just failed** — which are already on a mandated
   re-inspection clock. A clean place quietly drifting toward failure never appears
   (only 48 of ~1,382 top-decile slots are clean places).

## What we measured (held-out test, n=13,812)

- **Stakes weighting** — rank by `risk × stakes`, where `stakes = 3×` for
  vulnerable-population facilities: vulnerable-facility event recall **0.23 → 0.84** at
  the top 5% (0.51 → 0.87 at top 10%), for a modest cost in total events caught.
- **Early-warning watch list** — reserve 20% of capacity for the highest-risk places
  whose **last inspection passed**: surfaces **276 clean places** (the watch slots hit
  at **22% = 2.5× the base rate**) for just **13 fewer total events** (515 → 502).
  Real catches it would have surfaced: HENRIETTA, Avondale Coffee Club, 4 Seasons —
  all passed last time, then failed.
- We also checked: **do not** drop the current-outcome feature or train a separate
  forecast model — the existing model already ranks clean places best (clean-slice
  lift 3.81 vs a forecast model's 3.11). The watch list is **segmentation of the
  existing scores**, not a new model.

## Proposal

Ship the worklist as **`risk × stakes`, segmented into two lists**:

- **Active risk** — `last_inspection_passed == false`. Recently failed; usually already
  scheduled for re-inspection. Confirms known-bad places.
- **Early-warning watch** — `last_inspection_passed == true`, ranked by `stakes_score`.
  Proactive: clean places trending toward trouble.

No model change. No live inference. Same batch-score-to-JSON contract.

## Schema change (additive, backward-compatible)

Three new columns on `scores.parquet` → `scores.json` (full detail in
`interface_contracts.md` § 3, marked PROPOSED). Additive only — an app that ignores
unknown fields is unaffected:

| Column | dtype | Meaning |
|---|---|---|
| `last_inspection_passed` | `bool` | anchor inspection passed (`was_fail == 0`) → Active vs Watch |
| `stakes_weight` | `float64` | vulnerability multiplier (1.0, or 3.0 for vulnerable facility types) |
| `stakes_score` | `float64` | `risk_score × stakes_weight` — the worklist sort key |

Producer change is ~10 lines in `predict_batch.py` (it already has `was_fail` and
`facility_type` on each scored row): set `last_inspection_passed = was_fail == 0`,
`stakes_weight` from `normalize_facility_type(facility_type) in VULNERABLE_GROUPS`,
`stakes_score = risk_score * stakes_weight`; pass through in `parquet_to_json.py`.

## Policy knobs to decide (PM / label owner)

- `vuln_multiplier` (default **3.0**) and which facility types count as vulnerable
  (default: daycare, school, children's, long-term-care, hospital, shelter).
- `watch_frac` — share of capacity reserved for the watch list (default **0.20**).
- Whether the watch list is a separate tab/section or a badge within one list.

## Owner actions

- **Bella** — `scores.parquet`/`predict_batch.py` schema add + `parquet_to_json.py`
  pass-through; PR tagging all owners (schema-change rule).
- **Jun / Aurelia** — Next.js view: the two-list (Active / Watch) worklist + a
  "serves vulnerable population" badge; **run `/verify`** (screenshots in the PR per
  the app rule).
- **Jun (PM) / Aurelia (label)** — sign off the policy knobs above.

## Trade-offs to be honest about

- Stakes weighting **lowers raw events caught** at a fixed capacity (it trades some
  total catch for vulnerable-facility coverage) — that is a deliberate equity choice,
  not a regression. Decide it explicitly.
- Watch-list events are lower-prevalence (clean base rate ~4.3%); even at 2.5× lift the
  watch slots are an early-*warning* list, not a high-confidence one — label the UI
  accordingly.
