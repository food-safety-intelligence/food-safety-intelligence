# Setup Guide — Food Safety Agent (run_local.py)

Step-by-step for a fresh machine with Python 3 already installed.
The agent runs entirely locally — no Docker, no servers, no deployment.

---

## What you need before starting

| Requirement | Minimum version | Check command |
|---|---|---|
| Python | 3.11 | `python --version` |
| pip | any recent | `pip --version` |
| Git | any | `git --version` |
| AWS account | — | [aws.amazon.com](https://aws.amazon.com) |
| AWS CLI | v2 | `aws --version` |

> **macOS / Linux only for this guide.**  
> Windows users: use WSL2 with Ubuntu, then follow the Linux steps.

---

## Step 1 — Clone the repo

```bash
git clone https://github.com/<your-org>/food-safety-intelligence.git
cd food-safety-intelligence
```

---

## Step 2 — Create a Python virtual environment

Using the standard library `venv` (works everywhere):

```bash
python -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows (WSL not needed if using cmd)
```

Your prompt will change to show `(.venv)` — all packages install here, not system-wide.

---

## Step 3 — Install Python dependencies

```bash
pip install --upgrade pip
pip install strands-agents boto3
```

That's the minimum needed to run the agent. `strands-agents` pulls in everything
it needs (opentelemetry, httpx, etc.) automatically.

> **Optional — install the full project stack** (ML pipeline, notebooks, etc.):
> ```bash
> pip install -e ".[dev]"
> ```
> This installs pandas, scikit-learn, xgboost, pytest, and everything else in
> `pyproject.toml`. Not required just to run the agent.

---

## Step 4 — Configure AWS credentials

The agent calls Amazon Bedrock (Nova 2 Lite) — the only AWS service needed.

### Option A — AWS CLI (recommended)

```bash
aws configure
```

Enter when prompted:
```
AWS Access Key ID:     <your-key-id>
AWS Secret Access Key: <your-secret>
Default region name:   us-east-1
Default output format: json
```

### Option B — environment variables (CI / shared machines)

```bash
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1
```

### Verify credentials work

```bash
aws sts get-caller-identity
```

Expected output (values will be yours):
```json
{
    "UserId": "AIDA...",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/yourname"
}
```

---

## Step 5 — Enable Nova 2 Lite in Bedrock

This is a one-time click in the AWS console — no cost until you make calls.

1. Open → [Bedrock Model Access](https://us-east-1.console.aws.amazon.com/bedrock/home?region=us-east-1#/modelaccess)
2. Click **Modify model access**
3. Find **Amazon Nova Lite** → check the box
4. Click **Save changes**
5. Wait ~30 seconds — status changes to **Access granted**

> Make sure you are in **us-east-1 (N. Virginia)**. The model ID in the agent
> uses the `us.` cross-region inference prefix which routes through us-east-1.

---

## Step 6 — Verify the setup

```bash
python -c "
from strands import Agent
from strands.models.bedrock import BedrockModel
import boto3
print('strands-agents : OK')
print('boto3          :', boto3.__version__)
client = boto3.client('bedrock-runtime', region_name='us-east-1')
r = client.converse(
    modelId='us.amazon.nova-2-lite-v1:0',
    messages=[{'role':'user','content':[{'text':'ping'}]}],
    inferenceConfig={'maxTokens': 10}
)
print('Nova 2 Lite    : OK —', r['output']['message']['content'][0]['text'])
"
```

Expected output:
```
strands-agents : OK
boto3          : 1.xx.x
Nova 2 Lite    : OK — Pong!
```

If you see `ResourceNotFoundException` → Nova Lite is not enabled yet (Step 5).  
If you see `NoCredentialsError` → credentials not found (Step 4).

---

## Step 7 — Run the agent

From the repo root:

### Interactive mode (type queries, press Ctrl-C to exit)

```bash
python agents/run_local.py
```

### One-shot query

```bash
python agents/run_local.py "safe sushi near Wicker Park"
python agents/run_local.py "low risk thai food Lincoln Square"
python agents/run_local.py "ramen near the loop, my mom is immunocompromised"
python agents/run_local.py "pizza wicker park, no failed inspections"
```

### Expected output

```
╔══════════════════════════════════════════════════════════╗
║   Food Safety Intelligence — Local Agent (Strands)       ║
╠══════════════════════════════════════════════════════════╣
║  Model        : Nova 2 Lite (us.amazon.nova-2-lite-v1:0) ║
║  SageMaker    : STUB (deterministic hash)                 ║
║  scores.json  : FOUND ✓                                   ║
╠══════════════════════════════════════════════════════════╣

Query: safe sushi near Wicker Park

  → find_restaurants (calls OpenStreetMap, free, no key)
  → get_safety_score (XGBoost stub — no SageMaker needed)

1. Mirai Sushi — 2020 W Division St — Risk: Low
   No priority violations, no nearby pest complaints.
...
```

---

## Step 8 — Run the unit tests (optional, no AWS needed)

```bash
python -m pytest agents/tools/get_safety_score/test_sagemaker_stub.py -v
```

All 31 tests should pass without any AWS credentials.

---

## Scores data — two modes

The agent works out of the box in both cases:

| State | What happens |
|---|---|
| `app/public/data/scores.json` exists | Full ~20k Chicago establishment scores used for address matching |
| File missing (fresh clone) | Falls back to `scores_mock.json` — 8 sample restaurants |

To generate the real scores, run the Python ML pipeline (`make data features
retrain history`, with label construction from `notebooks/02_label_construction.ipynb`
— requires Chicago data download). The agent's Overpass restaurant discovery works regardless;
only the address-match enrichment is limited with mock data.

---

## Environment variables (all optional)

Add these to a `.env` file in the repo root, or export them in your shell:

```bash
# Which AWS region to use for Bedrock
AWS_REGION=us-east-1

# SageMaker scoring (default: stub — no endpoint needed)
SAGEMAKER_USE_STUB=true          # set false to use real endpoint
SAGEMAKER_ENDPOINT=              # required only when USE_STUB=false

# Override default data file locations
SCORES_JSON_PATH=app/public/data/scores.json
HISTORY_JSON_PATH=app/public/data/inspection_history.json
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'strands'`**
```bash
pip install strands-agents
```

**`ResourceNotFoundException` from Bedrock**
→ Nova Lite not enabled. Go to Bedrock Model Access (Step 5) and enable it.

**`NoCredentialsError` or `Unable to locate credentials`**
→ Run `aws configure` (Step 4) or export the `AWS_*` env vars.

**`ValidationException: extraneous key [thinking]`**
→ You have an older version of `run_local.py` that still passes the `thinking`
field. Pull the latest from the repo — this was fixed.

**`HTTP Error 406` from Overpass (rare)**
→ The public Overpass endpoint rate-limited the request. Wait 30 seconds and retry.

**`scores.json: NOT FOUND — using mock`**
→ Normal on a fresh clone. The agent still works; run the ML pipeline to generate
full scores, or copy a `scores.json` from a teammate.

**`AccessDeniedException` on Bedrock**
→ Your IAM user/role is missing the Bedrock permission. Add this policy:
```json
{
  "Effect": "Allow",
  "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
  "Resource": "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0"
}
```
