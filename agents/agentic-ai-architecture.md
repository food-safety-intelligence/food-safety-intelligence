# Agentic AI Architecture — Food Safety Intelligence
## NLP Chat Agent → Predicted Restaurant Risk + Food-Safety Education

**Model**: Amazon Nova 2 Lite (`us.amazon.nova-2-lite-v1:0`) via Amazon Bedrock
**Runtime**: Amazon Bedrock AgentCore Runtime (Strands Agents), single CodeZip deploy
**Restaurant data**: OpenStreetMap via Overpass API (free, no key)
**Safety scores**: existing batch pipeline `scores.json` (never a request-time model call)
**Citations**: curated public-health allow-list (CDC, FDA, USDA FSIS, WHO, NIH, city/state health)
**Cities**: Chicago (default), New York City, Los Angeles
**Status**: As-built (Phase 2). This document tracks the deployed agent in `agents/`.

---

## 1. Why This Approach

| Concern | Decision |
|---|---|
| Keep costs low | **Amazon Nova 2 Lite** — AWS-native, ~$0.30/M input tokens (US East), one of the cheapest tool-use models. No cross-provider billing. |
| Restaurant list | **Overpass API (OSM)** — free, no API key, covers Chicago / NYC / LA. Returns `amenity=restaurant`/`cafe`/`fast_food` nodes and ways with name, cuisine, address, and coordinates. |
| No extra infra for search | Overpass handles geo + text queries at runtime from static per-city neighborhood tables; no OpenSearch cluster needed. |
| Safety signal | Existing batch pipeline scores (`scores.json`) — read directly, never re-scored at request time. |
| General food-safety Q&A | A curated, cited topic catalogue (`food_safety_info`) over an allow-list of authoritative public-health sources — no open web search. |
| AWS-native deployment | **AgentCore Runtime** — one CodeZip artifact (the Strands agent + its in-process tools), fronted by an ALB → Lambda proxy. |

**Note on "thinking":** an earlier design assumed Nova 2 Lite exposed adaptive
extended-thinking budgets. It does not — those fields are only valid on Nova
Premier (see the note in `agents/harness.yaml`). Nova 2 Lite performs multi-step
tool-use reasoning natively. The deployed model is configured with a fixed
`temperature=0.2` and `max_tokens=4096` (`agents/entrypoint.py`), because this is
a factual lookup-and-report task where sampling variance only adds room for
fabricated scores or names.

---

## 2. Cost Estimate (Nova 2 Lite)

A typical agentic turn (NLP query → 2–3 tool calls → reasoned response):

| Component | Tokens | Cost |
|---|---|---|
| System prompt + conversation context | ~800 input | $0.00024 |
| User query + tool results (JSON) | ~1,500 input | $0.00045 |
| Final response | ~400 output | $0.00048 |
| **Per query total** | | **≈ $0.0012** |

1,000 queries/day ≈ **$1.20/day**. Cost is bounded by the fixed `max_tokens=4096`
ceiling per turn and by the proxy's 500-character query cap and 20-message /
8,000-character history bound, which stop a client from padding the context
window.

---

## 3. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         Browser (Next.js)                             │
│   Floating chat panel — sends { query, session_id, history }          │
│   Optional [[city:...]] / [[persona:...]] markers prepend the query   │
└────────────────────────────────│─────────────────────────────────────┘
                                 │ HTTPS POST (JSON)
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│        Public ALB  →  Lambda proxy  (agents/lambda_proxy/handler.py)  │
│   Validates JSON, caps query at 500 chars, bounds history, mints a    │
│   session id, signs InvokeAgentRuntime, parses the SSE stream back to │
│   a single { "result": string }                                       │
└─────────────────────────────────┬────────────────────────────────────┘
                                  │ invoke_agent_runtime (IAM-signed)
                                  ▼
