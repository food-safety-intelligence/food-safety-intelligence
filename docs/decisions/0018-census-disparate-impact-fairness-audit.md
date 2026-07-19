# 0018 — Census disparate-impact fairness audit (Chicago / NYC / LA)

- **Status**: Proposed — **pending Jun's sign-off** (scope guard). Roadmap work in
  [0004](0004-fairness-audit-and-proxy-feature-removal.md) /
  [0005](0005-ethics-bias-and-responsible-ai.md) now delivered.
- **Date**: 2026-07-12
- **Owners to ack**: Bella (author), Jun (scope), Deepak (modeling backup), Arun
  (DE — new S3 features artifacts), Aurelia (app — future UI surfacing)

> Decisions 0004 and 0005 committed the project to a **demographic disparate-impact
> audit** (census join) as "the real fairness gate before any deployment," and left
> it as Phase-2 roadmap. This record delivers that audit as a reusable framework
> across all three cities, and records the method and the findings.

## Context

The in-scope group-performance audit (`evaluate.group_performance_audit`,
`docs/fairness_audit.md`) only checked `facility_type` and `static_zip`. The
standing open question from 0004: dropping the geographic proxy removed the
*explicit* signal but only partly removed geographic miscalibration, and we did
not know whether the residual correlates with **protected classes** (race /
income). Answering that needs demographic data joined for measurement only.

## Decision

Build `foodsafety.audit` — a city-agnostic fairness framework — and run it on
Chicago, NYC, and LA.

1. **Census is audit-only, never a feature.** The `lat/lon → tract → ACS` join
   (`census.py`, geopandas, behind the `audit` optional extra) exists solely to
   *measure* disparate impact. No demographic column enters `ALL_FEATURES`, the
   served parquet, or the app. The package is structured so the census join runs
   *after* the model, in its own module.
2. **Audit the deployed model on the test split.** Each city's adapter reproduces
   its deployed model on the chronological test split with **realised labels** —
   not the forward-looking `scores.json` (whose labels are unknown, so FPR / FNR /
   calibration are undefined there). Refit is deterministic and reproduces the
   deployed model (Chicago test PR-AUC 0.38 matches production).
3. **Three lenses, one honest reading.** Per axis (neighborhood, area income /
   race / poverty / foreign-born / limited-English, cuisine, tenure, facility
   type): **statistical parity** (four-fifths rule on flag rate), **equalized
   odds** (FPR + FNR gaps), and **calibration** (ECE gap), each with bootstrap CIs.
   A gap is a *finding* only when it is both **material** and **CI-confident**.
   "Flagged" = the deployed **High** tier, with an **Elevated+High** secondary.
4. **Model coverage.** Model 1 (risk) gets the full battery; Model 2 (forecast)
   gets calibration + coverage only (it has no flagging operating point).
5. **Mitigation is analysis-only.** Where an equalized-odds gap appears we price
   per-group thresholds that equalize recall; the model is never changed. Adopting
   per-group thresholds would be a separate scope decision.

## Findings (2026-07-12)

Full per-city detail in `docs/fairness_audit.md`; JSON artifacts in
`reports/fairness/fairness_audit_<city>.json`.

- **Every demographic finding is parity-only.** Across all three cities, the
  flag-rate (four-fifths) lens fires on several demographic axes, but the
  **FPR, FNR, and calibration lenses do not** (one exception below). Parity does
  not condition on ground truth, so a flag-rate gap is *expected* wherever true
  failure rates differ across groups — the model correctly flagging higher-risk
  areas, not biased errors. Where the flag rate tracks group prevalence (e.g.
  Chicago neighborhood, limited-English) the case is clear; where it does not, the
  gap mostly does **not** persist at the wider Elevated+High operating point,
  pointing to thin High-tier counts rather than systematic bias.
