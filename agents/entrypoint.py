"""
AgentCore Runtime entrypoint — Food Safety Intelligence
--------------------------------------------------------
Deployed to Amazon Bedrock AgentCore Runtime via:
    agentcore configure -e agents/entrypoint.py -r us-east-1 --disable-memory
    agentcore deploy

On cold start, downloads scores.json and inspection_history.json from S3
into /tmp so the tool handlers can read them without network calls per query.

Environment variables (set in AgentCore runtime config or .bedrock_agentcore.yaml):
    DATA_BUCKET         S3 bucket name (default: food-safety-intelligence-data)
    DATA_PREFIX         S3 prefix     (default: web-app-data)
    SAGEMAKER_USE_STUB  true | false  (default: true)
    SAGEMAKER_ENDPOINT  required when SAGEMAKER_USE_STUB=false
    AWS_REGION          default: us-east-1
"""

from __future__ import annotations

import importlib.util
import os
import sys

# ---------------------------------------------------------------------------
# Path setup — add tool dirs so handler.py files import their siblings.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
for _tool in ["find_restaurants", "get_safety_score", "explain_restaurant"]:
    _p = os.path.join(_HERE, "tools", _tool)
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Default env vars — overridden by AgentCore runtime environment config.
# ---------------------------------------------------------------------------
os.environ.setdefault("SCORES_JSON_PATH", "/tmp/scores.json")
os.environ.setdefault("HISTORY_JSON_PATH", "/tmp/inspection_history.json")
os.environ.setdefault("SAGEMAKER_USE_STUB", "true")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("DATA_BUCKET", "food-safety-intelligence-data")
os.environ.setdefault("DATA_PREFIX", "web-app-data")

# ---------------------------------------------------------------------------
# Cold-start data warm-up — downloads from S3 once per container lifetime.
# ---------------------------------------------------------------------------
import boto3  # noqa: E402


def _warm_data_files() -> None:
    """Download scores files from S3 to /tmp on first cold start."""
    bucket = os.environ["DATA_BUCKET"]
    prefix = os.environ["DATA_PREFIX"]
    s3 = boto3.client("s3", region_name=os.environ["AWS_REGION"])

    files = {
        os.environ["SCORES_JSON_PATH"]: f"{prefix}/scores.json",
        os.environ["HISTORY_JSON_PATH"]: f"{prefix}/inspection_history.json",
    }
    for local_path, s3_key in files.items():
        if not os.path.exists(local_path):
            print(f"[warm-up] Downloading s3://{bucket}/{s3_key} → {local_path}")
            s3.download_file(bucket, s3_key, local_path)
            print(f"[warm-up] Done: {os.path.getsize(local_path):,} bytes")


_warm_data_files()

# ---------------------------------------------------------------------------
# Tool handler loader.
# ---------------------------------------------------------------------------


def _load_handler(tool_name: str):
    path = os.path.join(_HERE, "tools", tool_name, "handler.py")
    spec = importlib.util.spec_from_file_location(f"_{tool_name}_handler", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_find_handler = _load_handler("find_restaurants")
_score_handler = _load_handler("get_safety_score")
_explain_handler = _load_handler("explain_restaurant")

# ---------------------------------------------------------------------------
# Strands tool wrappers.
# ---------------------------------------------------------------------------
from bedrock_agentcore import BedrockAgentCoreApp  # noqa: E402
from strands import Agent, tool  # noqa: E402
from strands.models.bedrock import BedrockModel  # noqa: E402


@tool
def find_restaurants(
    neighborhood: str = "",
    lat: float = 0.0,
    lon: float = 0.0,
    radius_km: float = 1.0,
    cuisine: str = "",
    limit: int = 20,
) -> list:
    """
    Find restaurants near a Chicago neighborhood or lat/lon coordinates using
    OpenStreetMap (free, no API key). Filters by cuisine when provided.
    ALWAYS call this first before get_safety_score.
    """
    ev: dict = {"radius_km": radius_km, "limit": limit}
    if neighborhood:
        ev["neighborhood"] = neighborhood
    if lat and lon:
        ev["lat"] = lat
        ev["lon"] = lon
    if cuisine:
        ev["cuisine"] = cuisine
    return _find_handler.handler(ev, None)


@tool
def get_safety_score(restaurants: list) -> list:
    """
    Score restaurants using the XGBoost model (stub or real SageMaker endpoint).
    Call after find_restaurants with the full restaurant list.
    """
    return _score_handler.handler({"restaurants": restaurants}, None)


@tool
def explain_restaurant(license_id: str) -> dict:
    """
    Get full SHAP driver breakdown and inspection history for one restaurant.
    Call for the 2-3 lowest predicted-risk results.
    """
    return _explain_handler.handler({"license_id": license_id}, None)


# ---------------------------------------------------------------------------
# System prompt.
# ---------------------------------------------------------------------------
_PROMPT_FILE = os.path.join(_HERE, "system_prompt.txt")
SYSTEM_PROMPT = open(_PROMPT_FILE).read() if os.path.exists(_PROMPT_FILE) else ""

# ---------------------------------------------------------------------------
# Bedrock Guardrail (platform-level safety, independent of model compliance)
# ---------------------------------------------------------------------------


def _guardrail_kwargs() -> dict[str, str]:
    """Attach a Bedrock Guardrail to the model when one is configured.

    The guardrail's denied-topic and prompt-attack filters apply to input/output
    text automatically at the platform layer, so off-topic requests and prompt
    injection are blocked regardless of whether the model follows the prompt. The
    guardrail's contextual-grounding/relevance policy is NOT active as wired
    (Strands' BedrockModel does not tag tool outputs as grounding sources), so
    fabricated scores are not blocked here — anti-fabrication relies on the
    system prompt's rules. A guardrail only activates when BOTH an id and a
    version are set, so we pass them only when present; absent (local dev /
    tests) the agent runs with no guardrail. Create the guardrail out-of-band
    with ``agents/create_guardrail.py`` and wire the printed id and version
    through these env vars.
    """
    gid = os.environ.get("FSI_BEDROCK_GUARDRAIL_ID")
    gver = os.environ.get("FSI_BEDROCK_GUARDRAIL_VERSION")
    if gid and gver:
        return {"guardrail_id": gid, "guardrail_version": gver, "guardrail_trace": "enabled"}
    return {}


# ---------------------------------------------------------------------------
# Agent + AgentCore app.
# ---------------------------------------------------------------------------
app = BedrockAgentCoreApp()
model = BedrockModel(
    model_id="us.amazon.nova-2-lite-v1:0",
    region_name=os.environ["AWS_REGION"],
    max_tokens=4096,
    # Low temperature: this is a factual lookup-and-report task, not a creative
    # one. Sampling variance only adds room for fabricated scores or names.
    temperature=0.2,
    **_guardrail_kwargs(),
)
agent = Agent(
    model=model,
    tools=[find_restaurants, get_safety_score, explain_restaurant],
    system_prompt=SYSTEM_PROMPT,
)


@app.entrypoint
def invoke(payload: dict) -> dict:
    """
    AgentCore Runtime invocation handler.

    Expected payload: { "query": "safe sushi near Wicker Park", "session_id": "..." }
    Returns:          { "result": "1. Mirai Sushi ..." }
    """
    query = payload.get("query") or payload.get("prompt", "")
    if not query:
        return {"error": "query is required"}

    result = agent(query)
    return {"result": str(result)}


# ---------------------------------------------------------------------------
# Local test server (python agents/entrypoint.py → http://localhost:8080)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run()
