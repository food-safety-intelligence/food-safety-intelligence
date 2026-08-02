# Food Safety Agent — Local Run Guide

Run the full NLP → restaurant safety pipeline on your laptop.
No AgentCore deployment needed. The agent serves precomputed scores from
`scores.json`; the SageMaker stub is a dev-only scaffold, not the scoring path.

---

## What runs

```
Your query
  → Strands Agent (Nova 2 Lite via Bedrock)
      → find_restaurants   — Overpass/OSM, free, no key
      → get_safety_score   — precomputed batch scores from scores.json
      → explain_restaurant — scores.json + inspection_history.json (by license_id)
      → look_up_establishment — resolve a NAME to its authoritative record (general chat)
      → find_reviews       — third-party review links (opt-in; not a score input)
      → find_inspection_records — authoritative city-record links (compare/list/area)
      → food_safety_info   — general food-safety facts + authoritative citations
      → visualize_data     — sandboxed pandas/matplotlib chart of the city's scores
  → Plain-English ranked response
```

---

## Architecture & tool contracts

> Reference for the agent's design and each tool's input/output shape. Each
> behaviour is attributed inline to the PR that adds it — #55 (prompt, config &
> Bedrock Guardrail), #56 (explain/error-shape & location scope), #57 (name
> match), #58 (scoring) — and
> [decision record 0010](../docs/decisions/0010-agent-no-request-time-scoring-and-no-record.md).

### What the agent is

A **conversational search** assistant for predicted food-safety risk of food
establishments in the cities it covers — **Chicago, New York City, and Los
Angeles**. It is reachable as its own surface — the web app's `/chat` page and the
local runner — **not** tied to a specific restaurant detail page. A user asks in
natural language ("low-risk ramen near Lincoln Square"); the agent finds candidate
venues from OpenStreetMap, attaches the **precomputed** risk signal for the active
city, and returns a ranked, plain-English answer under the responsible-AI framing
in `system_prompt.txt`.

### Cities (multi-city, DR 0016)

The city is chosen by the frontend per request (a `[[city:nyc]]` / `[[city:la]]`
marker on the query; default Chicago) and rides the request via a contextvar — the
model never picks it. Every tool reads the active city and returns **only that
city's** data, and the request is framed in that city's terms:

- **Chicago** — inspections are Pass / Pass w/ Conditions / Fail with violation
  codes (no letter grade).
- **New York City** — a letter grade A/B/C from a points score (fewer points is
  cleaner).
- **Los Angeles** — a letter grade A/B/C from a 0-100 score (**higher** is cleaner,
  the opposite direction to NYC).

`agents/city_context.py` holds this per-city framing + scope text, shared by
`entrypoint.py` (deployed) and `run_local.py` (local / eval) so both frame a
request identically. Per-city data: a separate `scores.json` per city;
`find_inspection_records` links to Chicago's and NYC's open-data grids and LA
County's inspections page; `food_safety_info` surfaces the active city's local
health source.

### Core design rule — no request-time scoring

The agent **never calls the model at request time**. `get_safety_score` reports
only the precomputed batch scores written to `scores.json` (the project's
permanent batch-score-to-JSON design — see `CLAUDE.md` and
[0010](../docs/decisions/0010-agent-no-request-time-scoring-and-no-record.md)).
A venue the batch run does not cover returns an explicit **no-record** result
(no number), not an estimate. The agent therefore does discovery over the
establishments the batch run covers; widening coverage is a batch/data task, not
a request-time-inference one.

### Surfaces

| Surface | Entry | Notes |
|---|---|---|
| Local runner | `agents/run_local.py` | Strands + Bedrock; SageMaker stub by default |
| Deployed | `agents/entrypoint.py` + AgentCore | warms `scores.json` / `inspection_history.json` from S3 on cold start |
| Web app | `/chat` (`app/src/components/ChatInterface.tsx` → `/api/agent`) | the user-facing surface |

All three run the **same** eight `handler.py` files (and share `city_context.py`
plus the `scores_match.py` matcher).

### Tools

Each handler takes `handler(event, _ctx)`. Which tools apply depends on how the
user arrived and what identity you already hold:

- **Discovery** ("safe sushi near Wicker Park") — the ordered sequence
  `find_restaurants` → `get_safety_score` → `explain_restaurant` (for the
  lowest-risk few).