┌──────────────────────────────────────────────────────────────────────┐
│     Amazon Bedrock AgentCore Runtime — single CodeZip (Strands)       │
│                                                                        │
│   entrypoint.invoke(payload):                                         │
│     • _warm_data_files()  — lazy S3 → /tmp download on first request  │
│     • _extract_city / _extract_persona  — strip markers, set context  │
│     • _build_agent(history, persona)  — FRESH Agent per request       │
│                                                                        │
│   ┌──────────────────────────────────────────────────────────────┐   │
│   │      Orchestrator — Amazon Nova 2 Lite (us.amazon.nova-2-...)  │   │
│   │      temperature 0.2, max_tokens 4096, optional Guardrail      │   │
│   └──┬────────┬────────┬────────┬─────────────┬─────────────┬─────┘   │
│      ▼        ▼        ▼        ▼             ▼             ▼          │
│  find_     get_     explain_  find_       find_          food_        │
│  restaurants safety_ restaurant reviews  inspection_    safety_       │
│            score                          records        info         │
│      │        │        │        │             │             │         │
│      ▼        ▼        ▼        ▼             ▼             ▼          │
│  Overpass  scores.  scores.+  deep links  Chicago Data  curated       │
│  API (OSM) json     history   (Yelp/      Portal query  citation      │
│            /tmp     /tmp      Google/…)   URL builder   catalogue     │
└──────────────────────────────────────────────────────────────────────┘

