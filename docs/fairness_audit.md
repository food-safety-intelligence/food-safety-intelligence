# Fairness audit — results

Living record of the in-scope group-performance fairness audit. The audit asks:
does the model **rank comparably across kinds of establishment and across the
city**, or is it systematically worse for some groups (especially
vulnerable-population facilities)?

- **Method**: per-group PR-AUC, precision@10%, and recall@10% (coverage), for each
  `facility_type` and full 5-digit `static_zip` with **n ≥ 50** in the
  time-held-out test split (right-truncation filtered = served basis). Rule
  (CLAUDE.md): no group should fall below **50% of the overall PR-AUC**.
- **Reusable check**: `foodsafety.models.evaluate.group_performance_audit` — run it
  on any new experiment; `notebooks/06` is the canonical interactive run. Facility
  groups are normalized via `license_features.normalize_facility_type` so the
  vulnerable-pop families aren't fragmented.
- **Scope reminder**: the data is **all licensed food establishments, not just
  restaurants** (see `interface_contracts.md` § Scope) — which is exactly why the
  daycare / school / hospital / long-term-care groups exist to audit.

## v36 contract — 2026-06-21 (served basis, n = 7,008; overall PR-AUC 0.372; floor 0.186)

**Verdict: no clean pass on the strict PR-AUC floor, but no evidence of systematic
unfairness on the coverage lens.** The below-floor groups are concentrated in
low-prevalence / small samples, where PR-AUC is mechanically depressed.

By facility (normalized):

| group | n | prevalence | PR-AUC | recall@10% | below floor? |
|---|---|---|---|---|---|
| Restaurant | 4,940 | 12.1% | 0.377 | 0.35 | no |
| Grocery Store | 686 | 10.6% | 0.424 | 0.41 | no |
| School | 444 | 8.8% | 0.555 | 0.59 | no |
| Children's Services Facility | 299 | 5.4% | **0.152** | 0.38 | **yes** |
| Daycare | 194 | 5.2% | 0.388 | 0.60 | no |
| Bakery | 100 | 6.0% | 0.433 | 0.50 | no |
| Long Term Care | 63 | 6.3% | 0.213 | 0.25 | no (barely) |

By ZIP: **7 of ~48** fall below the floor (60608, 60616, 60613, 60642, 60630,
60660, 60652) — all low-prevalence (2.8–5.3%).

**Interpretation.** PR-AUC's floor is roughly the base rate, so a 3–5% prevalence
group can trip the "50% of overall" rule without the model being biased against it.
Read alongside recall@10% (coverage), the picture is reasonable — vulnerable groups
are caught (Daycare 0.60, School 0.59, Children's 0.38). The one to watch is
**Children's Services Facility** (a vulnerable group below the floor), but it is
small-sample (≈16 positives in 299) and its dip is within bootstrap noise — see
decision 0005 (small-group-noise residual risk + the re-inspection caveat).

**Standing conclusion** (consistent with decisions 0004 / 0005): the model is *more*
fair than the pre-audit version (demographic proxies `static_zip` /
`static_facility_type` dropped), with **no evidence of systematic unfairness on
coverage**; residual caveats — per-ZIP miscalibration only partly removed,
small/low-prevalence-group noise — carry to the **Phase-2 disparate-impact audit**
(census join), which is the real fairness gate before any deployment.

---

# Phase-2 — census disparate-impact audit (Chicago / NYC / LA)

Delivered 2026-07-12 via the reusable `foodsafety.audit` framework (decision
[0018](decisions/0018-census-disparate-impact-fairness-audit.md), **pending Jun's
sign-off**). Method: each city's deployed model on its chronological **test split**
(realised labels), joined to ACS tract demographics (audit-only), then three lenses
per axis — **statistical parity** (four-fifths flag-rate rule), **equalized odds**
(FPR + FNR gaps), and **calibration** (ECE gap) — each with bootstrap CIs; a gap is
a finding only when both material and CI-confident. Flagged = deployed **High** tier
(secondary: Elevated+High). Full per-axis numbers: `reports/fairness/fairness_audit_<city>.json`.

## The headline

**Across all three cities, every demographic finding is on the parity lens only —
the equalized-odds (FPR/FNR) and calibration lenses stay clean** (one exception:
NYC cuisine, below). Parity does not condition on the truth, so a flag-rate gap is
expected wherever true failure rates differ across groups — the model correctly
flagging higher-risk areas, not biased errors. This is the reassuring pattern: the
model does not make *more errors* or run *miscalibrated* for any race / income /
immigrant group.

| City | Test rows | Prevalence | M1 PR-AUC | Parity findings | Equalized-odds / calibration findings |
|---|---|---|---|---|---|
| Chicago | 6,222 | 10.5% | 0.382 | neighborhood, race, poverty, foreign-born, limited-English, facility type | **none** |
| NYC | 9,456 | 41% | 0.583 | neighborhood, income, race, poverty, foreign-born, limited-English, cuisine | **NYC cuisine — ECE (calibration) gap** |
| LA | 7,197 | 8.7% | 0.187 | neighborhood, income, race, foreign-born, limited-English, tenure | **none** |

## Reading the parity findings

- Where the flag rate **tracks group prevalence**, the parity gap is prevalence-
  driven, not bias. Chicago neighborhood (corr 0.67) and limited-English (0.85) are
  clear examples; both persist at the wider operating point.
- Where the flag rate does **not** clearly track prevalence (Chicago race / poverty,
  low correlation), the gap mostly does **not** persist at Elevated+High — pointing
  to thin High-tier counts (Chicago flags only ~125 as High) rather than a stable
  disparity. The secondary operating point is the honest check here.

## The one signal to watch — NYC cuisine calibration

NYC is the only city with a native cuisine field, and its model shows a
**calibration (ECE) gap across cuisines in both the risk model and the forecast
model** — the sole finding on a truth-conditioned lens in the whole audit.
Follow-up: is it concentrated in a few low-count cuisines, or a genuine
miscalibration worth a per-segment recalibration? Chicago and LA have
no cuisine field (OSM-derived cuisine is a deferred, low-confidence refinement).

## Mitigation (analysis only)

`foodsafety.audit.mitigation` prices per-group thresholds that equalize recall.
On Chicago, equalizing recall across income quartiles costs **~6 extra inspections
of ~124 flagged** — a ~5% adjustment, consistent with there being no equalized-odds
gap to fix. The model is not changed; adopting per-group thresholds is a scope call.

## Caveats

- Low-prevalence / small groups are gated out (n ≥ 50 for parity; ≥ 50 positives
  for FNR/calibration) and every gap carries a bootstrap CI — a single below-floor
  group is not a finding.
- LA coordinates are geocoded with a zip-centroid fallback (some points coarse);
  NYC/LA tenure is a first-seen-inspection proxy (no license history); NYC/LA
  facility type is a single group (not carried into their feature frames).
- "Area demographics" is the **residential** population of the establishment's
  tract — a neighborhood proxy, not its actual patrons.