- **One equalized-odds signal to watch: NYC cuisine calibration.** The NYC model
  shows a **calibration (ECE) gap across cuisines**, in both the risk and forecast
  models — the only finding on a truth-conditioned lens. It needs follow-up (is it concentrated in a few
  low-count cuisines, or a real miscalibration?). Cuisine is audited natively only
  for NYC (DOHMH field); Chicago/LA have no cuisine field.
- **Mitigation cost is small.** Equalizing recall across Chicago income quartiles
  costs ~6 extra inspections of ~124 flagged — consistent with there being no
  equalized-odds gap to fix.

## Refresh (2026-07-19)

The notebook (`notebooks/08_fairness_census_audit.ipynb`) gained a colorblind-safe
**visual summary** (a fairness scorecard, two finding close-ups, and a detailed
appendix, saved to `reports/figures/fairness_*.png`) and was re-run on current data.
Two things changed:

- **NYC/LA numbers moved.** Chicago reproduces exactly (frozen deployed feature
  snapshot); NYC/LA re-pull live SODA, which has grown (LA 7,197 → 10,045 test rows).
  The three cities are therefore **not on one as-of date** — a reproducibility gap.
  **Recommendation:** pin NYC/LA to their raw snapshot (the hash already exists; the
  adapters just don't read it) so a re-run is deterministic across all three cities.
- **A new finding: LA neighborhood false-positive-rate gap** (0.14, CI [0.11, 0.23]),
  the first truth-conditioned finding outside NYC cuisine. Treat as **provisional**:
  LA neighborhood coverage is ~55% with coarse zip-centroid geocoding, so it may be a
  geocoding artifact. Re-check after LA geocoding improves and at the wider operating
  point. The headline is now "almost all findings are parity-only; two truth-
  conditioned findings (NYC cuisine calibration, LA neighborhood FPR), both flagged
  for follow-up," not "every finding parity-only except NYC cuisine."

### Follow-ups closed out (2026-07-19)

Both truth-conditioned findings were diagnosed further; neither changes the model.

- **NYC cuisine calibration — real but narrow; no action.** The 0.20 ECE gap is
  **concentrated in a single cuisine**: Bangladeshi (ECE 0.229, n=125). Every other
  audited cuisine is ≤ 0.09 and the best-calibrated is Pizza (0.026, n=587). It is
  stable (persists at Elevated+High, 0.20). We do **not** recalibrate for one n=125
  group — marginal gain, overfitting risk, and a per-segment recalibration is a model
  change outside the audit's measurement-only scope. Logged as a known limitation;
  revisit with more NYC history.
- **LA neighborhood FPR — likely a geography/small-sample artifact; keep provisional.**
  The operating-point check is done: the gap persists and grows (0.14 → 0.75 at
  Elevated+High), so it is not a thin-tier count artifact. But LA "neighborhood" is
  ZIP, and the gap is a range over 71 ZIPs (many n ≈ 50–86) under coarse zip-centroid
  geocoding, which inflates a max-minus-min statistic. No action now; the clean fix
  (if pursued) is to audit LA at a coarser, well-defined geography (e.g. council
  district), and the geocoding re-check stays blocked while LA is a preview feature.

## Consequences

- The census audit is now reusable and reproducible; adding a city is one adapter.
- **New artifacts**: per-city feature parquets persisted to S3
  (`processed/features/{features_current_inspection,nyc_features,la_features}.parquet`)
  so the audit and retrains no longer rebuild from raw — a cross-team addition
  (tag Arun).
- **New dependency**: geopandas + shapely + pyogrio, in the `audit` extra only —
  not installed for the model pipeline, app, or CI.
- **Follow-ups**: (a) surface a "model performance across groups" section on the
  how-it-works page — app workstream (Aurelia/Jun), product-sensitive framing (do
  **not** show raw per-group PR-AUC); the current page still says this audit is
  "deferred" and goes stale. (b) Investigate the NYC cuisine calibration gap.
  (c) OSM-derived cuisine for Chicago/LA (low-confidence, deferred).
- This does **not** change any model or feature. It is a measurement + a charter
  update, pending Jun's sign-off.