Cold start: scores.json + inspection_history.json (Chicago required; nyc/, la/
optional) are downloaded from s3://food-safety-intelligence-data/web-app-data/…
into /tmp on the FIRST invocation, not at import (the ~68 MB download would blow
AgentCore's 30 s init budget). The tools read the local /tmp copy per query.
```

The tools run **in-process** inside the one AgentCore Runtime artifact (they are
`@tool`-wrapped Python functions in `entrypoint.py`), not as separate per-tool
Lambdas. The only Lambda is the front-door proxy. The diagram shows the discovery
path; two more tools sit outside it — `look_up_establishment`, used in general chat
to resolve a named venue directly against the city data (see §6), and
`visualize_data`, the sandboxed chart tool (see Tool 8).

---

## 4. Safety Scores — Batch Pipeline, No Request-Time Model

`get_safety_score` and `explain_restaurant` read the **precomputed** `scores.json`
(and `inspection_history.json`) that the Python batch pipeline already publishes —
the same files the web app reads. **The model is never called at request time.**
This is the project's permanent batch-score-to-JSON design.

- A venue that matches a published record returns that record's `risk_score`,
  `risk_tier`, and `top_drivers` (SHAP) directly from `scores.json`.
- A venue NOT covered by the batch run has no city inspection record to speak to.
  It returns an explicit **no-record** result (`risk_score: null`,
  `status: "no_inspection_record"`) rather than a request-time estimate — with no
  inspection history the only features are all zero, so a model score would carry
  no per-venue meaning. The agent reports "no inspection record found" instead of
  inventing a number.

A vestigial `agents/tools/get_safety_score/sagemaker_stub.py` remains in the tree
from an earlier design that scored at request time. **It is not on the request
path** — the live `handler.py` neither imports nor calls it. Any future move to
request-time SageMaker inference would be a deliberate departure from the
batch-score-to-JSON contract, not a wiring detail.

### 4.1 Matching OSM venues to city records

OSM and the city inspection dataset share no common id, so `get_safety_score`
matches heuristically, in `handler.py`:

1. **Address fuzzy-match** — normalise the address (uppercase, expand `STREET→ST`
   etc.), look up the record bucket for that address (exact, then a
   `difflib.get_close_matches` fuzzy key at cutoff **0.72**).
2. **Name disambiguation** — when 2+ records share one address (food courts,
   malls, airports), the best `dba_name` match must clear a name cutoff (**0.6**)
   before a score attaches. A single-occupancy address skips the name gate.
3. **Name + geographic fallback** — when OSM has no usable street address, recover
   the venue by `lat/lon` within ~250 m (`_GEO_RADIUS_DEG`) plus a name match. A
   confident wrong score is worse than a miss (ethics decision record 0005), so an
   unresolved venue returns no-record rather than a neighbour's score.

---

## 5. Data Sources

### 5.1 Restaurant List — Overpass API (OpenStreetMap)

**Endpoint**: `https://overpass-api.de/api/interpreter` (POST, no API key).
**Coverage**: Chicago, New York City, Los Angeles.

`find_restaurants` builds an Overpass QL query at runtime from the active city's
geography tables and the agent's parsed intent (neighborhood, cuisine, radius). It
queries `amenity=restaurant` (node + way) plus `amenity=cafe` and
`amenity=fast_food` nodes within the bounding box, requesting `out center tags`
so ways return a single centre coordinate.

```
# Example: "ramen near Wicker Park" (Chicago)
[out:json][timeout:15];
(
  node["amenity"="restaurant"]["cuisine"~"ramen|japanese",i](41.90,-87.68,41.92,-87.66);
  way ["amenity"="restaurant"]["cuisine"~"ramen|japanese",i](41.90,-87.68,41.92,-87.66);
  node["amenity"="cafe"]["cuisine"~"ramen|japanese",i](41.90,-87.68,41.92,-87.66);
  node["amenity"="fast_food"]["cuisine"~"ramen|japanese",i](41.90,-87.68,41.92,-87.66);
);
out center tags 20;
```

Fields returned per venue: `osm_id`, `name`, `address`, `lat`, `lon`, `cuisine`,
`opening_hours`, `phone`, `website`, and `dist_km` (distance from the query
centroid). Results are de-duplicated by name+location and sorted by distance.

**Neighborhood → bbox**: static per-city Python tables
(`chicago_neighborhoods.py`, `nyc_neighborhoods.py`, `la_neighborhoods.py`) map a
named area to a bounding box and centroid. An unrecognised neighborhood returns a
`location_not_recognized` error object rather than silently falling back to a
whole-city search; explicit out-of-city coordinates are rejected too.

### 5.2 Safety Score — Existing Batch Pipeline

`get_safety_score` and `explain_restaurant` read `scores.json` /
`inspection_history.json` from `/tmp` (warmed from S3 on cold start; see §3). The
match runs inside the tool handler, so no OSM data touches the ML model. The
batch scores stay the single source of truth; unmatched venues surface honestly as
no-record.

### 5.3 General Food-Safety Facts — Curated Allow-List

`food_safety_info` answers general questions from a vetted topic catalogue, each
entry shipping a short paraphrased summary AND the source link it came from. Every
citation host must be on a curated `ALLOWED_DOMAINS` allow-list — CDC, FDA, USDA
FSIS, FoodSafety.gov, WHO, NIH MedlinePlus, the Partnership for Food Safety
Education, and Chicago / Illinois / Cook County public health plus the Chicago
Data Portal. **No open web search, no news sources.** The agent must state a
statistic only if it is in the returned summary, and cite only the returned links.

---

## 6. Agent Tools — Specification (eight tools)

All eight are `@tool`-wrapped functions in `agents/entrypoint.py`, each delegating
to `agents/tools/<name>/handler.py`. The active city rides through a contextvar,
not a model argument. The name/address normalisation and fuzzy-matching shared by
the scoring tools lives in `agents/scores_match.py`; the per-city framing text is
in `agents/city_context.py` (shared by the deployed `entrypoint.py` and the local
`run_local.py`).

### Tool 1: `find_restaurants` → Overpass / OSM

```python
# Input (active city injected from context, not chosen by the model)
{ "neighborhood": "Wicker Park", "lat": 0.0, "lon": 0.0,
  "radius_km": 1.0, "cuisine": "sushi", "limit": 20 }

# Output: list[RestaurantStub] sorted by distance, or {"error", "reason"}
[ { "osm_id": "12345678", "name": "Arami",
    "address": "1829 W Chicago Ave, Chicago, IL 60622",
    "lat": 41.8957, "lon": -87.6742, "cuisine": "japanese;sushi",
    "opening_hours": "...", "phone": "...", "website": "...", "dist_km": 0.3 } ]
```

Always called first, before `get_safety_score`.

### Tool 2: `get_safety_score` → precomputed `scores.json`

```python
# Input
{ "restaurants": [ {"osm_id","name","address","lat","lon","cuisine"} ] }

# Output: ordered by predicted risk ascending; no-record venues sort last
[ { "osm_id": "12345678", "name": "Arami", "address": "...",
    "license_id": "2543871",            # null if no match
    "risk_score": 0.09,                 # null if no match
    "risk_tier": "Low",                 # Low | Moderate | Elevated | High | null
    "trend": "stable",                  # improving | stable | worsening
                                        #   | "not enough inspection history"
    "percentile_rank": 8, "shap_drivers": [ ... ],
    "matched_scores_json": true,
    "status": "scored" } ]              # or "no_inspection_record"
```

Reads the batch score directly; no model call. On a match the returned `address`
is the **city record's authoritative address**, not the OSM stub's (an
anti-hallucination guard). See §4.

### Tool 3: `explain_restaurant` → `scores.json` + `inspection_history.json`

```python
# Input
{ "license_id": "2543871" }

# Output (abridged)
{ "found": true, "license_id": "2543871", "dba_name": "ARAMI",
  "address": "...", "neighborhood": "...", "facility_type": "...", "zip": "...",
  "risk_score": 0.09, "risk_tier": "Low",
  "trend": "stable", "trend_slope": -0.002, "percentile_rank": 8,
  "top_drivers": [ {"feature","label","detail","value","shap","direction","magnitude"} ],
  "inspection_summary": { "total": 6, "pass": 4, "fail": 1,
                          "pass_w_conditions": 1, "other": 0,
                          "last_date": "2025-11-12", "days_since_last": 211 },
  "inspection_history": [ {"date","result","headline", ...} ],  # newest first, max 10
  "model_note": "Risk score is a 180-day forward prediction ..." }
```

Called for the 2–3 lowest predicted-risk results. Pure data retrieval, no model call.

### Tool 4: `look_up_establishment` → authoritative record by name

For general chat where the user names a place directly ("what's the address of
Lou Malnati's?", "compare Giordano's and Pequod's") — no `find_restaurants` step.
It resolves each name against the **active city's** inspection data and returns
that establishment's authoritative record (address, ZIP, facility type, last
inspection, risk score / tier / trend, `license_id`) straight from the data, so
the model never states a fact about a named venue from memory (the
anti-hallucination guard behind decision record on establishment lookup). Takes
all names in one call.

```python
# Input
{ "names": ["Lou Malnati's", "Pequod's"] }
# Output: one entry per name, each with a status
[ { "query": "Pequod's", "status": "matched",     # use `match`
    "match": {"license_id","dba_name","address","zip","facility_type",
              "risk_score","risk_tier","trend","last_inspection"} },
  { "query": "Lou Malnati's", "status": "ambiguous",  # several venues share the name
    "candidates": [ {"dba_name","address","neighborhood","license_id"}, ... ] } ]
  # or { "status": "no_inspection_record" } → no address or score is given
```

On a detail page where a `license_id` is already known, use `explain_restaurant`
instead. Matching is the shared `scores_match.py` logic (see §4.1).

### Tool 5: `find_reviews` → attributed deep links

Builds keyless deep links to each source's search for the business (Yelp, Google
Maps, TripAdvisor) on food-safety topics (`cleanliness`, `pests`, `food_quality`,
`illness`). It never scrapes or stores those pages — it only constructs URLs the
user clicks through to. Every response carries a disclaimer: reviews are unverified
opinion and are **not** part of the risk score. Called only when the user asks what
reviewers say.

