# 0016 — Multi-city expansion (NYC, then LA) and a shared risk vocabulary

- **Status**: **Proposed** (feasibility record. A measured feasibility run
  (2026-07-04) now backs the shape below — see "Measured results". The one
  durable artifact produced is [`reference/violation_crosswalk.csv`](../../reference/violation_crosswalk.csv);
  the NYC/Chicago modelling code stayed throwaway scratch.) **Los Angeles was
  then built as a third city on this same shape — see the
  [Los Angeles extension](#los-angeles-extension-2026-07-04) below; that section
  is the durable LA record and its producer + data are committed, not scratch.**
- **Date**: 2026-07-04
- **Owner**: Bella (modeling / eval)
- **Owners to ack if this proceeds to a build**: Bella + Deepak (modeling),
  Aurelia + Jun (web app — the `scores.json` vocabulary is cross-team), Arun (DE
  — a second-city loader), Jun (PM / scope — this is a Phase-2 scope expansion).

> Scope guard: multi-city is on the acknowledged Roadmap, not current-iteration
> scope. This record captures a feasibility investigation and a recommended
> shape so that *if* NYC is picked up, the team starts from a decision, not a
> blank page. It authorises no code by itself.

## Update (2026-07-06, PR #165) — NYC/LA now serve XGBoost

The "LogReg served (XGBoost comparator only)" decision recorded below is
**superseded**: NYC and LA now serve **XGBoost** for both models, matching
Chicago's two-XGB architecture. The feasibility numbers below still stand; only
the served estimator changed.

- **Model 1 (risk score) → XGBoost.** On a deploy-realistic split (train on all
  realized history, test on the most recent 12 months) XGB beats the calibrated
  LogReg baseline on both gate metrics: NYC +0.016 PR-AUC / +0.039 precision@10%,
  LA +0.006 / +0.044. (Rolling-CV early folds train on a data-starved post-COVID
  sliver that won't recur, so the deploy-realistic eval is the honest read of a
  "deploy now" decision.)
- **Model 2 (forecast-only trend) → regularized shallow XGBoost** (depth-2,
  strong L2, few trees) — the thin prior-only feature set overfits at depth-3.
  The tree config is matched to feature-set size, not city (the same reg config
  is the *worst* option on Chicago's richer Model-2 feature set).
- **Label unchanged.** A 365-day calendar window was evaluated and **rejected**:
  the median next-inspection gap is ~378 d (NYC) / ~342 d (LA), so a fixed window
  would mislabel ~60% of establishments as false negatives. The event-anchored
  next-inspection label stays.
- **Trend framing per city.** LA's steeply-rising-slope watch list shows ~2.7×
  forward lift (validated, DR 0011 style); NYC's is weak (~1.4×, no
  strict-vs-loose separation, compressed by its high base rate) so NYC's trend
  stays **descriptive-only**, never a watch-list claim.
- **Serving shape unchanged.** XGB uses Platt-on-margin calibration + native
  TreeSHAP drivers + the same calibration triple the detail-page waterfall
  already consumed under LogReg, so the app path is unchanged. `MODEL_VERSION`
  is now `{nyc,la}_xgb_sigmoid`.
- **Archival parity.** NYC/LA are now S3-backed like Chicago and persist Model 1
  + Model 2 joblibs (`/models`) plus the raw pull snapshot (`/processed`, the
  reproducibility anchor, since the source feed drifts) via `make publish-cities`.

## Question

We want to (a) add a second city (New York City) and (b) give the product **one
consistent risk vocabulary across cities** — while also, if possible, improving
accuracy. Two sub-questions drove this record: do we build **one pooled model or
separate models**, and **what does each city predict**?

## Terms

- **Chicago label (exists today)** — `y_fail_or_critical_next_180d`: 1 if the
  establishment has a Fail result **or** a priority violation (codes 1–29)
  within 180 days of `as_of_date`. Forward-looking, binary. Unchanged by this
  record.
- **NYC grade / score** — NYC inspections carry a **numeric score** (the
  inspection's violation-point total: general ≥2, critical ≥5, public-health
  hazard ≥7 points, summed) and a **letter grade** that is a threshold on it:
  **A ≤13, B 14–27, C ≥28. Lower score = cleaner.** The grade is a coarse
  3-bucket rounding of the score.
- **Shared risk vocabulary** — a common `severity_tier` (T1/T2/T3) and violation
  `theme` set that both cities' violation codes map onto, plus the existing
  `risk_score` / `risk_tier` / `top_drivers` output fields. A *presentation and
  feature-schema* layer, **not** a shared training target.
- **Crosswalk** — the code→(theme, severity) lookup that realises the shared
  vocabulary. Sketched in this record; full build is a separate artifact.

## Decision

1. **Separate models, one shared pipeline — not a pooled model.** Chicago and
   NYC each get their own fitted model against their own real label. They share
   the **feature-engineering code** (`prior_*` history builders, the temporal
   splitter, keyword flags, the crosswalk theme/severity columns) and the
   **output schema** (`scores.json`). One pipeline, run twice, `.fit()` twice.
   A single pooled model is rejected (see Alternatives).

2. **Each city predicts forward risk of a bad inspection outcome — same
   product meaning, city-specific event.** The user-facing prediction is
   identical in both cities ("elevated near-term risk, yes/no, and why" →
   `risk_score`, `risk_tier`, `top_drivers`). The underlying event differs
   because the cities record outcomes in different units:
   - **Chicago:** next-180-day Fail-or-priority (unchanged).
   - **NYC:** the **next inspection is graded B or C** (equivalently score ≥14).

3. **NYC label is event-anchored, not a fixed 180-day window.** NYC inspects on
   a ~annual+ cycle (Evidence), so a 180-day window is empty for most places.
   NYC predicts the outcome of the establishment's **next inspection whenever it
   occurs**. Chicago keeps its 180-day window (Chicago inspects far more often).
   The windows legitimately differ by city; the product statement does not.

4. **NYC primary target = binary B/C; numeric-score regression is the accuracy
   experiment.** The binary gives a calibrated P(bad) that drops into the
   existing eval harness (PR-AUC, precision@K, calibration, top-decile lift) and
   the shared `risk_score`. The **numeric score** keeps information the binary
   discards and was the one lever with a plausible accuracy story, so it was
   prototyped as a regression **and measured**. **Result: it did not win** — the
   regressed score ranks the B/C target no better than the binary classifier
   (PR-AUC 0.594 vs 0.600). Ship the binary; the score-regression is not worth
   the added complexity (see Measured results).

5. **No change to the Chicago model — label or features.** Chicago keeps its
   forward Fail-or-priority binary and its current feature set. The crosswalk's
   theme/severity columns are redundant with Chicago's existing
   `n_priority`/`n_core` + keyword flags, so they are **not** wired into Chicago
   training. **Now measured, not just asserted:** adding crosswalk theme counts
   moves the production model +0.006 PR-AUC (noise, same size as the
   facility-type ablation) and moves the forecast model −0.001 PR-AUC when the
   themes are leak-free *prior* counts. (A +0.033 gain appears only when
   *current*-inspection theme counts are added to the forecast model, but that
   just reintroduces the current-outcome signal the forecast model deliberately
   drops — not orthogonal signal.) The crosswalk therefore touches Chicago only
   as a **display/reporting** derivation (`severity_tier`, `top_theme`, a shared
   "severity burden" metric), computed from violation text already parsed.

6. **A pseudo-score is a display metric, never a Chicago training target.**
   Chicago records no numeric score. A crosswalk-weighted burden
   (T1×7 + T2×5 + T3×2) can be computed for both cities as a **shared display
   magnitude**, but predicting an invented number is not more truthful than
   predicting Chicago's real Fail event — so Chicago's label stays the real
   event.

## Evidence

All figures pulled live from NYC Open Data `43nn-pn8j` on 2026-07-03 (SODA API).

- **Size / coverage:** 296,235 violation rows, 26 columns, ~31,200 distinct
  establishments (`camis`); one row **per violation** (Chicago is one row per
  inspection). Portal keeps a rolling ~3 years live.
- **Grade distribution:** among rows carrying a letter grade (130,032),
  A 75.8% / B 14.0% / C 10.1% at the **row** level. At the **inspection-event**
  level (deduplicated to one row per `camis`×date, n≈51,800) the skew is
  **stronger**: **A 87.6% / B 8.5% / C 3.9%** — B/C row-share is inflated because
  worse inspections cite more violations. The "less-skewed label" hope is
  therefore **weaker than expected** for the binary/letter framing.
- **Numeric score:** range 0–154, per-event **median 11, mean 11.6**, 75th pct
  13, 90th pct 19. Continuous spread exists but the bulk sits in 8–13.
- **Cadence (window design):** median days to next graded inspection **≈500**
  (A→503, B→467, C→306; worse places return sooner). Only ~10% of gaps are under
  ~286 days → a 180-day forward window is empty for most NYC establishments,
  which is why NYC is event-anchored (decision 3).
- **Violations are a different source, not the same catalog.** NYC uses NYC
  Health Code Article 81 codes (`10F`, `08A`, `04L`, …); Chicago uses codes 1–63
  under the Illinois/Chicago food code. Overlapping *concepts*, no 1:1 code map —
  hence the crosswalk (below) rather than a code join.
- **Accuracy context:** the Chicago model sits at an *information* ceiling, not a
  sample-size ceiling ([handoff: modeling ceiling]). Pooling NYC rows does not
  lift Chicago; violation-derived features are the weakest, tested-flat lever. So
  the shared vocabulary delivers **consistency, not lift**; the only credible
  lift is NYC's own richer score target, which must be measured before claiming.

## Crosswalk sketch

Two axes; every code in both cities maps to exactly one `(theme, severity)`.
Grounded in the actual code descriptions pulled from both feeds.

**Severity → shared risk tier**

| Shared tier | NYC source | Chicago source |
|---|---|---|
| **T1 — imminent hazard** (closure-worthy) | public-health-hazard scoring (≥7 pts) / immediate-closure conditions | `results = Fail` + priority code; active pest / sewage / no water |
| **T2 — critical / priority** | `critical_flag = Critical` | priority codes 1–29 |
| **T3 — general / core** | `critical_flag = Not Critical` | core codes 45–63 |

Chicago's priority-foundation band (30–44) has no exact NYC twin: temperature /
contamination items map up to T2, documentation / structural items to T3. This is
the one judgement call in the mapping and must be documented per code.

**Theme buckets (shared vocabulary)** — examples verified against both feeds:

| Shared theme | NYC codes (verified) | Chicago code families |
|---|---|---|
| Temperature control | `02B` hot <140°F, `02G` cold >41°F | 11–16, 33–35 |
| Pest / vermin | `04K` rats, `04L` mice, `04M` roaches, `04N` flies | 55–58 |
| Facility pest-proofing / harborage | `08A` harborage | 55, 58, 59 |
| Hygiene / handwashing | `05D` no handwash sink | 10, 3 |
| Cross-contamination / food protection | `06C` unprotected storage | 36–38, 22 |
| Approved source | `03A` unapproved / home-prepared | 17–21 |
| Food-contact surface cleanliness | `06D`, `06E`, `09C` | 47–49 |
| Non-food-contact / equipment | `10F` equipment / surfaces | 51–54 |
| Plumbing / sewage / water | `10B` backflow / anti-siphon | 39–44 |
| Facility structure / lighting | `22C` lighting / shatterproof | 45, 51–54 |
| Management / certification | management-code family | 1–3, 5 |
| Chemical / toxic | toxic-storage codes | 29, 60 |

**Artifact (built):** [`reference/violation_crosswalk.csv`](../../reference/violation_crosswalk.csv)
— a single flat lookup, `city, native_code, native_desc, theme, severity_tier`,
one row per violation code, joined by each city's feature builder. Reviewable,
diffable, out of code. **220 codes** (65 Chicago + 155 NYC).

### How the crosswalk was built

1. **Codes + descriptions.** NYC: every distinct `violation_code` from the live
   feed (`43nn-pn8j`), with its modal `violation_description` and modal
   `critical_flag`. Chicago: codes 1–63 parsed out of the `violations` free-text
   in `inspections_labeled.parquet` (each fragment is `"<code>. <DESCRIPTION> -
   Comments: …"`), keeping the longest description seen per code.
2. **Theme** is assigned by an **ordered keyword rule-list run on the
   description text**, not on the code number — so the same rules work across
   both cities' different code schemes. First rule that matches wins; 12 themes
   (temperature, pest/vermin, pest-proofing, hygiene/handwashing, approved
   source, cross-contamination/protection, food-contact surface, non-food
   equipment, plumbing/sewage, chemical/toxic, management/certification, plus
   `other_administrative` as the fallback).
3. **Severity tier.** NYC: `critical_flag = Critical → T2`, `Not Critical → T3`;
   a few live-pest / sewage / no-water descriptions lifted to **T1**. Chicago:
   priority codes 1–29 → T2, core 30+ → T3, with the same T1 lift for
   imminent-hazard wording.
4. **Coverage.** 22% of codes fall in `other_administrative` — and those are
   genuinely **not food-safety** (NYC tobacco `15-xx`, trans-fat/sodium labeling
   `16-xx`, recycling/straws `19-xx`, signage `20-xx`; Chicago smoking,
   "previous violation corrected", report-display). The food-safety themes are
   cleanly populated in both cities. The one documented judgement call is
   Chicago's priority-foundation band (30–44): temperature/contamination items
   lifted to T2, documentation/structural to T3.

The rules are heuristic and reviewable; a per-code human sign-off pass is the
remaining polish before this is treated as canonical.

## Measured results (2026-07-04 feasibility run)

Throwaway scratch (not committed): full NYC pull → event dedup → leak-free
features → event-anchored forward B/C label; XGBoost, project defaults,
`scale_pos_weight`, 70/15/15 chronological split. Chicago A/B ran on the real
`features.parquet` at the production split (train 79,268 / test 7,008).

**NYC — the model is honest but weak, and the accuracy bets did not land.**

| NYC model (forward-only anchors, base ~0.39) | PR-AUC | ROC-AUC | P@10% | lift |
|---|---|---|---|---|
| Model 1 (production, incl current outcome) | 0.600 | 0.660 | 0.700 | 1.57 |
| Model 2 (forecast-only) | 0.576 | 0.638 | 0.677 | 1.51 |
| Score regression (ranking the B/C target) | 0.594 | — | — | 1.57 |

- The **less-skewed target is real** (base ~38–45% vs Chicago ~11%), but it does
  **not** translate to a better model. Base-rate-free, NYC is clearly *weaker*
  than Chicago: **ROC-AUC 0.66 vs 0.78**, **lift 1.6× vs 3.4×**. NYC's high raw
  P@10% (0.70) is a base-rate artifact — B/C is simply common. Raw precision@K is
  **not** comparable across the two cities' different labels/base rates; lift and
  ROC-AUC are.
- **Score regression did not beat the binary** (0.594 vs 0.600) — the hypothesised
  accuracy lever is dead.
- Forward-only (dropping mandated ~30-day reinspections) scores *better* than
  all-anchors, so the signal is genuine forward signal, not the reinspection
  bounce — but it is a shallow signal, consistent with NYC's rolling ~3-year
  history and the noisy score.

**Chicago crosswalk A/B — themes add no accuracy (confirms decision 5).**

| Chicago (test base 0.108) | PR-AUC | Δ vs baseline |
|---|---|---|
| Model 1 baseline (ALL_FEATURES) | 0.3254 | — |
| Model 1 + crosswalk themes | 0.3310 | +0.006 (noise) |
| Model 2 forecast baseline | 0.2726 | — |
| Model 2 + **prior** themes (clean, leak-free) | 0.2714 | −0.001 (nothing) |
| Model 2 + *current* themes (confounded) | 0.3060 | +0.033 (re-adds current outcome) |

**Verdict against the two goals:** shared vocabulary — **achieved** (crosswalk
works). Accuracy — **not supported by the data**: NYC is a weaker model than
Chicago, its score-regression lever is dead, and crosswalk features add nothing
to Chicago. Multi-city expansion is worth doing for *consistency and coverage*
(a second city in one product vocabulary), not for a modelling win. Any pitch
that says "NYC will improve accuracy" is contradicted by this run.

## Consequences

- **Chicago:** none to the model. Gains a display-only `severity_tier` /
  `top_theme` derivation from the crosswalk if/when the shared vocabulary ships.
- **NYC (if built):** a new loader (same SODA client family), an event-anchored
  next-inspection label, a mirrored feature build, and two candidate targets
  (binary B/C + score regression) to evaluate. `camis` history supports the
  forward label.
- **Product / `scores.json`:** stays one schema across cities. Adds a `city`
  discriminator and (optionally) a shared severity-burden field. Owner-tagged
  schema change → all-owner ack at build time.
- **Fairness:** NYC ships cuisine / borough; **cuisine is a proxy for ethnicity
  and stays out of the model** per [0004] / [0005], same as Chicago
  `facility_type`. It may inform product stakes-weighting, not training.

## Alternatives considered

- **One pooled model with a city indicator** — rejected. It needs a single
  unified label, forcing an artificial reconciliation of Chicago's forward
  binary with NYC's grade; base-rate / distribution gaps mean it largely learns a
  city switch; and we are information-ceiling'd, so pooling rows buys no accuracy.
- **Predict NYC's concurrent grade (the linked bootcamp repo's task)** —
  rejected. That describes the inspection just performed, not forward risk; it is
  a different product than the one we built.
