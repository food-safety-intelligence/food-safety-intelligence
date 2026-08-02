# Datasets and EDA takeaways (slide notes)

Two slides, about one minute each. **Slide content** is what goes on the slide,
kept minimal. **Script** is what you say over it (~150 words = 1 minute).
**Notes** are backup for questions, not for the slide.

Numbers verified against committed artifacts on 2026-07-19: the three cities'
`scores.json` and `inspection_history.json`, `reports/metrics/`, and decision
records 0007 / 0014 / 0016 / 0017. Inspection gaps are computed, not quoted.

---

# Slide 1: The data

## Slide content

**Three cities, three public feeds, no shared grading system.**

| | Chicago | New York City | Los Angeles |
|---|---|---|---|
| Venues served | 19,924 | 27,525 | 42,270 |
| Inspections | 307,591 | 84,457 | 94,524 |
| History | 2010-2026 | 2022-2026 | 2023-2026 |
| Grading | Pass / Fail + codes 1-63 | points, higher worse | 0-100, higher cleaner |
| Typical gap | 231 days | 316 days | 325 days |
| Bad-outcome rate | 14% | 38% | 6% |

<sub>All figures: full published dataset. Model metrics later in the deck use
the held-out test window, where base rates are 10.8% / 41.0% / 8.7%.</sub>