```python
# Input
{ "name": "Arami", "address": "1829 W Chicago Ave", "topics": ["pests","cleanliness"] }
# Output
{ "name": "...", "topics": [...],
  "review_links": [ {"source":"Yelp","label":"Yelp reviews","url":"..."}, ... ],
  "disclaimer": "Third-party reviews are unverified diner opinions ..." }
```

### Tool 6: `find_inspection_records` → city inspection-record links

Builds (does not fetch) a deep link to the **active city's** authoritative
inspection records for a **set** of establishments, filtered by exactly one of:
`license_ids` (city-native ids from `get_safety_score` — Chicago license number,
NYC CAMIS), a `zip`, or a `lat + lon + radius_m` area. Chicago and NYC publish on
Socrata, so the tool builds a filtered query link (Chicago Food Inspections
`4ijn-s7e5`; NYC DOHMH `43nn-pn8j`); LA County has no filterable grid, so the tool
returns the LA County Public Health inspections page. This is the city's own data
behind the risk score, so it needs no disclaimer.

```python
# Input (exactly one filter mode)
{ "license_ids": ["2543871","1998877"] }   # or {"zip":"60622"} or {"lat","lon","radius_m"}
# Output
{ "url": "https://data.cityofchicago.org/.../explore/query/...",
  "mode": "license_ids", "truncated": false, "note": "Opens the Chicago Food ..." }
```

### Tool 7: `food_safety_info` → curated cited facts

Answers general food-safety / foodborne-illness questions from the vetted topic
catalogue over the allow-listed public-health sources (see §5.3). Education, not
medical advice — personal "is it safe for me" questions are steered to a
professional by the system prompt and guardrail, not here.

```python
# Input
{ "query": "how common is food poisoning?", "topics": [] }
# Output
{ "query": "...", "topics": ["overview","prevention"],
  "info": [ {"topic","title","summary","sources":[{"name","url"}]} ],
  "disclaimer": "General food-safety information from public health authorities ..." }
```

