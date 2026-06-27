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