- **Chicago** — [Food Inspections](https://data.cityofchicago.org/Health-Human-Services/Food-Inspections/4ijn-s7e5)
  + [Business Licenses](https://data.cityofchicago.org/Community-Economic-Development/Business-Licenses-Current-Active/uupf-x98q).
  No grade. Violation codes **plus free-text inspector comments**.
  *All licensed food establishments*: 69% restaurants, 31% grocery, school,
  daycare, hospital kitchens, bakeries, caterers, mobile vendors.
- **New York City** — [DOHMH Inspection Results](https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j).
  Violation points to a letter: A up to 13, B 14-27, C 28+.
  *Restaurants only* — the feed is restaurant inspections, so no schools,
  daycares or hospital kitchens at all. Its variety axis is **cuisine** instead
  (about 33 types).
- **Los Angeles** — [Inspections](https://data.lacounty.gov/datasets/19b6607ac82c4512b10811870975dbdc)
  + [Violations](https://data.lacounty.gov/datasets/5eaea9f89b7549ee841da7617d3a9cba).
  Bulk CSV, not an API. A is 90+, so the scale runs the **opposite** way.
  *Restaurants and retail food markets*. No cuisine field, and the split between
  the two types is not measured.

> **The three populations are not the same.** Chicago is the broadest, NYC the
> narrowest. Cross-city comparisons are like-for-like on method, not on who is
> in the data.

## Script (about 60 seconds)

> Three cities, three separate public feeds, and they do not share a grading
> system. So each city gets its own model against its own label, through one
> shared pipeline.
>
> Chicago is our primary city and by far the deepest: sixteen years, three
> hundred thousand inspections. It has no letter grade at all, just pass or
> fail plus violation codes, and uniquely it gives us the **inspector's written
> comments** on what they actually saw. We turn those into twelve keyword
> features. We also pull business licence history for venue age.
>
> New York and LA both grade A, B, C, but in opposite directions. New York
> totals violation points, so higher is worse. LA scores out of a hundred, so
> higher is cleaner. Both inspect about once a year; Chicago visits roughly
> twice as often.
>
> And the rightmost row is the one to hold onto: bad outcomes range from six
> percent to thirty-eight. That is why we never compare raw accuracy across
> cities.

## Notes (backup)

- **Inspector comments.** Chicago's `violations` field is free text with a
  "Comments:" section describing what the inspector observed. Twelve hand-picked
  regex flags run on that residual text (temperature, cooling, raw meat, cross
  contamination, expired, rodent, pest, no soap, no paper towels, handwash sink,
  sewage, certified manager). Hand-picked over TF-IDF so each flag is one
  explainable SHAP column. Patterns are Chicago-tuned and do not transfer.
  `src/foodsafety/features/keyword_flags.py`
- **Licence features actually used:** `license_age_days`,
  `license_n_history_rows`. 311 and building permits/violations were built and
  tested but are **not** wired in — all flat.
- **Scope:** 69% restaurants, 31% grocery, school, daycare, hospital kitchens,
  bakeries, caterers, mobile vendors.
- **Chicago's short gaps:** the lowest quartile is under 12 days, which is the
  mandated re-inspection after a Fail.
- **LA has no coordinates in the feed** — geocoded once via the free US Census
  batch geocoder, 95.7% matched, ZIP centroid fallback.
- **NYC grain:** 296,235 raw rows are one row *per violation*, collapsed to
  about 51,800 inspection events.

---

# Slide 2: What EDA and the pipeline told us

## Slide content

**The signal**

- The **current inspection** carries it: clean now 7% forward risk, bad now 37%.
  <sub>(full dataset, as on slide 1)</sub>
- Prior fail count alone is **nearly flat** (0.22 / 0.20 / 0.22 / 0.26).
- That **flips by city** — NYC and LA inspect yearly, so they lean on history.
- NYC's closure flag points the **wrong way**: shutdown means the next visit is
  usually clean (19% vs 39%).

**The data problems**

- 2018 rule change forced a **2019 cutoff**, earlier rows kept as burn-in.
- Reopened licences created **ghost duplicates**: 23.6k venues down to 19.9k.
- **27.6% of scored venues were already closed** — 127 ranked High risk.
- Leakage guarded: chronological split, 180-day embargo, truncated rows dropped.

**The features: one source, sliced by time**

| Slice | Question | Example |
|---|---|---|
| **Now** | What did this visit find? | `was_fail` |
| **Ever** | What is the lifetime record? | `prior_fails` |
| **Lately** | Recent, and which direction? | `prior_fails_365d` |

Violation text (codes, keywords, themes) is a fourth cut of the **same rows**.

> **That is why we hit an information ceiling.** Every feature re-slices one
> table, so each new slice bought less than the last. The only genuinely new
> sources we tried all came back flat. The wins left are calibration and
> operating point, not accuracy.

## Figures to show

| Figure | Path |
|---|---|
| **Risk drivers** (the flip) | `reports/figures/cross_city/02_risk_drivers.png` |
| **Base rate** (why cities differ) | `reports/figures/cross_city/01_base_rate.png` |

Backups: `03_nyc_closure.png` (closure reversal), `04_seasonality.png`,
`07_violation_categories.png` (category mix), `09_topk_lift.png`,
`../eda_prior_fail_signal.png` (flat bars),
`../eda_label_prevalence_quarterly.png` (drift), `../eda_results_distribution.png`.

## Script (about 60 seconds)

> Three findings shaped the model.
>
> First, the current inspection is the signal. A clean visit in Chicago means
> seven percent forward risk; a bad one means thirty-seven. The venue's prior
> fail count, on its own, is almost flat.
>
> Second, that flips by city. New York and LA inspect yearly, so "now" is stale
> and they lean on track record. New York's strongest single feature is its
> closure flag, and it points the wrong way: a shutdown means the next visit is
> usually clean, because reopening requires passing a re-inspection.
>
> Third, cleaning changed the product more than the model did. Reopened licences
> created duplicate ghost entries for the same restaurant. And twenty-eight
> percent of everything we scored was already out of business, including a
> hundred and twenty-seven venues we were ranking as High risk. Both fixed.
>
> The honest conclusion: we are at an information ceiling. What is left to win
> is calibration and operating point, not accuracy.

## Notes (backup)

**Which population to quote — the rule for this deck.** Slides 1 and 2 describe
the *data*, so they use the **full published dataset**. Modeling slides evaluate
the *model*, so they use the **held-out test window**. Never mix the two in one
claim, and label every base rate with which one it is. The one-line footer under
each slide does that job.

**Where every base rate comes from.** There are **two** populations, not three.
The live web app and the metrics files are the same population; the app just
rounds to whole numbers.

| Surface | Chicago | NYC | LA | Population |
|---|---|---|---|---|
| Chart `01_base_rate.png` | 14% | 38% | 6% | full dataset, all years |
| `reports/metrics/` + `methodology.json` | 10.8% | 41.0% | 8.7% | held-out test window |
| Live web app (how-it-works) | 11% | 41% | 9% | same test window, rounded |

The chart averages the label over **every modelable row across all years**
(`notebooks/09_cross_city_eda.ipynb`, cell 5: `df[label].mean()`). The metrics
files and the app report only the **most recent held-out window**
(Chicago from 2025-07-01, n=7,008; NYC from 2025-04-01, n=9,456; LA from
2025-01-01, n=7,197).

They differ because the base rate **drifts**: Chicago's quarterly fail rate
peaked near 27% in 2023 and has fallen to about 20%, while NYC and LA drifted
up. That drift is itself the argument for a temporal split.

**The app already labels its own numbers**, so nothing there needs fixing:

> "time-held-out test from 2025-07-01 onward (n ≈ 7,008 inspections, 11% with
> an event)" — `app/src/app/how-it-works/page.tsx:573-580`

**So the only real outlier is the chart**, and that is correct as built: its
title asks "how often a bad outcome follows an inspection", which is a question
about the data, so the full dataset is the right answer. Do not regenerate it on
the test window. Just say which population you are quoting each time — the slide
footers do that.

**The feature engineering, in order of what it bought.** All three cities share
this architecture; only the text layer differs.

1. **Prior history (`prior_*`) — the backbone.** About 10 features per city:
   cumulative inspections, fails, priority violations, near-misses (Pass with
   Conditions), re-inspections, complaint-triggered visits, plus recency. This is
   where the leakage discipline lives: only two approved patterns, an exclusive
   `cumsum` minus the current row, and last-event-strictly-before. A bare
   `.shift()` is banned because it is not group-aware and would bleed values
   across licence boundaries.
2. **Current-inspection outcome — the single biggest win.** Adding `was_fail`,
   `n_priority_this_inspection`, `n_core_this_inspection` (contract v33 to v36)
   moved LogReg PR-AUC **0.291 to 0.344** and XGBoost **0.280 to 0.344**, both
   with precision@10% up, on an honest n=13,812 test. Still the model's spine:
   leave-one-out costs 0.028 and 0.026 PR-AUC for those two features while the
   other 34 each move it within ±0.006. NYC and LA carry the same idea as
   `cur_score` / `cur_n_critical` / `cur_is_bad` / `cur_closed`. This is also the
   change that required the ethics review (the re-inspection feedback loop).
3. **Recency and trend (v33).** `last_was_fail`, `prev_priority_violations`,
   `priority_violation_trend`, `prior_fails_365d`, `prior_priority_violations_365d`
   — the bet that recent history beats lifetime totals on a non-stationary
   process. Served PR-AUC 0.3147 to 0.3246, precision@10% 0.352 to 0.364. The
   same change **removed** `static_zip` and `static_facility_type` as fairness
   proxies, and dropping ZIP *improved* accuracy as well as bias. A rare win-win.

A fourth, if asked: the **forecast-only second model** (decision record 0011) is
trained on prior features only and is deliberately blind to the current
inspection. It exists precisely because the main model is so dominated by "what
just happened" that it cannot speak to direction.

**What model 2 drops, per city.** The three cities interpret "blind to the
current inspection" very differently:

| | Model 1 | Model 2 | Dropped |
|---|---|---|---|
| Chicago | 36 | **33** | 3 |
| New York City | 32 | **13** | 19 |
| Los Angeles | 28 | **11** | 17 |

- **Chicago drops only 3:** `was_fail`, `n_priority_this_inspection`,
  `n_core_this_inspection` (`CURRENT_OUTCOME_FEATURES`,
  `src/foodsafety/models/baseline.py:170-174`).
- **NYC drops 19:** `cur_score`, `cur_n_viol`, `cur_n_critical`, `cur_is_bad`,
  **`cur_closed`**, the 3 current severity counts (`cur_sev_T1/T2/T3`), and all
  **11** current theme counts.
- **LA drops 17:** `cur_score`, `cur_n_viol`, `cur_n_critical`, `cur_is_bad`,
  the 3 current severity counts, and all **10** current theme counts. LA has no
  closure field.

**Two things worth noticing.**

First, **NYC and LA are far stricter.** They drop every column derived from the
current visit and keep prior history only, so model 2 really is thin — which is
exactly why both use a regularized shallow configuration (depth 2, strong L2).
A depth-3 tree overfits 11 to 13 features. Note NYC gives up `cur_closed` here,
its single strongest feature.

Second, **Chicago's model 2 still sees the current inspection's violation text.**
The 12 `flag_kw_*` flags are regexes over *this* visit's inspector comments, and
they are not in `CURRENT_OUTCOME_FEATURES`, so they survive into the forecast
model. The stated intent is that model 2 "does not see today's verdict" — it
does not see today's *result*, but it does see today's *observations*. So
Chicago's forecast model is not prior-only in the way the other two are. Whether
that is deliberate is not recorded anywhere; worth raising rather than assuming.

**Why they are all one idea.** Every item above re-slices the same inspection
table on a different time horizon, and the text layer re-cuts the same rows
again. Nothing here is an independent source. That is the mechanical reason the
returns decayed — each slice is correlated with the last — and the reason the
ceiling could only have been broken by genuinely new data. The new sources we
tried (311 complaints, building permits and violations, weather, menu and
cuisine enrichment) were flat every time.

**How violation categories are grouped** (behind `07_violation_categories.png`).

*The problem.* The same real-world hazard is written three different ways.
A rat in the kitchen is code **13** in Chicago, **04K** in New York, and **F023**
in Los Angeles. The code numbers share nothing, so you cannot join on them and
you cannot compare cities without a translation layer.

*The solution: label every code twice.* One flat lookup table,
`reference/violation_crosswalk.csv`, gives every violation code in every city two
shared labels:

- **Theme = what kind of problem is it?** (11 values: temperature control, pest
  and vermin, hygiene and handwashing, plumbing, and so on.)
- **Severity tier = how dangerous is it?** Three levels: **T1 imminent hazard**,
  **T2 critical**, **T3 general**.

*How each label is assigned.* Theme comes from an ordered keyword rule-list run
on the code's **description text**, never its number, because the text is the
only thing the three cities share. Severity comes from each city's **own** native
judgement, so we are relaying the city's opinion, not inventing our own:
Chicago's priority band (codes 1-29) vs core (30+), NYC's critical flag and
hazard points, LA's point weighting.

*Worked example — one theme, three cities.* All six rows below carry
`theme = temperature_control` and `severity_tier = T2`, so the product can talk
about "temperature problems" in one vocabulary:

| City | Code | Native description |
|---|---|---|
| Chicago | `3` | POTENTIALLY HAZARDOUS FOOD MEETS TEMPERATURE REQUIREMENT |
| NYC | `02B` | Hot TCS food item not held at or above 140 °F |
| LA | `F007` | PROPER HOT AND COLD HOLDING TEMPERATURES |

*And where the cities genuinely disagree.* Pest violations show the severity axis
doing real work: Chicago `13` (rodent evidence) and LA `F023` are **T1**, but
LA `F043` (vermin-proofing of the premises) is only **T3** — evidence of an
actual rat outranks a gap under a door. That judgement is the city's, not ours.

The table is deliberately a plain CSV rather than code, so a reviewer can diff
it: `city, native_code, native_desc, theme, severity_tier`. **348 rows: 65
Chicago, 155 NYC, 128 LA. T3 230 / T2 100 / T1 18.**

*The 11 themes, in plain English.* Nine describe a real hazard:

- **Temperature control** — food held, cooked or cooled outside safe temperatures (33 codes)
- **Cross contamination and food protection** — raw and ready-to-eat food not kept apart, food left uncovered (35)
- **Approved source and food safety** — food from an unapproved supplier, spoiled or unlabelled stock (32)
- **Hygiene and handwashing** — staff hygiene, handwashing sinks, soap and towels (33)
- **Food contact surfaces** — cleanliness of the surfaces and utensils that touch food (20)
- **Equipment and non-food surfaces** — the rest of the kitchen's equipment and fittings (29)
- **Pest and vermin** — evidence of rodents, insects or birds on the premises (18)
- **Pest proofing of the building** — gaps and harbourage that let pests in (1)
- **Plumbing, sewage and water** — backflow, drainage, hot water supply (15)

Two are about paperwork and the operator rather than the food itself:

- **Management and certification** — a certified manager on site, required records (55)
- **Other administrative** — tobacco, labelling, signage, permits (77)

Two honest wrinkles: **"other administrative" is the single largest bucket at
22% of all codes**, and **"pest proofing" holds exactly one code** (one NYC
code, nothing from Chicago or LA), so it cannot support any cross-city
comparison and really belongs inside pest and vermin. Note also that
`docs/adding-a-city.md` still tells contributors to keep a **12**-theme set, and
the chart plots only the top **8** — three different counts across the repo, so
say "11" and expect to be asked.

Three caveats worth knowing:

- **22% of codes (77) land in `other_administrative`** — tobacco, labeling,
  signage. Genuinely not food safety.
- **Chicago's priority-foundation band (30-44) has no NYC twin.** Temperature
  and contamination items map up to T2, documentation and structural down to T3.
  This is the one judgement call in the mapping.
- **The chart reflects coding practice as much as real conditions.** NYC almost
  never codes "equipment / nonfood surface" (3% vs Chicago 73%); that is a
  difference in how inspectors write things up, not in how clean the kitchens
  are. Say this out loud if you show the chart.

Crosswalk themes are a **display layer for Chicago, not a training feature** —
adding them moved the Chicago model +0.006 PR-AUC, i.e. noise (decision record
0016). NYC and LA do use theme and severity counts as features.

**The label choice, if asked.** Fail-only measured *better* (3.61 vs 3.22
PR-lift, winning 6 of 6 folds) but we kept fail-or-priority: about 2.2x the
prevalence, so it catches more real hazards. A product call, on record in
decision record 0007.

**Seasonality — and why only Chicago uses it.** Risk peaks late summer and
December in all three cities, but **only Chicago ships calendar features**
(`temporal_month`, `temporal_quarter`). NYC and LA have none: neither producer
computes them.

That was measured, not assumed. The calendar family was tested in both cities
and **failed the both-metrics gate**:

| | Δ PR-AUC | Δ precision@10% | Passes gate |
|---|---|---|---|
| NYC | −0.0017 | −0.0024 | no |
| LA | +0.0006 | −0.0047 | no |

Chicago is the mirror image: *dropping* its calendar features fails the gate
(−0.0011 PR-AUC, −0.0086 precision@10%, ablated ≥ full in 0 of 3 folds), so they
stay. `reports/metrics/{nyc,la}/*_feature_experiments.json`

**So: no, we should not add month/quarter to NYC or LA.** The reason is in the
seasonality chart — LA's monthly swing looks the largest of the three, but at a
9% base rate those monthly estimates are small-sample noise, not a stable annual
pattern. Chicago has roughly twice the inspection volume and a longer history, so
its seasonal shape repeats across years and survives cross-validation; the other
two do not. Adding them would fit noise.

---

# Slide 3: Where the model works, and where it does not

## Slide content

**The use case that works everywhere: a ranked worklist for inspectors.**
Ranking is the product. The individual probability is not, and it is never a
verdict on a venue.

| Working the top 10% | Chicago | New York City | Los Angeles |
|---|---|---|---|
| Test inspections | 7,008 | 9,456 | 7,197 |
| Bad outcomes in it | 756 | 3,874 | 623 |
| Venues you get to flag | 701 | 946 | 720 |
| Caught | 295 | 699 | 157 |
| Precision | 42% | 74% | 22% |
| Lift over random | **3.9x** | 1.8x | 2.5x |

<sub>Held-out **test window** only, not the full served population (19,924 /
27,525 / 42,270). "Top 10%" is a budget of ~700-950 visits, so the counts are
small by construction.</sub>

**Chicago — works best.** Tiers span 16x, from 2.6% realized risk at Low to
40.8% at High.
*Breaks on venues with no track record.* On establishments that have never
failed, PR-AUC drops to **0.13** against a 0.38 headline.
> *Example:* a new restaurant passes its first inspection. No prior history, no
> days-since-last-fail, clean current result. Two features carry this model, and
> neither one says anything here.

**NYC — highest precision, weakest ranking.** 74% precision looks excellent until
you remember 41% of inspections already end badly. Lift is only **1.8x**.
*Breaks on the "Low" label.* NYC's Low tier realizes **22.8%** actual failure.
> *Example:* it tells a user "lower risk" about a venue that fails nearly one
> time in four. But be careful with the raw miss count: with 3,874 bad outcomes
> and only 946 visits to spend, **no model could catch more than 24%** here. NYC
> reaches 74% of that ceiling — the best of the three. Its weakness is ranking
> (1.8x lift), not the number it misses.

**LA — ranks fine, cannot threshold.** ROC-AUC 0.721 actually beats NYC.
*Breaks on absolute probabilities, and by neighborhood.* At a 0.5 cutoff recall
is **0.003**. False-positive rate varies **0.14** across ZIPs against a 0.10
tolerance.
> *Example:* use rank order, never the number. And the neighborhood gap was
> tested against a resampled null at **p = 0.0004** — it is not noise, and the
> earlier "probably geocoding" explanation was checked and rejected.

## Script (about 60 seconds)

> The honest answer is that this is a worklist, not a verdict. It tells an
> inspector where to go first. It should never tell a diner a restaurant is
> safe.
>
> Chicago is where it works best. Working the top ten percent finds bad outcomes
> about four times more often than picking at random, and the tiers span a
> genuine sixteen-fold range of real risk.
>
> New York looks like our best city and is actually our weakest. Seventy-four
> percent precision sounds excellent until you remember four in ten inspections
> already end badly there. To catch six hundred and ninety-nine problems, it
> misses over three thousand.
>
> And every city has an edge it fails on. Chicago is nearly blind to a brand-new
> restaurant with no track record. New York's "Low" tier still fails twenty-three
> percent of the time. And LA's false alarms cluster by neighborhood, which we
> tested against chance and it is not noise.

## Notes (backup)

**Worked example — why Chicago's top decile looks circular.** A restaurant fails
in March. A Fail triggers a mandated re-inspection about 30 days later, which
lands inside the 180-day label window, and re-inspections often find something.
So the model flags it High and is right. That is genuine forward risk, and SHAP
shows `was_fail` driving it openly — but it means **~91% of the top decile is
"recently failed"**, not newly discovered risk. Deconfounding was tried and
reverted (it cost accuracy and hurt Children's Services recall).
Decision record 0005.

**Worked example — why Chicago is blind to new venues.** A brand-new restaurant
passes its first inspection. The model has no `prior_*` history, no
`days_since_last_fail`, and a clean current outcome — which is most of its
signal gone. Two features carry the whole model (`n_priority_this_inspection`
−0.028 PR-AUC, `was_fail` −0.026; the other 34 each move it within ±0.006), and
neither is informative here. Measured: never-failed rows PR-AUC **0.128 to
0.146**; `prior_inspections == 0` is ~8.9% of rows.

**Worked example — NYC's closure flag runs backwards.** A venue closed by the
health department reads as *lower* risk next visit (19% vs 39%), because
reopening requires passing a re-inspection. Correct, but it means a shutdown in
the history makes the score go down, which looks wrong to a user unless the
driver text explains it.

**The two fairness findings that are open, not resolved.**

- **NYC cuisine calibration.** Across-group expected-calibration-error gap
  **0.20 against a 0.05 tolerance**, stable at Elevated and High. Four
  immigrant-associated cuisines read *safer than they are*: Bangladeshi
  predicted 0.512 vs actual **0.720**; Chinese 0.466 vs 0.530; Caribbean 0.433
  vs 0.519; Latin American 0.461 vs 0.526. Not fixable by dropping cuisine — the
  model never sees it. `docs/fairness_audit.md:120-152`
- **LA neighborhood false-positive gap.** 0.14 across ZIPs, CI [0.11, 0.23],
  against a 0.10 tolerance; tested against a small-sample null over 20,000
  resamples, **p = 0.0004**. Grows to 0.75 at the wider operating point. The
  earlier "probably a geocoding artifact" reading was tested and **wrong**.
  `docs/fairness_audit.md:154-187`

**Smaller groups where Chicago underperforms:** Children's Services PR-AUC 0.152
and Long Term Care recall@10% 0.25 (worst coverage of any group) — though both
are small-n. Seven of about 48 ZIPs sit below the performance floor, all at
2.8-5.3% prevalence.

**What the team tells users not to use it for** (`how-it-works` page): not a
verdict that a place is unsafe; **not an enforcement or licensing input**; not a
live guarantee for a diner; not valid outside the city it was trained on; and
never an automated action without a person in the loop.

**The trend arrow is weaker than it looks.** A plain "improving / worsening"
direction is only ~1.16x informative, i.e. near useless. Only the strict slice
(steeply rising *and* currently clean) reaches 2.26x. That is why the UI does
not present the arrow as a prediction.

**Right-truncation, said plainly:** the most recent scores are exactly the ones
whose labels cannot be verified yet. Those rows are dropped from evaluation, so
the honest test set and the served population are different bases — a 2026-06-27
PR once reported a fake +0.0216 PR-AUC purely by comparing across the two.

---

# Slide 4: Models explored, and what we serve

## Slide content

**Four families tried. The simplest tree won.**

| Model | Test PR-AUC | Verdict |
|---|---|---|
| Logistic regression | 0.372 | baseline, defensibility floor |
| **XGBoost, depth 3 + monotone** | **0.382** | **served** |
| MLP (sklearn) | ~0.371 | benchmark only |
| Tabular deep learning | 0.368-0.372 | parity, not served |

- **LogReg first** — every coefficient is interpretable. If the tree only
  barely wins, we ship this.
- **XGBoost** — non-linear interactions, native missing values, categorical
  splits without one-hot blowup.
- **MLP and tabular deep learning** — run *expecting* a negative result. Both
  delivered one, which is itself evidence the ceiling is in the data.

**Promotion gate:** a challenger must beat the incumbent on **both** PR-AUC and
precision@10%, on the same rows. XGBoost failed this once and stayed benched
before it later passed.

## Script (about 60 seconds)

> We tried four model families. We started with logistic regression, not as a
> throwaway but as a defensibility floor: every coefficient is interpretable, and
> if the fancier model only barely beat it, we would have shipped it.
>
> XGBoost won, for three specific reasons: it captures interactions logistic
> regression cannot express, it handles missing history natively instead of
> imputing it away, and it splits categories without exploding them into
> one-hots.
>
> We also ran a neural network and three modern deep tabular architectures,
> deliberately expecting them to lose. They did, and that is the useful part:
> given the same tuning budget they reached parity and won nothing measurable.
> That is strong evidence our ceiling is the information in the data, not the
> model.
>
> And no model ships unless it beats the incumbent on both our metrics at once.
> XGBoost failed that gate the first time and had to wait.

## Notes (backup)

**The served architecture, precisely.**

- **Estimator:** `XGBClassifier`, **300 trees, max_depth=3, learning_rate 0.05**,
  early stopping off so the served run is deterministic.
- **Why depth 3, not the experiment default of 6:** the signal is low-order, so
  deep trees over-fragment it and lose the forward-time top decile.
- **Monotone constraints (+1)** on every `prior_*` count, the `flag_kw_*` flags,
  and the three current-outcome features. This is the lever that put XGBoost past
  LogReg: on a forward-time split those counts grow past the training range, and
  unconstrained trees saturate at the top training threshold and lose rank
  resolution exactly where precision@10% lives.
- **`colsample_bytree = 0.70`**, below the 0.85 default. Two features dominate
  the model, so sampling fewer columns per tree decorrelates the ensemble away
  from them and sharpens the top-decile ranking. Seed-mean over 16 seeds:
  PR-AUC 0.3813 to 0.3824. Every other knob was null or worse.
- **Imbalance:** `scale_pos_weight`, never SMOTE (SMOTE on a time split inflates
  apparent PR-AUC and invalidates calibration).
- **Calibration:** Platt / sigmoid on the margin, fitted on validation.
- **Explainability:** XGBoost's native TreeSHAP (`pred_contribs=True`), which
  avoided adding the `shap` dependency. Explainability had been the blocker to
  promoting a tree at all.
- Same idea in all three cities; NYC and LA use a regularized shallow config for
  their thin model 2.

**Why these metrics, and why not accuracy.** The promotion gate is **PR-AUC plus
precision@10%**, both on the same rows:

- **PR-AUC** because the positive class is rare (about 11% in Chicago). ROC-AUC
  and accuracy both look flattering when 89% of rows are negative; PR-AUC tracks
  performance on the class we care about.
- **Precision@10%** because it is the actual operating point. A city inspects a
  fixed number of venues, so "of the top 10% we hand an inspector, how many are
  real" is the number that maps to the job.
- **Both, together,** because each is gameable alone: PR-AUC can improve while
  the top of the list gets worse, which is precisely where the product lives.
- **ROC-AUC** is reported but never used to gate, because it is base-rate
  invariant, which makes it the only fair *cross-city* comparison.
- The gate has teeth. XGBoost cleared PR-AUC (0.254 to 0.268) but missed
  precision@10% by ~0.003 and **stayed benched** (decision record 0002); it was
  promoted only later, at depth-3 with monotone constraints, winning both metrics
  in 5 of 6 expanding-window folds (decision record 0009).

## Related work: the Chicago precedent

**The prior work.** In 2015 the Chicago Department of Public Health deployed a
food-inspection forecasting model, built with the Department of Innovation and
Technology, Civic Consulting Alliance and Allstate, and open-sourced it
([github.com/Chicago/food-inspections-evaluation](https://github.com/Chicago/food-inspections-evaluation)).
It was independently audited in
[Kannan, Shapiro & Bilgic (2019), *Hindsight Analysis of the Chicago Food
Inspection Forecasting Model*](https://arxiv.org/abs/1910.04906) (AAAI Fall
Symposium), which is the source for everything below.

**Their architecture.** A **logistic regression with 16 predictors** (regularized
via `glmnet` in the released code). Trained on 17,015 canvass inspections
(2011-09 to 2014-04), tested on 1,637 (2014-09 to 2014-10). Their target was
**binary: will *this* inspection cite at least one of 14 critical violations** —
14.1% positive in training.

**Their metrics, and their results.** Three, all operational rather than
statistical:

1. Average reduction in **days** to reach a restaurant with a critical violation
   — **7.4 days earlier**
2. Standard deviation of that reduction — **25.2 days**
3. Fraction of critical-violation restaurants reached in the **first half** of
   inspections — **69%**

### How ours differ, and why

| | Chicago 2015 | Ours |
|---|---|---|
| Predicts | *this* inspection's outcome | the **next 180 days** |
| Metrics | days-earlier, first-half share | PR-AUC + precision@10% |
| Evaluation | simulated re-ordering of a 2-month test set | held-out chronological split |

**Ours are not simply "better" — they answer a different question**, and the
honest framing is that each buys something the other cannot:

- **Their metrics measure deployment value; ours measure ranking quality.**
  "Seven days earlier" is a real-world outcome that no PR-AUC can express. We
  have never run a field trial, so we cannot make that claim at all.
- **But their metrics carry two assumptions the audit says may not hold.** The
  days-earlier figure assumes **time invariance** — that a venue cited on one day
  would have been cited on another. Finding 2 of the audit calls that a
  counterfactual the data cannot settle. Finding 3 shows citation rates rose
  after 2015 in *complaint* inspections too, which the model never touched, so
  the improvement may not be the model's at all.
- **The audit's Finding 4 is the sharpest point: "violation hit rate is not an
  ideal metric."** Hit rates measure how often inspectors find problems, not
  whether food got safer. Our metrics inherit that same limitation, and we should
  say so rather than pretend a temporal split solves it.

**Where we genuinely improve on the precedent — one fairness fix, verified.**
Their single most influential feature was the **sanitarian (inspector) cluster**:
the "purple" cluster carried a coefficient of 1.555, an odds ratio of **4.7**,
larger than any violation-history feature. The audit's Finding 1 is that this
"unfairly changes predicted risk" — an establishment cannot choose its inspector,
so the model partly scored venues on who last walked in. **We exclude inspector
identity entirely.** Chicago's public feed does not even publish it
(`docs/data_dictionary.md:28-29`), and it is on our do-not-use list with cuisine
and Yelp.

**We also independently re-tested four of their feature families, and all four
came back flat on our forward-looking label:**

| Their feature | Our result |
|---|---|
| Daily high temperature | flat, fails gate (PR-AUC −0.0036, P@10 −0.0030) |
| Local sanitation complaints / garbage carts | 311 flat at every spatial scale |
| Alcohol / tobacco licence | +0.0014 PR-AUC but P@10 −0.0030, fails gate |
| Past critical / serious violation | **kept** — still our backbone |

That is the real relationship to prior work: we inherited their core insight
(per-venue inspection history predicts), dropped their unfair feature, and found
their auxiliary signals do not survive a leak-free forward-window test.

> **Repo citation error to fix.** `notebooks/00_feasibility_eda.ipynb` cell 17
> cites this as "Copel et al., 2014". No such reference exists — it is
> **Schenk Jr. et al. (2015)** for the model and **Kannan, Shapiro & Bilgic
> (2019)** for the audit. Worth correcting before anyone cites it onward.

**Other prior art we build on.** Tabular deep-learning literature
(FT-Transformer and ResNet-MLP, "Gorishniy 2021"; TabM, "Gorishniy 2024") —
implemented as challengers, given the same tuning budget as XGBoost, and beaten.
And one deliberate break with practice: we refuse socio-demographic predictors,
on the reasoning that "the literature's accuracy gains from socio-demographic
features partly *are* that bias" (decision record 0005).
