# 0010 — Agent: no request-time scoring; no-record for venues not in the batch run

- **Status**: Accepted
- **Date**: 2026-06-28
- **Owners to ack**: Deepak (agentic AI — owner), Bella (eval / serve), Jun (PM)

> The chat agent finds candidate venues from OpenStreetMap (live) and attaches a
> risk signal. Some OSM venues are not in the published batch run. The natural
> instinct is to "just estimate something" for those at request time. This
> records why we deliberately do **not** — the decision is not recoverable from
> the diff, and a future teammate will ask.

## Decision

1. **The agent never calls the model at request time.** `get_safety_score`
   reports only the precomputed batch scores from `scores.json`. A venue that
   matches an address in `scores.json` returns its published `risk_score` /
   `risk_tier` / drivers directly — no feature build, no model invocation.

2. **A venue not covered by the batch run returns a no-record result, not a
   number.** `get_safety_score` returns `risk_score: null`, `risk_tier: null`,
   `matched_scores_json: false`, `status: "no_inspection_record"`, and the agent
   tells the user "no Chicago inspection record found". It does **not** return a
   low-confidence model estimate or a base-rate number.

## Why

- **Batch-score-to-JSON is the project's permanent design.** Per `CLAUDE.md`,
  the model runs as a batch job that writes `scores.json`; no surface calls the
  model at request time. The agent is now embedded in the web app (`/chat`), so
  scoring an unmatched venue live would directly violate that rule.

- **An estimate for an unmatched venue carries no per-venue signal.** A venue
  absent from the batch run has no inspection history, so every
  prior-/recency-/current-inspection feature is zero. Those are exactly the
  features the modeling work found carry the model (see `experiments.md`, the
  current-inspection-outcome run). With them all zero, the model returns a
  **near-constant value for every unmatched venue** — it cannot tell them apart.

- **A number invites comparison the data can't support.** `get_safety_score`
  sorts by `risk_score`. Emitting a near-constant estimate — even flagged
  "low confidence" — would let the agent rank one venue above another on noise,
  which is the exact fabrication failure mode the responsible-AI charter
  ([0005](0005-ethics-bias-and-responsible-ai.md)) forbids. A flag does not fix
  this; the misleading ordering survives it.

- **Calibration mismatch.** Batch scores are calibrated on a temporal split
  ([0002](0002-xgb-validation-methodology.md)). A request-time score from a
  zero feature vector is not comparable to them, so mixing the two in one ranked
  list is apples-to-oranges.

## Alternatives considered

- **Low-confidence model estimate with a UI flag** (the first approach on the
  PR that became this decision) — rejected. The estimate is near-constant across
  unmatched venues, so it is false precision, and the flag does not stop the
  agent from ranking on it.
- **Citywide base-rate number** (the label positive rate, ~11%) shown on the
  no-record result — rejected. A base rate is not a prediction for *that* venue;
  putting a number on the card reintroduces the same false-precision problem. If
  the agent ever cites the base rate it must be in words, framed explicitly as a
  citywide rate, never as the venue's score.
- **Omit unmatched venues from the response entirely** — rejected in favour of
  an explicit "no record" so the user learns the venue exists but is not covered,
  rather than silently disappearing.

## Consequences

- **`get_safety_score` output schema changed.** `risk_score` and `risk_tier` can
  now be `null`; a `status` field (`"scored"` | `"no_inspection_record"`) is
  added; no-record venues sort last. The agent prompt
  (PR #55 / `agents/system_prompt.txt`) reinforces this at the model layer: give
  no number when `matched_scores_json` is false. To be documented in the agent
  tool-output contract (`agents/README.md`).
- **`sagemaker_stub.py` is now orphaned.** With no request-time scoring, the
  agent never calls it. It is left in place but is a candidate for retirement;
  its pre-existing `FEATURE_ORDER`-vs-`ALL_FEATURES` drift is moot for the agent.
  Deepak (agent owner) to decide whether to remove it.
- This narrows the agent to **discovery over establishments the batch run
  covers**. Extending coverage is a data/batch problem (score more venues), not
  a request-time-inference problem.

## Cross-references

- `CLAUDE.md` — the batch-score-to-JSON rule ("the app never calls the model at
  request time").
- [0005](0005-ethics-bias-and-responsible-ai.md) — risk signal, not a verdict;
  no fabrication.
- 0006 — Chatbot surface and agent↔model integration *(in open PR #21; not yet
  on `main`)*: this record refines the scoring behaviour of that surface.
- [0002](0002-xgb-validation-methodology.md) — calibrated scores on a temporal
  split (the calibration this estimate could not match).
- [`../experiments.md`](../experiments.md) — current-inspection features carry
  the model / cold-start is weak.
- Implemented in PR #58 (`bella/agent-feature-builder-drift`).