### Tool 8: `visualize_data` → sandboxed chart of the city's data

For "chart / plot / graph / visualize" requests over the ACTIVE CITY's own
food-safety data. The model writes short pandas + matplotlib `code` (over a
preloaded `df` = the city's `scores.json` plus derived `top_driver` /
`top_driver_topic` columns) and a `title`; the tool runs the code in a
**network-isolated AgentCore Code Interpreter** (untrusted model code, no egress),
uploads the rendered PNG + the script to a private S3 prefix, and returns them as
short-lived **presigned URLs** inside a fenced `eatelligence-chart` block. A chart
is an aggregate of the precomputed batch scores, never a new prediction
(batch-score-to-JSON design). The code must `print()` the numbers it plots; the
tool returns that stdout as `summary` so the agent captions from real values, not
guesses (decision record 0019).

```python
# Input
{ "code": "import matplotlib.pyplot as plt ... fig.savefig('chart.png'); print(...)",
  "title": "Chicago establishments by risk tier" }
# Output (success)
{ "status": "ok", "chart_id": "chart-…", "summary": "<the printed numbers>",
  "chart_block": "```eatelligence-chart\\n{...img/script URLs...}\\n```" }
# Output (bad or failing code)
{ "status": "error", "error": "..." }   # the agent relays it or fixes the code
```

Off AWS (local / tests / CI) it **stubs**: it does NOT execute the code and returns
a placeholder, so nothing untrusted runs off the sandbox
(`FSI_SANDBOX_USE_STUB=false` switches on real execution in the deploy).

---

## 7. The Agent's Two Jobs, City & Persona Context

### 7.1 Two jobs (system prompt)

`agents/system_prompt.txt` scopes the agent to exactly two jobs:

- **Job A** — help users understand the **predicted food-safety risk signal** for
  the active city's establishments, combining OSM discovery with the batch scores,
  SHAP drivers, and inspection history.
- **Job B** — answer **general food-safety / foodborne-illness questions** via
  `food_safety_info`, always with a cited authoritative source.

Guardrail framing (prompt-level): the score is a **180-day forward prediction, not
a verdict**; never tell the user whether to eat somewhere; never label a place
"safe"/"unsafe"; refuse a yes/no framing (the reply's first word is never "Yes"/
"No"); never fabricate inspection data (every claim comes from a tool result); give
no personalised medical or legal advice. Anything outside the two jobs — recipes,
meal planning, other cities' restaurants, **writing code or software**, homework,
chit-chat — is politely declined in one sentence, then the agent offers what it can
do.

### 7.2 City & persona (per-request context)

The frontend prepends optional `[[city:chicago|nyc|la]]` and
`[[persona:inspector|caregiver]]` markers (or sends explicit `city` / `persona`
payload fields; the deployed proxy forwards only the query string, so the marker is
the robust path). `invoke()` extracts and strips them, sets the `_ACTIVE_CITY`
contextvar, and prepends city/persona framing to the system prompt. **The model
never chooses the city** — the tools already read the right city's data; the
framing only keeps the model's wording aligned. The two persona sections
(INSPECTOR CONTEXT, CAREGIVER / IMMUNOCOMPROMISED CONTEXT) tune which drivers are
emphasised, without ever issuing a pass/fail verdict.

### 7.3 Per-request isolation & history

`_build_agent` constructs a **fresh Strands `Agent` per request** (the
`BedrockModel` is shared and stateless). A module-level singleton would accumulate
one growing history across every caller on a warm container, leaking one user's
context into another's. Multi-turn context is replayed by the caller: the client's
prior turns arrive in `history`, are validated hard in `_coerce_history`
(only `user`/`assistant` roles, strict alternation, length-capped, **text turns
only** — never client-supplied tool results), and seed the new agent. A follow-up
re-runs the tools, so a prior score is never treated as ground truth.

---

## 8. Deployment & Front Door

### 8.1 AgentCore Runtime (single CodeZip)

The agent is deployed as **one CodeZip AgentCore Runtime** — the Strands agent
plus its in-process tools in `entrypoint.py` — via the CDK and
`agentcore-deploy/agentcore/agentcore.json` (`scripts/deploy_aws.sh`). See
`agents/README.md` → "Deploying to AgentCore".

`agents/harness.yaml` describes an **alternate** per-tool-Lambda harness
(`agentcore deploy --config agents/harness.yaml`). It is **not the wired deploy
path** and is kept for reference only; its content (five tools, thinking budgets,
off-topic/PII guardrail wording) predates the current design and should not be read
as the live configuration.

