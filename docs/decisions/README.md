# Decision records

Short records of decisions that aren't recoverable from a diff (the "why", with
alternatives and consequences). Numbers are **assignment-order IDs — when a
decision was logged, not its priority**. Read by theme below, not by number. One
file per decision; the log is **append-only** — don't renumber existing records
(their numbers are referenced from code, other records, commits, and PRs).

## Foundational
- [0007 — Target label: definition and scope](0007-target-label-definition-and-scope.md)
  — what we predict (forward-180-day fail-or-priority), the window, the 2019
  burn-in cutoff, the label universe/exclusions, and why fail-only was rejected.
  (Recorded retroactively; mostly a project-start decision.)
- [0016 — Multi-city expansion (NYC) and a shared risk vocabulary](0016-multi-city-nyc-expansion-and-shared-risk-vocabulary.md)
  — **Proposed** (feasibility, measured): separate per-city models over one shared
  pipeline/vocabulary (not pooled); NYC predicts next-inspection B/C (event-anchored).
  Measured 2026-07-04 — shared vocabulary works (`reference/violation_crosswalk.csv`,
  220 codes), but no accuracy win: NYC weaker than Chicago (ROC-AUC 0.66 vs 0.78),
  score-regression doesn't beat binary, Chicago themes add nothing. Chicago model
  unchanged.

## Methodology & experiment tracking
- [0001 — Experiment tracking and served-model reconcile](0001-experiment-tracking-and-reconcile.md)
- [0002 — XGBoost validation methodology](0002-xgb-validation-methodology.md)
  — no val double-dip, expanding-window CV, the both-metrics promotion gate, and
  LogReg as the served production estimator.
- [0003 — Phase 2: hosted experiment tracking and feature versioning](0003-phase2-experiment-tracking.md)
- [0009 — Production estimator revisit: LogReg vs XGBoost under v36](0009-production-estimator-revisit-logreg-vs-xgb.md)
  — **Open**: inherits 0002's gate, supersedes only its estimator conclusion; lists
  what's needed to close.

## Fairness & ethics
- [0004 — Fairness audit and removal of demographic-proxy features](0004-fairness-audit-and-proxy-feature-removal.md)
- [0005 — Ethics, bias, and responsible-AI considerations](0005-ethics-bias-and-responsible-ai.md)
  — the living responsible-AI charter (principles incl. label scope, #7).

## Product & app
- 0006 — Chatbot surface and agent↔model integration *(in open PR #21; not yet on `main`)*
- [0008 — Risk-tier thresholds (Low / Moderate / Elevated / High)](0008-risk-tier-thresholds.md)
  — the score→tier cutoffs every user sees, why the mock thresholds were recalibrated.
- [0010 — Agent: no request-time scoring; no-record for venues not in the batch run](0010-agent-no-request-time-scoring-and-no-record.md)
  — why the chat agent reports only precomputed batch scores and returns an
  explicit "no record" (not an estimate) for OSM venues the batch run doesn't cover.
- [0011 — Trend signal: forecast-only model + last-K-visits slope](0011-trend-signal-forecast-model-last-k-visits.md)
  — **Accepted** (contract change): replaces the broken `trend_slope_90d` with a
  last-K-visits slope of a forecast-only model; descriptive trend + additive
  early-warning watch-list, not a verdict.
- [0014 — User feedback collection via a hosted form endpoint](0014-user-feedback-collection.md)
  — why a Google Apps Script form → private Sheet + team email (not an AWS
  write-backend), no PII, honeypot spam guard, prefilled role, summarizer deferred.
- [0015 — Agent: third-party reviews vs authoritative city-record links](0015-agent-reviews-and-authoritative-records-links.md)
  — why `find_reviews` links go direct to the source (unverified opinion, no
  scrape/paid API) and the new `find_inspection_records` links to the city's own
  records (authoritative provenance, keyless); extends 0012's sourcing principle.
- [0017 — As-of-common-month scoring + unified cross-city risk-tier rule](0017-seasonality-asof-scoring-and-low-tier-widening.md)
  — (A) freeze the seasonal features to the current month at scoring time only
  (keeps seasonality in the model, fixes calendar-frozen/stale Chicago scores); and
  (B) one tier rule for all three cities anchored to each city's base rate
  (Low `<0.5×`, Mod `<1×`, Elev `<max(2×, p98)`, High above) — meaning-based Low,
  small capped High; supersedes 0008's fixed Chicago cutoffs and the NYC/LA quantile
  blocks.

---

*Not a decision record?* Schema and **data cleaning** rules live in
[`../interface_contracts.md`](../interface_contracts.md); experiment results in
[`../model-experiments.md`](../model-experiments.md). See [`../README.md`](../README.md) for the
full docs map.
