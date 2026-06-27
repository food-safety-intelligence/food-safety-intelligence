# Project plan

> **Scope authority:** `CLAUDE.md` is the source of truth for what is in and out
> of scope. This file captures the project's intent and testable claims — the
> why, what, and how. Where the two ever disagree, `CLAUDE.md` wins.

Condensed from the team's capstone plan.
Team: Arun Agarwal, Bella Davies, Deepak Srivastava, Jun Xu, Aurelia Yang.

## Problem / value

Foodborne illness is a major public-health issue. Chicago inspection data is
public but hard for consumers to interpret. We build a predictive, explainable
food-safety risk layer for Chicago food establishments. It is consumer-facing.

Three product questions the UI must answer for any establishment:

1. Does it show elevated predicted risk?
2. Is its risk improving, worsening, or stable over time?
3. What's driving the signal?

**Responsible-AI framing (explicit):** say "predicted risk" / "risk signal", not
"unsafe restaurant"; show the model's limits; avoid overclaiming.

## Data

Chicago Food Inspections (core, 2010+; train on 2019+, with pre-2019 inspections
as burn-in only), Business Licenses, and 311 complaints. NOAA weather and Yelp are
named in the original plan but deferred to Phase 2.

## Approach

Supervised classification / ranking: predict a Fail OR critical/priority violation
in a forward window (label `y_fail_or_critical_next_180d`). LogReg baseline → tree
models (XGBoost), both calibrated. Time-aware backtest with chronological splits —
never a random shuffle.

Four model components in the plan: (1) risk classification / ranking,
(2) violation-text classification (NLP), (3) Yelp review-signal extraction
(Phase 2), and (4) SHAP explainability. Plus a fairness audit across geography,
demographics, and cuisine (the plan's aspiration; the implemented audit covers
facility type and ZIP, with a demographic disparate-impact audit deferred to
Phase 2 — see decisions 0004 and 0005).

Evaluation metrics: precision, recall, ROC-AUC, PR-AUC, and top-decile lift. The
primary metrics are PR-AUC plus precision@k / recall@k.

## NLP strategy (hybrid)

- **A:** structured violation-code counts (codes 1–29, plus priority/core
  rollups).
- **B:** ~12 hand-picked keyword flags on the residual violation text.
- **C:** TF-IDF → TruncatedSVD(50) (kept as a deliverable; came up flat).

LLM / transformer NLP is a Phase-2 bet, scoped separately in a deep-learning
decision record.

## Anticipated challenges (check these in review)

- **Temporal leakage** — frequent reinspections can leak across the cutoff.
- **Class imbalance** — ~10% positive; use `class_weight` / `scale_pos_weight`,
  never SMOTE on time-split data.
- **Data-linkage quality** — Yelp fuzzy and 311 spatial joins (Phase 2).
- **Free-text violation parsing** inconsistency.
- **Responsible-AI / fairness** — consumer-facing, so reputational harm is a real
  risk; see decisions
  [0004](decisions/0004-fairness-audit-and-proxy-feature-removal.md) and
  [0005](decisions/0005-ethics-bias-and-responsible-ai.md).

## Success criteria

Model performance on a time-held-out test set, plus a demoable Next.js web app
(search + map + establishment detail + methodology page).

## References

- Scope source of truth: `CLAUDE.md`
- Data contracts: [interface_contracts.md](interface_contracts.md)
- Experiment ledger: [experiments.md](experiments.md)
- Decision records: [decisions/README.md](decisions/README.md)
