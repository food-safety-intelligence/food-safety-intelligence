# 0015 — Agent: third-party reviews vs authoritative city-record links

- **Status**: Proposed
- **Date**: 2026-07-04
- **Owners to ack**: Deepak (agentic AI — owner), Bella (eval / serve), Jun (PM / scope guard)

> The agent can point a user to two very different kinds of "what else can you
> tell me about this place" — unverified third-party diner reviews, and the
> city's own inspection records. This records the provenance boundary between
> them and why both are keyless link-outs (never scraped, never a paid API). It
> extends the sourcing/verifiability principle of
> [0012](0012-agent-general-food-safety-education-with-cited-sources.md) — a
> claim must come from an authoritative source the user can verify — from general
> facts to the score's own source and to diner opinion. The ToS / cost / audience
> reasoning is not recoverable from the diff. It also retroactively records the
> `find_reviews` tool, which shipped without a decision record.

## Decision

1. **`find_reviews` links go directly to each source's own site** — Yelp, Google
   Maps, and TripAdvisor search for the business. Opt-in, only when the user asks
   what diners say. Reviews are unverified opinion: disclaimered, never part of
   the risk score, never an eat/don't-eat verdict. (This fixes the earlier form,
   which routed through a DuckDuckGo / Maps *search*, so a link labelled "Yelp
   reviews" was actually a `duckduckgo.com` URL — not a link to reviews.)

2. **New tool `find_inspection_records` links to the city's OWN records** — a
   keyless deep link to the Chicago Food Inspections portal for a *set* the agent
   is discussing: compare/list by `license_id`, or an area by ZIP / radius. It is
   the authoritative source behind the score, so it carries **no disclaimer**; it
   is provenance offered alongside the agent's own comparison, not a substitute
   for it.

3. **Both tools only BUILD a URL** — no fetch, no credentials, nothing stored.
   The agent never scrapes or quotes third-party pages, and never calls a paid
   API.

4. **Unverified and authoritative content stay visibly separate.** A review is
   never presented as an inspection result; a city record is never presented as
   diner opinion.

## Why

- **Reviews are a weak safety signal for our audiences** (everyday diner,
  inspector, restaurant owner) — and near-counterproductive for the
  caregiver / vulnerable-diner audience, where unverified opinion beside a health
  decision is noise at best. So reviews stay an opt-in convenience, framed as
  opinion, never a verdict — consistent with the responsible-AI framing of
  [0005](0005-ethics-bias-and-responsible-ai.md).
- **We do not scrape or quote reviews.** Yelp / Google / TripAdvisor Terms of
  Service forbid automated page access. The only sanctioned way to show review
  text is a paid API, and it is not justified here: Yelp Fusion is not free
  ($229/mo base; review excerpts need the $299/mo Enhanced plan) and Google
  Places requires a billing account.
- **The city record is the authoritative source the score is built from, and it
  is free open data.** Linking to it lets an inspector or owner verify at the
  source — the same "let the user verify it" principle [0012] applied to cited
  facts, now applied to the score itself. It is keyless because a Socrata
  `explore/query` deep link resolves to the exact records with no credentials.
- **The record content is already shown in-app** per establishment (the
  inspection timeline renders full violations + inspector comments), so a
  per-inspection detail-page link isn't worth it — the records link earns its
  keep in the agent's compare/list/area flows, where the user is evaluating a set
  they can't easily reconstruct.

## Alternatives considered

- **Scrape/quote reviews, or use a paid reviews API (Yelp Fusion / Google
  Places)** — rejected: ToS and cost, and unverified opinion doesn't warrant it.
- **Keep the search-engine-intermediary review links** — rejected: a "Yelp
  reviews" link that is actually a DuckDuckGo URL is not a link to reviews.
- **Per-inspection city links in the detail-page inspection history** — rejected:
  the app already displays the full record better; the city grid is a slow,
  spreadsheet-style destination.
- **Key the records tool by `inspection_id` or restaurant name** — rejected: the
  agent never receives an `inspection_id`, and city `dba_name` matching is
  unreliable; `license_id` (already returned by `get_safety_score`) is the
  reliable key, so no tool/schema change was needed to feed it.

## Consequences

- **New tool `find_inspection_records`** (`agents/tools/find_inspection_records/`)
  wired into both runners (`run_local.py`, `entrypoint.py`); **`find_reviews`**
  links rewritten to direct-to-source (per-topic keyword scoping dropped — no
  source exposes a keyless topic-filtered review URL).
- **System prompt** (`agents/system_prompt.txt`) gains a city-records section:
  offer the link for a compare/list/area request, and pass **only non-null**
  `license_id`s (a venue with no record has none).
- **Eval** (`agents/eval/run_eval.py`): deterministic link-builder gates (a
  `--link-checks` flag, wired into CI — records-filters, review-link structure,
  injection safety), a live records-link resolution gate under `--links` (replays
  each link's SoQL against the Socrata `$query` API), and guardrail cases
  (records-not-a-verdict; reviews-vs-records distinction). Also fixes a
  guardrail-runner bug that blanket-skipped every tool-using case, and sharpens
  the no-record judge rubric so a generic caveat isn't mis-graded as a fabricated
  score.
- **No schema / data-artifact change**; no request-time inference
  ([0010](0010-agent-no-request-time-scoring-and-no-record.md) unchanged); no
  paid API and no scraping.

## Cross-references

- [0012](0012-agent-general-food-safety-education-with-cited-sources.md) — the
  sourcing / verifiability principle this extends (authoritative + cited;
  unverified content excluded).
- [0005](0005-ethics-bias-and-responsible-ai.md) — risk signal, not a verdict;
  the line reviews must never cross.
- [0010](0010-agent-no-request-time-scoring-and-no-record.md) — the agent's
  scoring behaviour, unchanged here.
- `agents/README.md` — the tool contracts for `find_reviews` and
  `find_inspection_records`.