- **Fixed 180-day NYC window (mirror Chicago exactly)** — rejected on the
  cadence data (~500-day median gap; the window is empty for most places).
- **Replace Chicago's label with a crosswalk pseudo-score for cross-city
  symmetry** — rejected; it is a synthetic target with no ground truth and leans
  on the weakest lever. Kept as a display metric only.
- **Skip the crosswalk, keep raw per-city codes** — rejected; then there is no
  shared vocabulary and no apples-to-apples cross-city reporting, which is half
  the goal.

## Residual risks

- **The accuracy goal was measured and not met.** The score-regression lever did
  not beat the binary (0.594 vs 0.600) and NYC is a weaker model than Chicago
  (ROC-AUC 0.66 vs 0.78). NYC ships as the binary; the expansion delivers
  *consistency and coverage*, not lift. State this plainly in any pitch.
- **NYC portal is rolling ~3 years**, limiting `prior_*` history depth relative
  to Chicago's 2019-onward span; the burn-in window for NYC will be shallower.
- **Crosswalk judgement calls** (Chicago 30–44 band; concept overlaps that are
  not 1:1) need per-code sign-off, not a bulk auto-map.
- **Two cities to maintain.** Each retrain, schema change, or feature edit now
  has two targets; the shared pipeline mitigates but does not remove this.

