# 0008 — Risk-tier thresholds (Low / Moderate / Elevated / High)

- **Status**: Accepted
- **Date**: 2026-06-21
- **Owners to ack**: Bella (eval / serve), Aurelia + Jun (web app), Jun (PM)

> The model outputs a calibrated probability; the UI buckets it into four tiers
> that drive what every user sees — the tier word, its colour, and sort order. The
> cutoffs are a product decision, and the "why these numbers" lived only in a code
> comment. This records it.

## Decision

Bucket `risk_score` with these thresholds (single source of truth:
`RISK_TIER_THRESHOLDS` in `src/foodsafety/serve/predict_batch.py`):

| Score range | Tier | Approx. population share |
|---|---|---|
| `[0.00, 0.04)` | Low | ~25% |
| `[0.04, 0.13)` | Moderate | ~62% |
| `[0.13, 0.30)` | Elevated | ~11% |
| `[0.30, 1.00]` | High | ~1% |

Tiers are assigned **in Python only** (`score_to_tier`) and shipped in
`scores.json`; the web app reads the `risk_tier` field directly. Documented in
[`interface_contracts.md`](../interface_contracts.md) § 3.

## Why these cutoffs
Real calibrated probabilities are **concentrated near zero** (median ~0.06,
p95 ~0.18), not spread across [0, 1]. The thresholds were recalibrated against the
actual served score distribution so the tiers carry information: most restaurants
sit in Low/Moderate, ~1% reach High — a useful triage band for inspector attention,
consistent with the capacity-limited top-K framing.

## Alternatives considered
- **The original mock thresholds `0.20 / 0.40 / 0.65`** — rejected. They suited the
  *uniformly-distributed synthetic* scores in the mock fixture, but on real
  calibrated probabilities they collapse almost every restaurant into "Low" and make
  the tiers meaningless.
- **Quantile / equal-frequency bucketing** — not adopted: fixed thresholds keep a
  restaurant's tier **stable across reships**, so its tier only moves when its score
  moves, not because the population distribution shifted.

## Consequences
- **A stale duplicate exists in the frontend.** `app/src/lib/scores.ts`
  (`tierFromScore`) still hard-codes the old `0.2 / 0.4 / 0.65` cutoffs. It is
  currently **dead code** (no call sites — the app uses Python's `risk_tier`), so it
  is not a competing live decision, but it is a landmine. **Tracked for removal** by
  folding into the open app PR #19 (app workstream).
- The mock fixture (`tests/fixtures/scores_mock.parquet`) **intentionally** keeps
  the old thresholds (uniform synthetic scores).
- Tier wording is product-facing and aligns with
  [0005](0005-ethics-bias-and-responsible-ai.md) principle 1: tiers are triage
  bands / a risk signal, **not** a safety grade or verdict.

## Cross-references
- [`interface_contracts.md`](../interface_contracts.md) § 3 — the tier table + the
  recalibration note.
- [0005](0005-ethics-bias-and-responsible-ai.md) principle 1 — "risk signal, not verdict."
- [0007](0007-target-label-definition-and-scope.md) — what the score predicts.