### 8.2 Lambda proxy (ALB → AgentCore)

`agents/lambda_proxy/handler.py` is the public front door. It accepts plain JSON
from the internet, validates it, and signs the `invoke_agent_runtime` call with the
Lambda execution role:

```
POST /                                 (from the ALB)
{ "query": "safe sushi near Wicker Park",
  "session_id": "abc123",
  "history": [ {"role":"user"|"agent","content":"..."}, ... ] }   # optional
→ 200 { "result": "1. Mirai Sushi ..." }
```

Guards: the query is required and capped at **500 characters**; history is bounded
to the last **20 turns**, each **8,000 chars** (a size guard — the runtime
re-validates roles/alternation); a short/absent `session_id` is filled with a
`uuid4`. AgentCore returns a Server-Sent-Events stream (`data: "<json>"` lines),
which `_parse_sse` concatenates into the single `{ "result": string }` the browser
consumes. The web app calls this proxy; there is no Next.js API route hitting a
live model, and the app itself still reads the committed `scores.json`, not the
agent.

---

## 9. Model Configuration

Nova 2 Lite is configured once in `agents/entrypoint.py` and shared across
requests:

| Setting | Value | Why |
|---|---|---|
| `model_id` | `us.amazon.nova-2-lite-v1:0` | AWS-native inference profile, cheapest tool-use tier |
| `temperature` | `0.2` | Factual lookup-and-report task; low variance limits fabricated scores/names |
| `max_tokens` | `4096` | Caps worst-case output cost per turn |
| Guardrail | optional | Attached only when both `FSI_BEDROCK_GUARDRAIL_ID` and `FSI_BEDROCK_GUARDRAIL_VERSION` are set |

There are **no** extended-thinking / adaptive-budget fields — those are Nova
Premier only. Nova 2 Lite does multi-step tool-use reasoning natively.

---

## 10. Bedrock Guardrail (platform-level)

`agents/create_guardrail.py` provisions the guardrail the agent attaches to. It is
deliberately narrow:

- **Denied topics — only two**: `PersonalisedMedicalAdvice` (personal diagnosis /
  treatment / medication for oneself) and `LegalAdvice`. There is **no catch-all
  "off-topic" topic**: a negatively-defined "anything not about food safety" topic
  makes Bedrock's classifier over-match — an earlier broad version blocked nearly
  every query, including core risk lookups. Off-topic requests are declined by the
  **system prompt** instead (the eval verifies this). The denied-topic definitions
  deliberately avoid the words "risk" / "food-safety" / disease names, because
  naming them pulls legitimate queries into the topic.
- **Prompt-attack filter** — `PROMPT_ATTACK` at `HIGH` input strength, resisting
  "ignore your instructions" injection.
- **Contextual-grounding / relevance** — configured but **NOT active** as wired:
  Strands' `BedrockModel` does not tag tool outputs as grounding sources, so the
  policy has no source to score against and does not block fabricated scores.
  Anti-fabrication therefore rests on the **system prompt's** rules. The policy is
  kept so it starts working if a grounding source is wired in later.