## Los Angeles extension (2026-07-04)

LA was built as a **third city on exactly this shape** — separate model, one
shared pipeline, shared crosswalk vocabulary, `scores.json` schema 0.5.0, calibrated
LogReg served (XGBoost comparator only). Unlike the NYC/Chicago scratch above, the
LA **producer** (`scripts/build_la_scores.py`), the **geocode cache**
(`reference/la_facility_coords.csv`), and the LA data JSONs are **committed**, and
the frontend/agent are LA-aware. Two things differed from the runbook's
assumptions and are the substance of this extension:

1. **Source is not Socrata — it's an ArcGIS Hub bulk CSV.** LA County left Socrata
   (the `data.lacounty.gov` SODA endpoint 302s to a dead legacy page); the only
   live *Socrata* LA feed (City of LA `29fd-3paw`) is frozen at 2018-07-31. The
   fresh data is LA County Environmental Health's ArcGIS Hub items — inspections
   `19b6607a…` + violations `5eaea9f8…` (2023-04-01 → 2026-03-31). The producer
   downloads/caches both CSVs and joins violations to inspections on
   `serial_number` to rebuild the per-violation frame the crosswalk needs.
2. **Grade direction is FLIPPED, and there are no coordinates.** LA grades A/B/C on
   **0–100 where HIGHER is cleaner** (A = 90–100), the opposite of Chicago and NYC.
   The label is `next inspection graded B or C` = **next score < 90**. The feed
   carries no lat/lon, so facilities are geocoded once via the free US Census batch
   geocoder (95.7% matched, ZIP-centroid fallback), cached and committed so
   rebuilds are offline.

