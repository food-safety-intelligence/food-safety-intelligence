# 0014 — Out-of-business establishments: flag, grey out, keep reachable

- **Status**: Proposed (contract change — needs all-owner ack before merge)
- **Date**: 2026-07-02
- **Owners to ack**: Bella (eval / serve / scores contract), Deepak (agents),
  Aurelia + Jun (web app), Arun (DE) — `scores.json` is the cross-team contract.

## Problem

**27.6% of everything we score is closed.** 6,516 of 23,621 establishments in
the served `scores.json` have "Out of Business" as their most recent inspection
event — including **127 High-tier and 596 Elevated-tier** venues. A 180-day
*forward-window* risk prediction for a venue that no longer exists is not a
low-value signal, it is a claim the model cannot stand behind — the same
false-precision failure mode the no-record rule (decision 0010) exists to
prevent. Today these venues rank in the "Highest risk" list, occupy map pins,
and are scored on request by the chat agent as if they were open.

## Decision

Add closure to the `scores.json` contract (schema **0.5.0 → 0.6.0**) and
de-emphasise — but do not hide — closed venues in every surface.

1. **Definition (pipeline, single source of truth).** A license is
   out-of-business iff its **latest inspection event of any type** (from
   `inspections_labeled.parquet`, the only artifact carrying non-scoreable
   events) has result **`Out of Business`** or **`Business Not Located`**.
   - Latest-event-only: Chicago re-licenses reopened venues under a new
     `license_id`, so an old closure event never marks a live license closed.
     (Reopened/renewed licenses are also collapsed to one served row per
     physical establishment *before* this flag is applied — see the dedup note
     below — so PISTORES PIZZA & PASTRY, which held two `license_id`s at 546 N
     Wells St, is served once as its most-recently-inspected license and flagged
     closed, rather than as a live entry beside a stale ghost.)
   - `No Entry` / `Not Ready` are **not** closure signals — the venue may
     operate.
2. **Contract.** Two new columns in `scores.parquet` / fields in `scores.json`:
   `is_out_of_business: bool`, `closed_since: date | null`. `totals` gains an
   `out_of_business` count; `worsening_30d` / `improving_30d` now count
   **active venues only**.
3. **Web app.** Closed venues stay searchable and clickable (a user who looks
   one up deserves an answer), but: grey map pin with an "×" centre (not
   colour-only) and "out of business" in the accessible name; popup shows
   "OUT OF BUSINESS" instead of tier and hides the score; list rows dim, swap
   the tier pill for a neutral "Closed" pill, and drop score/trend/driver; the
   detail page banners the closure date and frames everything below as
   historical. In risk-sorted views closed venues sort **after** all active
   ones — this also keeps them out of the map's zoom-density pin budget, so
   city-zoom pins are always live signal.
4. **Chat agent (follow-up PR, Deepak).** Tools pass the flag through and the
   prompt directs the agent to disclose closure and frame the score as
   historical. Until that lands the agent keeps scoring closed venues as open —
   tracked below.

**Reopened-license dedup (folded in).** A reopen/renewal mints a new
`license_id` at the same name + address, so a license-only anchor lists the same
restaurant twice — a stale "Low" ghost beside the live entry (~2,620
establishments, ~3,700 duplicate rows in the served set). Scoring now collapses
to one row per physical establishment (normalised name + address;
most-recently-inspected license wins) *before* the closure flag, so the survivor
carries the closure status. This shrinks the served row count (~23.6k → ~19.9k)
and shifts the closed-count numbers in "Problem" above — recount them on
regeneration. A same-name chain at different addresses is not merged; a
shared-address venue with an identical name (food hall / terminal) can
over-merge (rare, accepted).

## Alternatives rejected

- **Drop closed venues from `scores.json`** — smallest diff, but deep links
  die, and the agent would answer "no Chicago inspection record found" for
  venues that have records; a factual lie (0005/0010 framing).
- **Cross-check Business Licenses status instead of inspection events** —
  catches quiet closures with no OOB visit (our count is a lower bound), but
  needs a second dataset join and status-code mapping. Deferred as a v2
  refinement; the OOB-event definition is precise (an inspector physically
  found it closed) and covers 6.5k venues today.
- **A "show closed" filter toggle** — new UI surface for an unproven need;
  grey-out + sort-last already keeps them out of the way.

## Consequences

- Homepage "Highest risk" and city-zoom pins stop surfacing dead venues
  (127 High-tier today).
- `tier_counts` still count closed venues (their historical tier); only the
  trend totals change meaning. Revisit if the homepage stats ever read wrong.
- The mock fixture and eval fixtures need the new fields on regeneration.

## Implementation status

(The 0011 half-landing taught us to track this per surface — keep it updated.)

- [ ] PR-A (this PR): pipeline (`out_of_business_status`, contract columns,
      totals, reopened-license dedup), web app (pin/list/detail/sort), contract
      doc, this record
- [ ] Regenerate + `make publish` + commit the refreshed
      `app/public/data/scores.json` fallback (bundle with the 0011
      `trend_slope` fallback regen — one regen fixes both)
- [ ] PR-B (Deepak): agent tools + prompt closure handling + eval case
- [ ] Fixture refresh: `scores_mock` + agent test fixtures on 0.6.0
