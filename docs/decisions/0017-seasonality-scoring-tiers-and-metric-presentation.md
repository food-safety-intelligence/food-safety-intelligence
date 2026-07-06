# 0017 — Responding to the "seasonality decides the tier" feedback: keep seasonality but apply it uniformly, widen the Low tier, and present metrics honestly

- **Status**: **Partly accepted, partly proposed.** The metric-presentation /
  how-it-works changes (Decision 4) are **built and verified** on branch
  `bella/mle-seasonality-cold-start`. The model-scoring and tier changes
  (Decisions 2 and 3) are **proposed** and handed off for implementation — see
  the [[handoff-seasonality-asof-scoring-2026-07-05]] memory note.
- **Date**: 2026-07-05
- **Owner**: Bella (modeling / eval)
- **Owners to ack**: Bella + Deepak (modeling), Jun (PM / scope), Aurelia (app)
- **Updates**: [0008](0008-risk-tier-thresholds.md) (Low-tier threshold). Inherits
  the both-metrics gate + temporal-split discipline from
  [0002](0002-xgb-validation-methodology.md) and the served estimator from
  [0009](0009-production-estimator-revisit-logreg-vs-xgb.md).

## Context — the feedback

The feedback, verbatim:

> "Looking at Emporium Logan Square, it gets a score of "moderate" and that seems
> to be completely a result of your seasonality parameter? It looks like all the
> other variables are 0. Which would seem to imply that the only reason it gets
> "moderate" instead of "low" is a factor that isn't really about the
> establishment itself.
>
> The place is a barcade that serves canned/bottled beverages, so based on that
> alone I would guess it's low risk just because they don't have a kitchen to keep
> clean."

## Diagnosis (confirmed empirically on the served data)

On the production model (`xgb_monotone_sigmoid`), Emporium Logan Square scores
**0.0422 → Moderate** (the Low/Moderate line is 0.04). Its SHAP drivers:

```
was_fail            -0.683   (passed the current inspection)
temporal_month      +0.366   (anchored in December — the ONLY upward driver)
n_priority 0        -0.356
prior_complaint 0   -0.308
n_core 0            -0.284
```

Every establishment-specific factor pushes the score **down**; the lone thing
lifting it over the Low line is the calendar. The reviewer is right.

**Root cause.** Seasonality is a real *population* effect (inspections anchored
late in the year carry higher forward-180-day risk because their window runs into
the warm season). But we score each venue at its **most recent inspection** and
**freeze** the seasonal term at whatever month that visit happened to fall in,
then display it as a timeless property of the business. Consequences:
- **Arbitrary across venues** — two identical clean venues get different tiers
  purely from *when* they were last inspected.
- **Stale** — Emporium's "December" window is already over; it is July.
- **Chicago-only** — the NYC and LA models carry no calendar features at all, so
  this cannot occur there (0 calendar-driven tiers in either).

Population scale: **988** Chicago establishments are Moderate where *every*
positive driver is a calendar feature — clean venues (Starbucks, Panera, Ballast
Point Brewing, preschools, nursing homes) tipped over the Low line by the month.

## Decision 1 — Keep seasonality in the model (do **not** drop it)

An ablation retrained the served recipe without `temporal_month` /
`temporal_quarter`:

| Basis | PR-AUC Δ | precision@10% Δ |
|---|---|---|
| Served honest test (n=7,008) | −0.0011 | −0.0086 |
| Expanding-window folds (ablated ≥ full) | 0 / 3 | 1 / 3 |

Dropping **fails the both-metrics gate** — small but consistent loss, and it is
bidirectional at the population level (moves 1,158 venues Moderate→Low but pushes
others up, **net +449 Moderate**). Seasonality carries genuine forward signal, so
we keep it and instead fix *how it is applied* (Decision 2).

## Decision 2 — Apply seasonality as a uniform "as-of" baseline (proposed)

At **scoring time only**, set `temporal_month` / `temporal_quarter` to one common
value for every venue, instead of each venue's frozen last-inspection month.
Training, validation, and test stay on the **real** inspection months, so the
honest evaluation is unchanged. This keeps the seasonal signal but applies it as a
population baseline rather than an individual differentiator, removing both the
arbitrariness and the staleness. Emporium, scored as-of July, is **0.028 → Low**.

The seasonal effect is real and sizeable (population mean score ranges ~0.048 in
spring/summer-anchored windows to ~0.078 for December-anchored ones).

**Open sub-decision (Jun):** score everyone as-of the **current month** (the home
page "breathes" with the season on each regeneration; most honest as a
forward-from-now estimate) vs a **season-neutral month** (a stable per-venue score
that averages the season out for display). Either removes the arbitrariness.