**No burn-in cutoff was needed:** the fresh feed starts 2023-04 (already
post-COVID); mean score is flat ~94.5 across 2023–2026 with no step-change (only a
gradual B/C-rate drift the temporal split handles honestly).

**Measured (2026-07-04, regenerated after the same-day-B/C label fix + reopened-
establishment dedup).** 103,474 inspections / 43,053 facilities (42,270 served after
collapsing reopened establishments); B/C base rate ~4.9%. Temporal split **train 36,900
(2023-04→2024-06) / val 7,374 / test 7,197** (test base 8.7%). Served Model 1 (calibrated
LogReg): **PR-AUC 0.167, ROC-AUC 0.720, top-decile lift 2.12×** — an honest coverage
feature that sits **between NYC (~0.66) and Chicago (~0.78)** on base-rate-free ROC-AUC.
Tiers recalibrated to LA's own distribution → Low 40% / Moderate 45% / Elevated 13% / High 2%.
Crosswalk: **128 LA codes** added (T3 91 / T2 32 / T1 5), now 348 rows total.

**Consequences specific to LA.** Data lives under the `la/` prefix; every per-city
difference is in `CITY_CONFIG.la` (incl. the flipped `isBadOutcome` and A/B/C
badges) + a `HowItWorksLa` page. The chat agent is LA-aware (city routing +
city-aware `find_restaurants`) and `chatSupported` is **true**: LA data is in S3
and merging this PR redeploys the agent (cross-account, Deepak's account); revert
the flag if a post-merge lookup returns "no record" (runtime-role S3 read gap). **Residual risks:** low ~5% base rate
(small High tier), a shallow 3-year window (thin history, 71% get a trend slope),
and geocoded (approximate) coordinates.

## References

- NYC Open Data `43nn-pn8j` (DOHMH NYC Restaurant Inspection Results).
- NYC Health — Letter Grading for Restaurants (score thresholds, severity tiers).
- LA County Environmental Health — ArcGIS Hub items `19b6607a…` (inspections) and
  `5eaea9f8…` (violations), 2023-04-01 → 2026-03-31.
- [0004](0004-fairness-audit-and-proxy-feature-removal.md),
  [0005](0005-ethics-bias-and-responsible-ai.md) — proxy-feature exclusion
  (cuisine / facility type).
- [0007](0007-target-label-definition-and-scope.md) — Chicago label definition
  (unchanged here).
- [0011](0011-trend-signal-forecast-model-last-k-visits.md) — the forecast-only
  trend model reused for LA.
