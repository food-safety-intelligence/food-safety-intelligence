# 0004 — Fairness audit and removal of demographic-proxy features

- **Status**: Accepted (implemented in PR #10, pending merge)
- **Date**: 2026-06-14
- **Owners to ack**: Bella (modeling/eval), Jun (PM/scope); Arun, Deepak, Aurelia (consumers — fairness touches the whole team)

> Note: this record was drafted by Claude (Claude Code) at Bella's request,
> consolidating decisions made across PR #10, the weekly check-in, and several
> commit messages into one durable artifact. It captures the *why* behind the
> feature drops so the choice isn't re-litigated.

## Context

The served model is **consumer-facing** and affects restaurant reputation, so the
project commits to responsible-AI framing ("predicted risk", not "unsafe") and
fairness checks (CLAUDE.md keeps an in-scope group-performance check by
`facility_type` and zip prefix; a full disparate-impact audit is Phase 2).

The shipping feature set used two location/business-type categoricals —
`static_zip` and `static_facility_type` — that can act as proxies for protected
attributes (race, income, national origin) in a highly segregated city. We ran
the in-scope group-performance audit (zip prefix, facility type) plus an
exposure-bias check on `prior_*`.

## Findings

- **`static_zip` (geographic):** well-calibrated on average but with real
  per-zip miscalibration — over-flags several low-actual-risk zips (incl.
  Pilsen / Chinatown areas), under-flags high-risk downtown zips. An ablation
  showed its sparse high-cardinality dummies **overfit the chronological split**
  (dropping it *raises* served PR-AUC 0.3147 → 0.3188, precision@10% 0.352 →
  0.367). Dropping `static_zip` removes the explicit geographic proxy but only
  *partly* reduces geographic miscalibration — other features still correlate
  with geography.
- **`static_facility_type`:** only *partly* a proxy (some types — Live Poultry,
  Mobile Vendor, Shared Kitchen — concentrate in immigrant/ethnic communities),
  and it carries *legitimate* operational risk. But the ablation shows it adds
  ~no accuracy (PR-AUC 0.3147 → 0.3139), and its operational-risk signal is
  largely redundant with the **kept** `static_risk_tier` (the city's official
  Risk 1/2/3). So dropping it is ~free.
- **`prior_*` exposure / measurement bias:** `prior_fails` is largely driven by
  inspection *frequency* (corr 0.79), which is unequal across groups and barely
  predicts true forward risk (corr 0.05). The `prior_*` counts therefore partly
  encode *scrutiny*, not just risk.

## Decision

1. **Drop `static_zip` and `static_facility_type`** from the feature contract.
   Win-win: better accuracy AND less demographic-proxy exposure (implemented in
   PR #10, alongside the leak-free recency/trend features).
2. **Decline neighborhood "peer-fail-rate" features** (prior fail-rate of *other*
   nearby restaurants). Geographic proxy + individual unfairness (guilt by
   location) + predictive-policing feedback loop; harm concentrates on
   disadvantaged neighborhoods for a consumer-facing product. Not implemented.
3. **Census socio-economic data: audit-only, never a feature.** Using
   tract-level demographics as a *predictor* is a direct proxy → disparate
   impact (and the literature's accuracy gains partly encode that bias). Census
   is allowed in Phase 2 **only as a fairness-audit tool** to measure disparate
   impact and confirm whether the `static_zip` miscalibration correlates with
   protected classes.
4. **Keep `static_risk_tier`** (regulatory designation, not a demographic
   proxy) — it carries the operational-risk dimension more defensibly.

## Consequences

- The shipped model (PR #10) is both more accurate and less biased; the model
  card should report the audit, the proxy removals, and the residual caveats.
- **Residual caveats (Phase 2):** geographic miscalibration is only *partly*
  removed by dropping `static_zip`; the full disparate-impact-by-protected-class
  audit needs a **census join**; and the `prior_*` exposure bias suggests
  evaluating rate-normalized features (e.g. `prior_fail_rate`) — currently
  dropped as "noise" but worth revisiting on fairness grounds.
- A one-time **leave-one-out ablation** is queued to find other dead/overfitting
  features like `static_zip`.
