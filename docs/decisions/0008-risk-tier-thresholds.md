# 0008 — Risk-tier thresholds (Low / Moderate / Elevated / High)

- **Status**: Accepted, then **superseded** by the unified cross-city tier rule in
  [0017](0017-seasonality-asof-scoring-and-low-tier-widening.md) (2026-07-05). The
  fixed cutoffs below are the original Chicago-only scheme, kept for the record; the
  *why* (calibrated probs concentrate near zero; fixed cutoffs over quantiles for
  reship-stability) still holds and is what 0017 generalises to all three cities.
- **Date**: 2026-06-21
- **Owners to ack**: Bella (eval / serve), Aurelia + Jun (web app), Jun (PM)

> The model outputs a calibrated probability; the UI buckets it into four tiers
> that drive what every user sees — the tier word, its colour, and sort order. The
> cutoffs are a product decision, and the "why these numbers" lived only in a code
> comment. This records it.

## Decision

Original Chicago cutoffs (`0.04` at first ship, widened to `0.06`):

| Score range | Tier |
|---|---|
| `[0.00, 0.06)` | Low |
| `[0.06, 0.13)` | Moderate |
| `[0.13, 0.30)` | Elevated |
| `[0.30, 1.00]` | High |

**Superseded (2026-07-05).** [0017](0017-seasonality-asof-scoring-and-low-tier-widening.md)
replaces these hand-picked cutoffs with one rule for all three cities, anchored to
each city's base rate: Low `<0.5×`, Moderate `0.5–1×`, Elevated `1×–High_cut`, High
`≥ max(2× base, city p98)`. For Chicago (base 0.108) that is `0.054 / 0.108 / 0.216`
— the Low line barely moves, so nothing about the "why" here changes; it just now
applies uniformly. Cutoffs live in `assign_risk_tiers` (`predict_batch.py`), and the
served cutoffs are recorded in `scores.json`'s `risk_tier_thresholds`.

Tiers are assigned **in Python only** and shipped in `scores.json`; the web app
reads the `risk_tier` field directly. Documented in
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