- **A named establishment in general chat** ("what's the address of Lou
  Malnati's?", "compare Giordano's and Pequod's") — skip `find_restaurants` and
  call `look_up_establishment` with the name(s). On a confident match, answer
  from it; chain to `explain_restaurant` (with the returned `license_id`) if the
  user wants the full inspection history. When several venues share the name it
  returns candidates to disambiguate first.
- **A scoped detail page** — the web app injects the exact `license_id` into the
  query (see `app/src/lib/agent-api.ts`), so answer with
  `explain_restaurant(license_id)` directly; do **not** re-resolve the venue by
  name or run the discovery sequence.
- **Optional, any mode** — `find_reviews` (only when asked what reviewers say),
  `find_inspection_records` (a link to the city's own records), and
  `food_safety_info` (a general food-safety question — does NOT run the
  restaurant sequence).
- **Charting the data** — `visualize_data` (when the user asks to plot / graph /
  visualize the active city's data). The model writes pandas + matplotlib code
  that a **network-isolated sandbox** runs against the precomputed `scores.json`;
  the tool returns a rendered image + the exact script as an `eatelligence-chart`
  block the web app renders inline. A chart is an aggregate of the batch scores,
  never a new prediction (decision record 0019). See [0019](../docs/decisions/0019-agent-data-visualization.md).

**Availability & plurality** — which tools apply in each mode, and whether one
call handles several establishments or the agent calls the tool once per venue:

| Tool | Discovery | Named (general) | Scoped page | One call handles… |
|---|:-:|:-:|:-:|---|
| `find_restaurants` | ✓ | — | — | a whole area (returns many) |
| `get_safety_score` | ✓ | — | — | **a list** of restaurants |
| `look_up_establishment` | — | ✓ | — | **a list** of names |
| `explain_restaurant` | ✓ (few) | ✓ (after match) | ✓ (the pinned id) | one venue (per `license_id`) |
| `find_inspection_records` | ✓ | ✓ | ✓ | **a set** of `license_id`s / an area |
| `find_reviews` | on ask | on ask | on ask | one venue (per place) |
| `food_safety_info` | ✓ | ✓ | ✓ | one general question |
| `visualize_data` | on ask | on ask | on ask | one chart of the city's data |

The batch tools (`get_safety_score`, `look_up_establishment`,
`find_inspection_records`) take a list, so a "compare A and B" request resolves
in one call instead of a call per venue. `explain_restaurant` and `find_reviews`
are single-venue — the agent calls them once per establishment. On a scoped page
the strongest identity signal (the exact `license_id`) is already in hand, so the
fuzzy tools are a downgrade there: `explain_restaurant` is a direct lookup with
no mismatch risk and the full history.

**When the agent asks the user (vs. answers directly)** — every tool is a
read-only lookup or link builder (no writes, nothing irreversible), so the agent
never asks "are you sure?" for a side effect. It pauses for user input in only
four cases:

- **Disambiguation (must ask).** `look_up_establishment` returns
  `status="ambiguous"` when several venues share a name (e.g. many "Subway"s).
  The agent lists the `candidates` by address / neighborhood, asks which one, and
  only then continues — chaining to `explain_restaurant` with the chosen
  `license_id` for detail. It never guesses one.
- **A location it can't place (must ask).** When `find_restaurants` can't resolve
  the area (`reason="location_not_recognized"`), the agent says it couldn't
  locate that area and asks for a major neighborhood name or lat/lon — it does
  **not** silently widen to a whole-city search. (A discovery query with *no*
  area given does default to a whole-city search rather than asking.)
- **Opt-in before an optional action (offer, act only on "yes").** Diner reviews
  are never volunteered: the agent may add one short offer to pull them and calls
  `find_reviews` only if the user accepts. Reviews stay separate from the risk
  signal.
- **Out-of-scope / personal-medical (decline, then offer).** For a request
  outside scope (recipes, code, another city) or a personal medical question, the
  agent declines and offers what it *can* do ("I can look up an establishment's
  predicted risk, or answer a general food-safety question with a cited source —
  want me to?").

What the agent does **not** do: ask the user to confirm an *unambiguous* match
(it states the resolved `dba_name` + `address` inline so a wrong match is
visible, then answers), or ask the user to supply a fact a tool can look up (it
looks it up rather than asking "what's the address?"). These behaviours are set
in `system_prompt.txt`.

**1. `find_restaurants`** — OpenStreetMap/Overpass lookup (no key).

- *Input*: `neighborhood` | (`lat`,`lon`), `radius_km`, `cuisine`, `limit`.
- *Output*: `list` of restaurant stubs sorted by distance — each
  `{osm_id, name, address, lat, lon, cuisine, opening_hours, phone, website, dist_km}`.
- *On failure*: returns a top-level `{"error": ..., "reason": ...}` object (a
  dict, not a list with a fake restaurant), so a downstream tool never reads
  `osm_id` off a malformed element. `reason` is `"location_not_recognized"` when
  the requested area is not a recognised neighborhood in the active city — it is
  **not** silently widened to a whole-city search — or `"directory_unavailable"`
  on an Overpass outage *(#56)*.

**2. `get_safety_score`** — attaches the precomputed risk signal.

- *Input*: `{"restaurants": [ ...find_restaurants stubs... ]}`.
- *Output*: `list` ordered by predicted risk ascending; no-record venues sort
  last. Each item:

  | Field | Type | Notes |
  |---|---|---|
  | `osm_id`, `name`, `address`, `lat`, `lon`, `cuisine` | — | passthrough identity |
  | `risk_score` | `float \| null` | calibrated probability `[0,1]`; **`null` when no record** *(null: #58)* |
  | `risk_tier` | `str \| null` | Low / Moderate / Elevated / High; `null` when no record |
  | `shap_drivers` | `list` | `[]` when no record |
  | `matched_scores_json` | `bool` | `true` only for a batch-run match |
  | `status` | `str` | `"scored"` \| `"no_inspection_record"` *(new: #58)* |
  | `stub` | `bool` | `true` for the `-1.0` mock-data sentinel in `scores.json` |
  | `stub_note` | `str \| null` | human-readable note explaining a preliminary/stub score; `null` for a real published score |
  | `license_id`, `percentile_rank`, `trend`, `neighborhood` | `… \| null` | from the matched record; `null` when no record |

  Matched venue → published batch score/tier/drivers directly. Unmatched venue →
  no-record (`risk_score`/`risk_tier` `null`, `status="no_inspection_record"`),
  no model call.

**3. `explain_restaurant`** — full detail for one venue by `license_id`.

- *Input*: `{"license_id": "..."}` (a license the agent already matched).
- *Output*: identity + score fields, `top_drivers`, `model_note`, and:
  - `inspection_history`: most-recent-first, max 10, **sorted in the handler** so
    it does not depend on upstream order *(sort + guard: #56)*.
  - `inspection_summary`: `{total, pass, fail, pass_w_conditions, other,
    last_date, days_since_last}`. The `other` bucket holds non-outcome results
    (Out of Business / No Entry / Not Ready / Business Not Located) so they are
    **not** miscounted as passes *(the `other` bucket: #56)*.

**4. `look_up_establishment`** — resolve a NAME to its authoritative record
(general chat; no `find_restaurants` step).

- *Input*: `{"names": ["Lou Malnati's", "Pequod's"]}` — batches all names in one
  call (a single `"name"` is also accepted).
- *Output*: `list`, one result per name (order preserved), each
  `{query, status, match, candidates, truncated}`:
  - `status="matched"`: `match` is the authoritative record — `dba_name`,
    `address` (`address_source="city_inspection_record"`), `zip`, `facility_type`,
    `neighborhood`, `risk_score`/`risk_tier`/`trend`, brief `top_drivers`,
    `last_inspection` `{date, result}`, and `license_id` (chain to
    `explain_restaurant` with it for the full history).
  - `status="ambiguous"`: several venues share the name — `candidates` (capped at
    8, `truncated: true` if more) each carry `license_id`, `dba_name`, `address`,
    `neighborhood`, `zip`, `risk_tier` so the agent asks which one. It never
    guesses one.
  - `status="no_inspection_record"`: no city record for that name — `match` is
    `null` and the agent invents no address or score.
- *Boundary — authoritative, never fabricated*: the matched `address` is the
  city's own record (unlike an OpenStreetMap-only address), so the agent may
  state it as the address on file. This is the general-chat counterpart to the
  scoped page's `explain_restaurant(license_id)`.

**5. `find_reviews`** — optional third-party diner reviews (only on request).

- *Input*: `{"name": "...", "address": "...", "topics": [...]}` — `topics` is a
  subset of `cleanliness`, `pests`, `food_quality`, `illness` (empty = all).
- *Output*: `{name, topics, review_links, disclaimer}`. `review_links` are
  attributed Yelp / Google Maps / TripAdvisor deep links — each to that source's
  own search for the business — the **user** clicks through to.
- *Boundary — reviews are not a model feature*: the tool **never scrapes or
  stores** Yelp / Google pages (their Terms of Service forbid automated page
  access); it only builds links the user follows. Reviews are
  unverified opinion and are **NOT** an input to the risk score — every response
  carries `disclaimer`, and the prompt forbids using a review to set or change a
  score or tier.

**6. `find_inspection_records`** — authoritative city-record link for a set of
establishments in the active city (opt-in; compare / list / area).

- *Input* (exactly one filter): `{"license_ids": [...]}` for named places (the
  **non-null** `license_id`s that `get_safety_score` returned — each city's native
  id: Chicago license number, NYC CAMIS), `{"zip": "..."}` for a ZIP, or
  `{"lat":…, "lon":…, "radius_m":…}` for a radius.
- *Output*: `{url, mode, truncated, note}`. For **Chicago and NYC** (both on
  Socrata) it is a deep link into that city's open-data query grid filtered to
  those records (`` `license_` `` / `` `camis` `` `IN (…)`, `` `zip` `` /
  `` `zipcode` `` `=…`, or `within_circle(…)`); enumerated id lists cap at 25 (URL
  length) → `truncated: true`. **LA** left Socrata (bulk CSV, no queryable API), so
  it returns `mode: "city_page"` — LA County Public Health's inspections page (a
  lookup landing page, not a pre-filtered grid).
- *Boundary — provenance, not a feature*: like `find_reviews` the tool **never
  fetches** — it only builds a URL the user clicks. But this is the city's **own**
  inspection data (the source behind the score), not third-party opinion, so it
  carries no disclaimer. It complements the agent's own comparison; it does not
  replace it.

**7. `food_safety_info`** — general food-safety education with cited sources.

- *Input*: `{"query": "...", "topics": [...]}` — `query` is the user's general
  question; `topics` is an optional explicit subset of the topic registry keys
  (e.g. `salmonella`, `cooking_temperatures`, `at_risk_groups`), otherwise topics
  are matched from the query text.
- *Output*: `{query, topics, info, disclaimer}`. `info` is a list of
  `{topic, title, summary, sources}`; each `sources` entry is `{name, url}`.
- *Sourcing — verifiable, allow-listed*: every `summary` is a short paraphrase of
  an **authoritative public health source** — national (CDC, FDA, USDA FSIS,
  FoodSafety.gov, WHO, NIH MedlinePlus, a recognised nonprofit) plus each covered
  city's **local** public health (Chicago / Illinois / Cook County + the Chicago
  Data Portal, NYC Health, and LA County Public Health). The tool takes the active
  `city`: its city-aware `local` topic surfaces **only that city's** local source
  (an NYC user never sees a Chicago source), while the national facts are
  city-independent. Each entry ships the source link it came from; links come
  **only** from a curated `ALLOWED_DOMAINS` allow-list — no news outlets, no open
  web search — so a citation can never point off-list. The prompt requires the agent
  to state statistics only from the returned summary and cite the returned link,
  keeping the citation true.
- *Boundary — education, not advice*: every response carries `disclaimer`
  (education only, not medical advice, not specific to any restaurant's score).
  Personal medical questions are steered to a professional by the prompt and the
  Bedrock guardrail.

### Safety layers

Independent layers keep the agent on-task and prevent fabrication:

1. **Prompt guardrails** (`system_prompt.txt`, #55) — risk-signal framing; scope
   (restaurant lookups in the active city + general food-safety education only;
   decline cities we don't cover / recipes / code / chit-chat; ignore
   prompt-injection); no number without a
   tool result; cite the returned source for any general fact; no personalised
   medical/legal advice; and a prediction-vs-verdict caveat on every response.
   The model runs at `temperature=0.2`.
2. **Bedrock Guardrail** (#55) — a platform-level guardrail attached to the
   model: two denied topics only — *personalised* medical advice and legal advice
   (general food-safety education is deliberately allowed) — plus a prompt-attack
   filter. There is deliberately NO catch-all "off-topic" topic: a
   negatively-defined one over-matches and blocks core risk lookups, so off-topic
   requests are declined by the system prompt instead. A contextual-grounding +
   relevance policy is configured but is NOT active as wired (Strands'
   `BedrockModel` does not tag tool outputs as grounding sources), so it does not
   block low-grounding answers — anti-fabrication rests on the system prompt and
   tool-level grounding. The denied-topic and prompt-attack filters are enforced
   by Bedrock, not by model compliance.
3. **Tool-level grounding** (#56, #58) — the tools never hand the model a value
   it shouldn't have: unmatched venues return no score (#58), tool failures return
   an explicit error object the prompt knows how to relay (#56), and
   `food_safety_info` can only cite URLs from a curated allow-list.

### Example: a query end to end

Putting the architecture together — here is what a real request looks like from
the user's side and what the agent does under the framing above.

**1. Discovery — "low-risk sushi near Wicker Park" (Chicago `/chat`):**

1. `find_restaurants(neighborhood="Wicker Park", cuisine="sushi")` → candidate
   venues from OpenStreetMap (name, address, coordinates).
2. `get_safety_score([…those venues…])` → each is matched to the city's
   `scores.json`; a match returns its **precomputed** `risk_score` / `risk_tier` /
   drivers **and the authoritative city address**, and the list comes back sorted
   lowest-risk first. A venue with no match returns a no-record result (no number).
3. `explain_restaurant(license_id)` for the 2-3 lowest-risk venues → full SHAP
   drivers + inspection history and summary.
4. The agent replies with a numbered list, lowest predicted risk first — each
   line: name, the city-record address, risk tier, a 1-2 sentence driver summary —
   and closes with the prediction-not-a-verdict caveat. No model ran at request
   time; every number came from a tool.

**2. A named establishment — "what's the address of Lou Malnati's?":**

- `look_up_establishment(["Lou Malnati's"])`. One match → the agent states the
  identity from the city record ("Lou Malnati's Pizzeria, 805 S State St") and
  answers, no confirmation step; if the user then wants its history it chains to
  `explain_restaurant` with the returned `license_id`.
- Several venues share the name ("Subway") → the lookup returns `ambiguous`
  candidates and the agent lists them by address and **asks which one** first (see
  "When the agent asks the user" above).

**3. A scoped detail page — "when was it last inspected?":** the web app injects
the venue's exact `license_id` into the query, so the agent skips discovery and
calls `explain_restaurant(license_id)` directly, answering from that venue's
inspection history.

Across all three the same invariants hold: the active city scopes every lookup,
no score is computed at request time, and **no establishment fact is stated
without a tool result behind it** — which is exactly what the evaluation below
checks.

### Evaluation

A behavioural eval harness (`agents/eval/`) exercises the guardrails on
adversarial prompts — off-topic, "is X safe?", a venue with no record, a
cross-city / out-of-scope location, a general food-safety question (must answer
WITH a cited source), a personal medical question (must steer to a professional),
per-city grade framing, and a tool outage — and checks the response follows the
rules (no yes/no verdict, no invented score, scope refusal, cited general facts,
graceful failure).

**Tone & appropriateness.** The suite also checks *how* the agent answers, not
just *what* it answers. There is **one tone baseline for every user** — general
diner, caregiver, restaurant owner alike — and it is a universal guarantee, not a
per-persona rule: calm and non-alarmist, empathetic to a sick or vulnerable user,
and never shaming or accusatory about a venue or its owner. What varies by persona
is *content* (a vulnerable diner gets lower-risk options and hazard drivers first),
never the register. On top of tone it covers **fairness** (no cuisine / ethnicity
/ neighbourhood stereotype — risk is per establishment, matching the model side
where cuisine was rejected as a feature on fairness grounds), **no personal legal
ruling** (decline "can I sue them?", point to reporting channels, never call a
venue negligent), and **false-premise resistance** (it will not confirm a verdict
it never gave). Each case carries both a cheap heuristic net (`require_any` /
`forbid`) and an LLM-judge `rule`; the judge (`--judge`) is the robust grader.
Note the tone cases respect the output guardrail's contract: for a personal health
situation the agent gives general facts and declines the personal ruling, so these
cases do **not** require a "see your care team" steer (that phrasing is blocked and
truncates the reply — see `system_prompt.txt`).

It also runs deterministic gates with no Bedrock:
- **faithfulness** (`--faithfulness`) — `get_safety_score` relays `scores.json`
  exactly (same score / tier / license_id / trend, no recompute);
- **authoritative-address relay** (`--identity`) — a matched venue returns the
  **city record's** address, not the OpenStreetMap stub's (the anti-hallucination
  guard: it feeds a wrong address, matched by name+coords, and asserts the tool
  overrides it);
- **name lookup** (`--lookup`) — a name resolves to the right record, and a
  nonsense name returns a clean no-record result (never a fabricated one);
- a citation **allow-list** check (every citable URL is https + on the allow-list);
- opt-in via `--links`, a **live link-resolution** check that fetches every
  citation URL to catch dead links.

**In CI:** the **Agent (deterministic checks)** job (`.github/workflows/ci.yml`)
runs the no-Bedrock, no-network parts on every PR — each tool's pytest suite (as
separate invocations, since the tool dirs share a `handler` module name and
collide in one run) plus `run_eval.py --self-test`, `--faithfulness` (vs the
committed `scores.json`), `--identity`, `--lookup`, and `--citations`. `--self-test`
validates the checker for every guardrail case, including the tone / fairness /
legal / robustness ones, against canned pass/fail responses — so their
*deterministic* coverage is gated on every PR for free. The Bedrock-graded
`--judge` guardrail suite (the robust grader for tone, which needs the live model)
and the network `--links` check stay **manual** (paid; run from the SageMaker
execution role via the `eval-agent` skill).

### Note on the SageMaker stub

`get_safety_score` does **not** score at request time — it serves the precomputed
batch scores in `scores.json` (see
[0010](../docs/decisions/0010-agent-no-request-time-scoring-and-no-record.md)).
`sagemaker_stub.py` is a dev-only scaffold, not the scoring path. Several parts of
this guide describe that scaffold for completeness — the pipeline diagram note,
the `SAGEMAKER_*` environment variables, the "Run the stub unit tests" command,
and the two stub sections near the end — and none of them is the live scoring
mechanism. Widening score coverage is a batch/data task (re-run the Python
pipeline so new venues land in `scores.json`), never a request-time endpoint call.

---

## Prerequisites

### 1. AWS credentials

The only thing that needs AWS is the Bedrock call to Nova 2 Lite.
The fastest way on a Mac:

```bash
aws configure
# AWS Access Key ID: <your key>
# AWS Secret Access Key: <your secret>
# Default region name: us-east-1
# Default output format: json
```

Or set env vars directly:
```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_REGION=us-east-1
```

### 2. Enable Nova 2 Lite in Bedrock console

1. Open [Bedrock Model Access](https://us-east-1.console.aws.amazon.com/bedrock/home?region=us-east-1#/modelaccess)
2. Find **Amazon Nova Lite** → click **Request access** (instant, no approval needed)
3. Wait ~30 seconds for status to show **Access granted**

### 3. Python deps (already installed in your venv)

```bash
# strands-agents and boto3 are already present — verify:
python -c "from strands import Agent; import boto3; print('OK')"
```

If either is missing:
```bash
pip install strands-agents boto3
```

---

## Run it

### Interactive REPL (recommended for testing)

```bash
python agents/run_local.py
```

You'll see:
```
╔══════════════════════════════════════════════════════════╗
║   Food Safety Intelligence — Local Agent (Strands)       ║
╠══════════════════════════════════════════════════════════╣
║  Model        : Nova 2 Lite (us-east-1)                  ║
║  SageMaker    : STUB (deterministic hash)                 ║
║  scores.json  : FOUND ✓                                   ║
╠══════════════════════════════════════════════════════════╣
║  Try: 'safe sushi near Wicker Park'                       ║
╚══════════════════════════════════════════════════════════╝

You: _
```

### One-shot query

```bash
python agents/run_local.py "safe sushi near Wicker Park"
python agents/run_local.py "low risk ramen near Lincoln Square, my mom is immunocompromised"
python agents/run_local.py "thai restaurant near the loop, no failed inspections"
python agents/run_local.py "pizza wicker park low risk open now"
```

### Run the stub unit tests (no AWS needed)

These cover the dev-only stub scaffold, not the scoring path (which serves
precomputed `scores.json`).

```bash
python -m pytest agents/tools/get_safety_score/test_sagemaker_stub.py -v
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `AWS_REGION` | `us-east-1` | Bedrock region |
| `SCORES_JSON_PATH` | `app/public/data/scores.json` | Precomputed batch scores — the scoring path |
| `HISTORY_JSON_PATH` | `app/public/data/inspection_history.json` | Inspection history file |
| `SAGEMAKER_USE_STUB` | `true` | Dev-only stub-scaffold toggle; not the scoring path (scores come from `scores.json`) |
| `SAGEMAKER_ENDPOINT` | — | Dev-only; unused by the precomputed-score path |

Set them inline for a one-off test:
```bash
SCORES_JSON_PATH=/path/to/scores.json \
python agents/run_local.py "ramen near wicker park"
```

---

## The SageMaker stub (dev-only scaffold)

The stub lives in `agents/tools/get_safety_score/sagemaker_stub.py`. It is a
development scaffold only — **not** the scoring path. `get_safety_score` serves
the precomputed batch scores in `scores.json`, and the agent never calls a model
at request time (see
[0010](../docs/decisions/0010-agent-no-request-time-scoring-and-no-record.md)).

To widen score coverage, re-run the Python batch pipeline so the new venues land
in `scores.json` — there is no live endpoint to switch on.

---

## What the stub scores look like

These describe the dev-only stub scaffold, not the precomputed scores the agent
serves. Stub scores are derived from `md5(name + address)` → `Beta(1.5, 8)`
distribution, which roughly matches the batch model's ~10% High-risk positive
rate; the same restaurant always gets the same stub score across runs.

A stub result carries a `stub_note` so the agent can flag it, for example:
> "Score from stub — SageMaker endpoint not yet configured."

---

## Deploying to AgentCore

The agent runs as a single AgentCore **CodeZip** runtime, defined by
`agentcore-deploy/agentcore/agentcore.json` (entrypoint `entrypoint.py`,
codeLocation `agents/`) and shipped by the CDK in `agentcore-deploy/agentcore/cdk`.
Deploy with the wrapper script (defaults: region `us-west-2`, the deploy account):

```bash
# from the repo root, with AWS creds for the deploy account
./scripts/deploy_aws.sh [region] [account-id]
```

This zips `agents/` (entrypoint + the eight `tools/` handlers + `system_prompt.txt` +
`city_context.py` + `scores_match.py`), deploys/updates the `foodsafetyagent` runtime, and points the
`food-safety-agent-proxy` Lambda at it — the request path is CloudFront `/api/agent`
→ ALB → that Lambda → the runtime. The runtime warms each covered city's precomputed
`scores.json` from S3 at startup and reads it for scoring; it never calls the model
for a score (the batch-score-to-JSON contract). `run_local.py` runs the same eight
`handler.py` files locally via Strands.

`harness.yaml` describes a different, per-tool-Lambda harness and is **not** the
wired deploy path.

---

## Troubleshooting

**`ResourceNotFoundException` from Bedrock**
→ Nova 2 Lite not enabled. Go to [Bedrock Model Access](https://us-east-1.console.aws.amazon.com/bedrock/home?region=us-east-1#/modelaccess) and enable it.

**`NoCredentialsError`**
→ Run `aws configure` or set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.

**`scores.json: NOT FOUND — using mock`**
→ The Python pipeline hasn't run yet. The agent works fine with the mock;
  scores will be from the 8-restaurant mock fixture, not the full 28k dataset.

**`Overpass API unavailable`**
→ The public Overpass endpoint is rate-limited. Wait 30 seconds and retry,
  or reduce `limit` to 5. For production, self-host or use overpass.kumi.systems.

**`ModuleNotFoundError: No module named 'strands'`**
→ `pip install strands-agents`
