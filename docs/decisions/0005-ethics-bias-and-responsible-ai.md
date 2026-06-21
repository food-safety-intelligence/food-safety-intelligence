# 0005 — Ethics, bias, and responsible-AI considerations

- **Status**: Accepted (living charter for this iteration; review before any real deployment)
- **Date**: 2026-06-15
- **Owners to ack**: all (Bella, Jun, Arun, Deepak, Aurelia) — fairness is everyone's

> This record consolidates the project's responsible-AI stance and the bias
> decisions made so far into one place. The plan commits to responsible-AI
> framing and a "fairness audit across geography / demographics / cuisine";
> this is how we're honoring that. The specific feature-removal decisions live
> in [0004](0004-fairness-audit-and-proxy-feature-removal.md); this is the
> broader charter.

## Context

The product is **consumer-facing** and predicts forward food-safety risk for
named restaurants. A wrong or biased signal can cause real reputational and
economic harm — and that harm concentrates on disadvantaged neighborhoods if the
model encodes who-lives-where instead of how-clean-the-kitchen-is. So ethics
isn't a post-hoc checkbox here; it shapes what we build.

## Principles / decisions

1. **Framing — it's a "risk signal," never a verdict.** UI copy says *predicted
   risk* / *risk signal*, NOT "unsafe restaurant." We always show model limits.
   This is grounded in the numbers: at the top-decile operating point precision
   is ~0.35 — i.e. **most flagged restaurants do not actually have an event**, and
   ~2/3 of true events sit outside the flag. The model is a *triage/prioritization*
   tool, not a judgment about any individual restaurant.

2. **No demographic proxies as model features.** We dropped `static_zip`
   (geographic proxy for race/income in a highly segregated city; it also
   overfit) and `static_facility_type` (partial cuisine/ethnicity proxy, ~free to
   drop) — see 0004. We **declined** a neighborhood "peer-fail-rate" feature
   (guilt-by-location + a predictive-policing feedback loop). The operational-risk
   signal we keep comes from `static_risk_tier`, the city's own regulatory Risk
   1/2/3 designation — a defensible category, not a demographic proxy.

3. **Protected-attribute data is for AUDITING fairness, never for prediction.**
   Any demographic / socio-economic data (e.g. census tract income/race,
   neighborhood composition) may be joined **only to measure disparate impact**
   — never fed to the model as a feature. Using it as a predictor would encode
   systemic bias directly (and the literature's accuracy gains from
   socio-demographic features partly *are* that bias). This applies to any future
   data source, not one in particular.

4. **In-scope fairness check (now):** group-performance by `static_facility_type`
   and full `static_zip` is run in nb06 (06_eval_and_shap) on the served eval
   basis. We report per-group calibration / over-prediction, not just averages.

5. **Prior-inspection history (`prior_*`) — predictive, not deterministic.** This
   family is the model's strongest signal and its sharpest ethical question ("past
   fails don't mean future fails"). Our stance:
   - It produces a *calibrated probability*, never a verdict. Recurrence is real, so
     prior history is legitimately predictive; the objection conflates prediction
     with determinism, and calibration is what keeps the output honest.
   - The genuine risk is a **detection feedback loop**, not "past≠future":
     `prior_fails` correlates ~0.79 with inspection *frequency* but only ~0.05 with
     true risk (see residual risks below), so the counts partly encode *scrutiny*,
     not safety. We keep auditing this and will test rate-normalized variants (Phase 2).
   - The **recency / trend features** added in the 33-feature set (`last_was_fail`,
     `priority_violation_trend`, `prior_fails_365d`, `prior_priority_violations_365d`)
     directly answer the "past≠future" worry: they let the model see *recovery* — an
     old failure followed by clean inspections lowers the score, so one bad day does
     not permanently condemn a restaurant. Dropping prior history would make the
     model blunter and *less* fair, not more.
   - Unlike `static_zip`, `prior_*` reflects the establishment's **own conduct**, not
     a demographic group — the least proxy-like signal we have.
   - It is used for **prioritisation, not sentencing** (principle 1): a high score
     routes a human inspector; it is not a judgment about the restaurant.

## Known residual risks (carry into the model card + Phase 2)

- **Geographic miscalibration only partly removed.** Dropping `static_zip`
  removed the explicit proxy, but other features still correlate with geography,
  so the per-zip calibration spread persists. Needs the Phase-2 audit to quantify
  against protected classes.
- **Exposure / measurement bias in `prior_*`.** `prior_fails` is heavily driven
  by inspection *frequency* (corr ~0.79), which is unequal across groups and
  barely predicts true risk (corr ~0.05). The counts partly encode *scrutiny*,
  not just risk. Worth evaluating rate-normalized features on fairness grounds.
- **Small-group noise.** Sub-~50-row groups have unstable metrics; reported but
  not treated as evidence.

## Phase-2 commitments (before any real deployment)

- A **full disparate-impact audit** across demographic groups (the CLAUDE.md
  "production fairness audit" item). This needs a demographic-data source +
  PM scope; whatever source is used is audit-only per principle 3.
- Revisit exposure-bias mitigation (rate-normalized features).
- Keep LLM/transformer NLP out (per CLAUDE.md); if added later, apply
  food-safety guardrails (the plan's "Cooking Up Risks" reference).

## Consequences

- The shipped model is both more accurate and less biased than the pre-audit
  version, and the limitations are documented rather than hidden.
- This charter is the reference for the writeup's ethics section and for any
  "should we add feature X?" question — if X is or proxies a protected attribute,
  the answer is audit-only, not predict.