There is no PII-extraction policy. The guardrail lives in **us-west-2** (the
runtime's region); wire its printed id + version through the `FSI_BEDROCK_*` env
vars.

---

## 11. Evaluation

`agents/eval/run_eval.py` layers deterministic gates under a live guardrail suite:

1. **Faithfulness** (deterministic, no Bedrock) — samples published `scores.json`
   records, runs them through `get_safety_score`, and asserts the returned
   `risk_score` / `risk_tier` / `license_id` / `trend` equal the JSON. This is the
   hard, CI-able metric on the batch-score data path (decision record 0010). Two
   sibling deterministic gates cover the identity path: **`--identity`** asserts a
   matched venue relays the city record's authoritative address (not the OSM
   stub's), and **`--lookup`** asserts `look_up_establishment` resolves a real
   name to the right record and returns a clean no-record for a nonsense name.
2. **Citations — allow-list** (deterministic) — every URL `food_safety_info` can
   cite is https and on `ALLOWED_DOMAINS`, so the agent can only cite authoritative
   public-health sources.
3. **Links** — a deterministic builder check on `find_inspection_records` (correct
   WHERE clause per mode, id-list cap, filter-less error), plus an **opt-in**
   `--links` live pass that resolves every citation URL (flagging 404/410/DNS) and
   replays each records link against Socrata to confirm ≥1 real record.
4. **Guardrails** (needs Bedrock) — runs the agent on adversarial prompts (off-
   topic / other-city declined, "is X safe?" → signal not verdict, unknown venue →
   no invented score, general question → cited source, personal-medical steered,
   tool outage degrades, injection refused). Substring heuristics by default; the
   `--judge` flag grades with a **Nova Pro** LLM judge.

There is no `golden.jsonl` / "AgentCore Evaluations" job — the deterministic gates
above are what run (and gate) in CI.

---

## 12. File / Folder Layout (as built)

```
food-safety-intelligence/
├── agents/
│   ├── entrypoint.py            ← AgentCore Runtime handler: @tool wrappers,
│   │                              per-request Agent, city/persona context, S3 warm-up
│   ├── system_prompt.txt        ← two-job scope, framing/guardrails, persona sections
│   ├── create_guardrail.py      ← Bedrock guardrail (medical + legal denied topics only)
│   ├── city_context.py          ← per-city framing/scope text (shared: entrypoint + run_local)
│   ├── scores_match.py          ← shared name/address normalisation + fuzzy matcher
│   ├── harness.yaml             ← reference-only alternate harness (NOT the deploy path)
│   ├── run_local.py             ← local test driver
│   ├── lambda_proxy/handler.py  ← ALB → AgentCore proxy, { result } response
│   ├── eval/run_eval.py         ← faithfulness + citations + links + guardrail suite
│   └── tools/
│       ├── find_restaurants/    ← Overpass query builder + per-city neighborhood tables
│       ├── get_safety_score/    ← fuzzy match to scores.json (sagemaker_stub.py = vestigial)
│       ├── explain_restaurant/  ← SHAP drivers + inspection history
│       ├── look_up_establishment/ ← name → authoritative city record (general chat)
│       ├── find_reviews/        ← attributed third-party deep links
│       ├── find_inspection_records/ ← city inspection-record link builder (Chicago/NYC Socrata, LA page)
│       ├── food_safety_info/    ← curated cited public-health topic catalogue
│       └── visualize_data/      ← sandboxed pandas/matplotlib chart of the city's data
└── agentcore-deploy/            ← CDK app for the AgentCore Runtime stack
```

---

## 13. Key Design Decisions

**Nova 2 Lite, no extended thinking**
AWS-native (no cross-provider billing), among the cheapest tool-use tiers, and it
does multi-step tool reasoning natively — the adaptive "thinking budget" an earlier
draft assumed is a Nova Premier feature and is not used here. A fixed low
temperature suits a factual lookup task.

**Batch scores stay unchanged — no request-time model**
The Python pipeline → `scores.json` seam is permanent. Both scoring tools read the
same precomputed file the web app uses; the model is never invoked on a query. An
unmatched venue surfaces as no-record, never an invented number.

**Overpass API for restaurant discovery**
No API key, no billing, covers Chicago / NYC / LA. The agent builds the Overpass QL
query at runtime from static per-city neighborhood tables — no pre-indexing needed.

**Address + name + geo matching instead of a shared key**
OSM and the city dataset share no id. Address normalisation + a name gate + a
lat/lon-and-name fallback handle common variations; an unresolved venue returns
no-record rather than a neighbour's score (a confident wrong score is worse than a
miss).

**Eight tools, two jobs**
Beyond the three risk tools, the agent resolves named venues to their
authoritative city record (`look_up_establishment`, so general chat never states
an address from memory), offers third-party review deep links (`find_reviews`), an
authoritative city-records link (`find_inspection_records`), cited general
food-safety education (`food_safety_info` — widening scope to job B while keeping
citations on a curated allow-list), and on-demand charts of the city's own data
(`visualize_data`, model-authored code run in a network-isolated sandbox; decision
record 0019).

**Narrow guardrail, prompt-level scope control**
The Bedrock guardrail denies only personalised-medical and legal topics plus
prompt-attacks; off-topic control lives in the system prompt because a negative
catch-all over-matches and blocks legitimate risk lookups.

**Single CodeZip runtime over a per-tool-Lambda harness**
The deployed agent is one AgentCore Runtime artifact with in-process tools, fronted
by a single Lambda proxy. Per-request Agent construction keeps sessions isolated;
`harness.yaml`'s per-tool-Lambda design is kept only for reference.