## Decision 3 — Widen the Low tier from 0.04 to 0.06 (proposed; updates 0008)

The score is a well-calibrated probability of a fail-or-priority event within 180
days (test base rate 10.8%). Realized forward-fail rate by predicted-score band:

| Band | Realized fail | vs base |
|---|---|---|
| 0.04–0.06 | 3.4% | 0.31× |
| 0.06–0.08 | 5.5% | 0.51× |
| 0.10–0.13 | 11.8% | 1.09× (≈ base) |

The current Low cutoff (0.04) is far too strict: everything from 0.04 to 0.13
("Moderate") realizes only 3–8% — well **below** the population average — so
"Moderate" is mislabeling below-average venues (it is ~45% of the population).
Setting Low `< 0.06` makes Low mean "realized risk ≈ a quarter of average" (2.6%),
moves ~48%→~69% of venues into Low, and fixes Emporium regardless of Decision 2.

**Open sub-decision:** exact cutoff (0.06 recommended; 0.05 conservative, 0.08
aggressive), and whether to re-derive the Moderate/Elevated/High cuts off
base-rate multiples. Keep scope to the Low cut unless a full re-tier is wanted.

## Decision 4 — Present metrics honestly on the how-it-works pages (built)

Reworked the methodology hero and metric copy across all three cities:

- **Comparison-safe hero = top-decile lift + ROC-AUC only.** Across cities, only
  ROC-AUC (base-rate independent) and lift (ratio to random) are comparable.
  Precision, recall, and PR-AUC are **not** — they move with each city's base rate
  (Chicago 10.8%, NYC 41%, LA 8.7%) *and* with different label definitions
  (Chicago = fail-or-priority within a fixed 180-day window; NYC/LA = grade at the
  next inspection, because those cities inspect ~annually and a fixed window would
  usually be empty). This is why LA has a high ROC-AUC (0.72) but low PR-AUC
  (0.17): good ranking on a rare-positive label, not a weak model.
- **Recall / precision / PR-AUC moved to the per-city operating section**, where
  they describe that city rather than invite a cross-city comparison. Where recall
  is shown it is quoted at the **same top-10% slice** as lift (recall = lift × K),
  so the two describe one operating point rather than a cherry-picked mix.
- **Selection-gate disclosure.** Added a sentence stating the model is *selected*
  on PR-AUC and precision in the top 10% (the both-metrics gate, under
  expanding-window cross-validation for Chicago), while lift/ROC-AUC describe the
  result. We do not hide the numbers we optimized for.
- **Ethics wording.** Removed "clean one" / "clean inspection" characterizations
  of establishments (a low score is a probability, not a verdict, and the page
  elsewhere says "not a verdict"). ROC descriptions now read "ranks a venue headed
  for [a fail/priority citation | a B or C grade] above one that won't."
- **Consistency.** All three cities now use "Methodology · <City>" eyebrows and an
  identical "How this *works*" title treatment.

## What we explicitly did NOT do

- **Did not drop seasonality** — it fails the gate and is real signal (Decision 1).
- **Did not switch Chicago to a next-inspection label** — the 180-day window is the
  better label (a true forward-time risk, free of the next-inspection *timing*
  confound). NYC/LA use next-inspection only because their annual cadence forces
  it.
- **Did not change the promotion gate.** PR-AUC + precision@10% stays: gating is a
  within-city, same-test-set comparison where base-rate dependence does not bite,
  and top-decile precision is exactly what a triage tool needs.
- **Did not switch NYC/LA to XGBoost.** They ship calibrated LogReg (XGB was a
  comparator); on their weaker signal XGB's edge is smallest and the linear drivers
  are simpler. Revisit per-city on the same gate if desired.

## Consequences / open items

- Decisions 2 and 3 require a **rescore + republish** of `scores.json` and
  `methodology.json`; tier distribution shifts (~48%→~69% Low). Verify Emporium
  (license `2294149`) → Low and that no venue's tier depends on inspection month.
- Implementation is handed off: [[handoff-seasonality-asof-scoring-2026-07-05]].
- A separate UI cleanup removes em dashes from all app copy:
  [[handoff-emdash-ui-cleanup-2026-07-05]].

## Cross-references

- [0002](0002-xgb-validation-methodology.md) — the gate + temporal-split it inherits.
- [0005](0005-ethics-bias-and-responsible-ai.md) — the responsible-AI framing behind
  the "not a verdict" / no-"clean" wording.
- [0008](0008-risk-tier-thresholds.md) — the tier thresholds this updates.
- [0009](0009-production-estimator-revisit-logreg-vs-xgb.md) — the served XGB.
- [0016](0016-multi-city-nyc-expansion-and-shared-risk-vocabulary.md) — the NYC/LA
  models and their next-inspection labels.
