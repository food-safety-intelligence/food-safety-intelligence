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
