# Food Safety Agent — Local Run Guide

Run the full NLP → restaurant safety pipeline on your laptop.
No AgentCore deployment needed. SageMaker is stubbed by default.

---

## What runs

```
Your query
  → Strands Agent (Nova 2 Lite via Bedrock)
      → find_restaurants   — Overpass/OSM, free, no key
      → get_safety_score   — XGBoost stub (or real SageMaker when ready)
      → explain_restaurant — scores.json + inspection_history.json
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

A **conversational search** assistant for predicted food-safety risk of Chicago
food establishments. It is reachable as its own surface — the web app's `/chat`
page and the local runner — **not** tied to a specific restaurant detail page.
A user asks in natural language ("low-risk ramen near Lincoln Square"); the
agent finds candidate venues from OpenStreetMap, attaches the **precomputed**
risk signal, and returns a ranked, plain-English answer under the responsible-AI
framing in `system_prompt.txt`.

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

All three run the **same** three `handler.py` files.

### Tools

The agent calls the tools in order: `find_restaurants` → `get_safety_score` →
`explain_restaurant` (for the lowest-risk few). Each handler takes
`handler(event, _ctx)`.

**1. `find_restaurants`** — OpenStreetMap/Overpass lookup (no key).

- *Input*: `neighborhood` | (`lat`,`lon`), `radius_km`, `cuisine`, `limit`.
- *Output*: `list` of restaurant stubs sorted by distance — each
  `{osm_id, name, address, lat, lon, cuisine, opening_hours, phone, website, dist_km}`.
- *On failure*: returns a top-level `{"error": ..., "reason": ...}` object (a
  dict, not a list with a fake restaurant), so a downstream tool never reads
  `osm_id` off a malformed element. `reason` is `"location_not_recognized"` when
  the requested area is not a recognised Chicago neighborhood — it is **not**
  silently widened to a whole-Chicago search — or `"directory_unavailable"` on an
  Overpass outage *(#56)*.

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

### Safety layers

Three independent layers keep the agent on-task and prevent fabrication:

1. **Prompt guardrails** (`system_prompt.txt`, #55) — risk-signal framing; scope
   (Chicago food establishments only; decline other cities / recipes / chit-chat;
   ignore prompt-injection); no number without a tool result; and a
   prediction-vs-verdict caveat on every response. The model runs at
   `temperature=0.2`.
2. **Bedrock Guardrail** (#55) — a platform-level guardrail attached to the
   model: denied topics (off-topic / medical / legal) plus a contextual-grounding
   check that scores each response against the tool outputs and blocks
   low-grounding answers. Enforced by Bedrock, not by model compliance.
3. **Tool-level grounding** (#56, #58) — the tools never hand the model a value
   it shouldn't have: unmatched venues return no score (#58), and tool failures
   return an explicit error object the prompt knows how to relay (#56).

### Evaluation

A behavioural eval harness (`agents/eval/`) exercises the guardrails on
adversarial prompts — off-topic, "is X safe?", a venue with no record, a
non-Chicago location, and a tool outage — and checks the response follows the
rules (no yes/no verdict, no invented score, scope refusal, graceful failure).
Run on demand; it needs Bedrock credentials, so it is excluded from the default
CI run.

### Note on the sections below

The "Switching from stub to real SageMaker" and "What the stub scores look like"
sections are **superseded by [0010](../docs/decisions/0010-agent-no-request-time-scoring-and-no-record.md)**
once #58 lands: the agent does not score at request time, so `sagemaker_stub.py`
becomes orphaned. They are kept until then and should be pruned with that merge.

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

```bash
python -m pytest agents/tools/get_safety_score/test_sagemaker_stub.py -v
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `AWS_REGION` | `us-east-1` | Bedrock region |
| `SAGEMAKER_USE_STUB` | `true` | `false` to call real SageMaker endpoint |
| `SAGEMAKER_ENDPOINT` | — | Required when `SAGEMAKER_USE_STUB=false` |
| `SCORES_JSON_PATH` | `app/public/data/scores.json` | Pre-computed scores file |
| `HISTORY_JSON_PATH` | `app/public/data/inspection_history.json` | Inspection history file |

Set them inline for a one-off test:
```bash
SAGEMAKER_USE_STUB=false \
SAGEMAKER_ENDPOINT=food-safety-xgboost-prod \
python agents/run_local.py "ramen near wicker park"
```

---

## Switching from stub to real SageMaker

The stub and real paths live in `agents/tools/get_safety_score/sagemaker_stub.py`.
The switch is one env var — no code change:

```bash
# 1. Deploy your XGBoost model to a SageMaker real-time endpoint
#    (endpoint must accept CSV, 26 features in FEATURE_ORDER, return JSON)

# 2. Set env vars
export SAGEMAKER_USE_STUB=false
export SAGEMAKER_ENDPOINT=food-safety-xgboost-prod

# 3. Run — identical command, real model scores
python agents/run_local.py "safe sushi near Wicker Park"
```

The response will include `"stub": false` in the score results.

---

## What the stub scores look like

Stub scores are derived from `md5(name + address)` → `Beta(1.5, 8)` distribution.
This matches the real model's ~10% High-risk positive rate. The same restaurant
always gets the same score across runs.

The agent will include a note like:
> "Note: scores are preliminary estimates — the SageMaker endpoint is not yet
> configured."

---

## Deploying to AgentCore (Phase 2b)

When ready to deploy:

```bash
# Install AgentCore CLI
pip install amazon-bedrock-agentcore-cli

# Set Lambda ARNs in harness.yaml (replace ${LAMBDA_ARN_*} placeholders)
# Then deploy
agentcore deploy --config agents/harness.yaml
```

The local `run_local.py` and the deployed harness use identical tool logic —
the same three handler.py files run both locally (via Strands) and on Lambda.

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
