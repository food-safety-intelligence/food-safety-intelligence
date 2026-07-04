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
import re
import sys

# ---------------------------------------------------------------------------
# Path setup — add tool dirs so handler.py files import their siblings.
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
for _tool in [
    "find_restaurants",
    "get_safety_score",
    "explain_restaurant",
    "find_reviews",
    "food_safety_info",
]:
    _p = os.path.join(_HERE, "tools", _tool)
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ---------------------------------------------------------------------------
# Default env vars — overridden by AgentCore runtime environment config.
# ---------------------------------------------------------------------------
os.environ.setdefault("SCORES_JSON_PATH", "/tmp/scores.json")
os.environ.setdefault("HISTORY_JSON_PATH", "/tmp/inspection_history.json")
# NYC (multi-city, DR 0014) — a second city under the nyc/ S3 prefix.
os.environ.setdefault("SCORES_JSON_PATH_NYC", "/tmp/nyc_scores.json")
os.environ.setdefault("HISTORY_JSON_PATH_NYC", "/tmp/nyc_inspection_history.json")
os.environ.setdefault("SAGEMAKER_USE_STUB", "true")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("DATA_BUCKET", "food-safety-intelligence-data")
os.environ.setdefault("DATA_PREFIX", "web-app-data")

# The selected city rides through one request via a contextvar: the frontend
# tags the query, invoke() sets it, and the @tool wrappers pass it to handlers
# (the LLM never chooses the city). Defaults to Chicago.
import contextvars  # noqa: E402

_ACTIVE_CITY: contextvars.ContextVar[str] = contextvars.ContextVar("active_city", default="chicago")

# ---------------------------------------------------------------------------
# Cold-start data warm-up — downloads from S3 once per container lifetime.
# ---------------------------------------------------------------------------
import boto3  # noqa: E402


def _warm_data_files() -> None:
    """Download scores files from S3 to /tmp on first cold start."""
    bucket = os.environ["DATA_BUCKET"]
    prefix = os.environ["DATA_PREFIX"]
    s3 = boto3.client("s3", region_name=os.environ["AWS_REGION"])

    # Chicago is required; NYC (nyc/ prefix) is best-effort so the agent still
    # serves Chicago if NYC data hasn't been published to S3 yet — a NYC lookup
    # then finds no scores and the tool returns "no record" (DR 0010), rather
    # than failing the whole request.
    required = {
        os.environ["SCORES_JSON_PATH"]: f"{prefix}/scores.json",
        os.environ["HISTORY_JSON_PATH"]: f"{prefix}/inspection_history.json",
    }
    optional = {
        os.environ["SCORES_JSON_PATH_NYC"]: f"{prefix}/nyc/scores.json",
        os.environ["HISTORY_JSON_PATH_NYC"]: f"{prefix}/nyc/inspection_history.json",
    }
    for local_path, s3_key in required.items():
        if not os.path.exists(local_path):
            print(f"[warm-up] Downloading s3://{bucket}/{s3_key} → {local_path}")
            s3.download_file(bucket, s3_key, local_path)
            print(f"[warm-up] Done: {os.path.getsize(local_path):,} bytes")
    for local_path, s3_key in optional.items():
        if not os.path.exists(local_path):
            try:
                s3.download_file(bucket, s3_key, local_path)
                print(f"[warm-up] Done (nyc): {os.path.getsize(local_path):,} bytes")
            except Exception as e:  # noqa: BLE001 — NYC data is optional
                print(f"[warm-up] NYC data not available ({s3_key}): {e}")


# NOTE: _warm_data_files() is intentionally NOT called here at import time. The
# score files are ~68MB, and downloading them during module init blows AgentCore's
# 30s runtime-init budget so the container never becomes ready (every invocation
# 502s with "Runtime initialization time exceeded"). It is called lazily from the
# invocation handler instead; being idempotent, only the first request on a fresh
# container pays the download.

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
_reviews_handler = _load_handler("find_reviews")
_info_handler = _load_handler("food_safety_info")

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
    return _score_handler.handler(
        {"restaurants": restaurants, "city": _ACTIVE_CITY.get()}, None
    )


@tool
def explain_restaurant(license_id: str) -> dict:
    """
    Get full SHAP driver breakdown and inspection history for one restaurant.
    Call for the 2-3 lowest predicted-risk results.
    """
    return _explain_handler.handler(
        {"license_id": license_id, "city": _ACTIVE_CITY.get()}, None
    )


@tool
def find_reviews(name: str, address: str = "", topics: list | None = None) -> dict:
    """
    Find THIRD-PARTY diner reviews (Yelp/Google/web) for one restaurant, focused on
    food-safety topics: cleanliness, pests, food_quality, illness. Use only when the
    user asks what reviewers say. Returns attributed deep links; reviews are
    unverified opinion and NOT part of the risk score — pass the disclaimer and
    never use a review to set or change a risk score or tier.

    Args:
        name: Restaurant name (from find_restaurants / get_safety_score)
        address: Street address — improves match quality (optional)
        topics: Subset of ["cleanliness", "pests", "food_quality", "illness"];
                omit for all topics
    """
    return _reviews_handler.handler(
        {"name": name, "address": address, "topics": topics or []}, None
    )


@tool
def food_safety_info(query: str, topics: list | None = None) -> dict:
    """
    Answer a GENERAL food-safety / foodborne-illness question (what a germ is, how
    common illness is, safe cooking temperatures, who is most at risk, how to
    prevent it) with short vetted facts AND a citation to an authoritative public
    health source (CDC, FDA, USDA, FoodSafety.gov, WHO, NIH, or Chicago/Illinois
    public health). Use for general questions NOT about one Chicago restaurant's
    score. Base any statistic on the returned summary and cite the returned source
    links. Education, not medical advice — never use it to judge what is safe for
    someone personally.

    Args:
        query: The user's general food-safety question, passed through verbatim
        topics: Optional explicit subset of topic keys; omit to match on the query
    """
    return _info_handler.handler({"query": query, "topics": topics or []}, None)


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


# Cap how many prior turns the client may replay. Bounds payload size, Bedrock
# token cost, and how far a malicious client could pad the context window. 20
# messages = 10 user/assistant exchanges, plenty for a follow-up conversation.
_MAX_HISTORY_MESSAGES = 20
# Per-message character cap — a backstop against an oversized single turn.
_MAX_MESSAGE_CHARS = 8000


def _coerce_history(raw: object) -> list[dict]:
    """Turn the client's prior turns into Strands ``Message`` dicts.

    The deployed agent is stateless (one fresh Agent per request, see
    ``_build_agent``), so multi-turn context has to be replayed by the caller.
    The client sends the prior turns; we rebuild them as the new agent's starting
    conversation.

    This history is UNTRUSTED client input — same trust level as ``query`` — so we
    validate hard: only ``user``/``assistant`` roles (``agent`` is accepted as a
    synonym for the UI's vocabulary), text coerced to a string and length-capped,
    empties dropped. We replay only TEXT turns, never tool-use/tool-result blocks:
    a follow-up re-runs the tools, so the model never treats a client-supplied
    prior score as ground truth (anti-fabrication still rests on live tool output
    + the system prompt). Bedrock requires the conversation to start with ``user``
    and strictly alternate, so we drop any turn whose role repeats the previous
    kept turn, trim a leading assistant turn, and trim a trailing user turn (which
    would collide with the new query appended by ``agent(query)``).
    """
    if not isinstance(raw, list):
        return []

    role_map = {"user": "user", "assistant": "assistant", "agent": "assistant"}
    cleaned: list[dict] = []
    for turn in raw[-_MAX_HISTORY_MESSAGES:]:
        if not isinstance(turn, dict):
            continue
        role = role_map.get(str(turn.get("role", "")).lower())
        text = turn.get("content")
        if role is None or not isinstance(text, str) or not text.strip():
            continue
        # Drop a turn that repeats the previous role — keeps strict alternation.
        if cleaned and cleaned[-1]["role"] == role:
            continue
        cleaned.append({"role": role, "content": [{"text": text[:_MAX_MESSAGE_CHARS]}]})

    # Must start with user and end with assistant for a valid replay.
    if cleaned and cleaned[0]["role"] == "assistant":
        cleaned.pop(0)
    if cleaned and cleaned[-1]["role"] == "user":
        cleaned.pop()
    return cleaned


def _build_agent(messages: list[dict] | None = None) -> Agent:
    """Build a fresh agent for ONE request.

    The model is shared (stateless), but each invocation gets its OWN Agent so its
    conversation history is never shared across sessions. A module-level singleton
    Agent accumulates one growing message history across every caller on a warm
    container, so one user's context could leak into another's. One agent per
    request keeps sessions isolated.

    ``messages`` seeds the new agent with the caller's prior turns so a follow-up
    question has context. It stays scoped to this one request, so isolation holds.
    """
    # Tell the model which city this request is scoped to (multi-city, DR 0014).
    # The tools already read the right city's data; this keeps the model's
    # framing + "no record" wording aligned to the active city.
    city = _ACTIVE_CITY.get()
    city_label = "New York City" if city == "nyc" else "Chicago"
    city_prefix = (
        f"ACTIVE CITY: {city_label}. Scope every restaurant lookup and every "
        f"'no record' statement to {city_label}; do not mention or use the other "
        f"city's establishments for this request.\n\n"
    )
    return Agent(
        model=model,
        messages=messages or [],
        tools=[
            find_restaurants,
            get_safety_score,
            explain_restaurant,
            find_reviews,
            food_safety_info,
        ],
        system_prompt=city_prefix + SYSTEM_PROMPT,
    )


@app.entrypoint
def invoke(payload: dict) -> dict:
    """
    AgentCore Runtime invocation handler.

    Expected payload: {
        "query":      "is the second one safe too?",
        "session_id": "...",
        "history":    [{"role": "user"|"agent", "content": "..."}, ...]  # optional
    }
    Returns:          { "result": "1. Mirai Sushi ..." }
    """
    # Warm score data on first use, not at import: a cold container downloading
    # ~68MB from S3 during module init blows AgentCore's 30s init budget (#100).
    # _warm_data_files() is idempotent (skips files already in /tmp), so only the
    # first invocation on a fresh container pays the download.
    _warm_data_files()

    query = payload.get("query") or payload.get("prompt", "")
    if not query:
        return {"error": "query is required"}

    # City (multi-city, DR 0014): prefer an explicit payload field; else parse a
    # leading `[[city:nyc]]` marker the frontend prepends (the deployed proxy
    # reliably forwards only the query string, so the marker is the robust path).
    # The marker is stripped before the model sees the query.
    query, city = _extract_city(query, payload.get("city"))
    _ACTIVE_CITY.set(city)

    # Fresh, isolated agent per request, seeded with the caller's prior turns so
    # follow-up questions have context. History is client-supplied and validated.
    agent = _build_agent(_coerce_history(payload.get("history")))
    result = agent(query)
    return {"result": str(result)}


_CITY_MARKER = re.compile(r"^\s*\[\[city:(chicago|nyc)\]\]\s*")


def _extract_city(query: str, field: object) -> tuple[str, str]:
    """Resolve the request city and strip its marker from the query.

    Precedence: an explicit `city` payload field, else a leading `[[city:...]]`
    marker in the query. Unknown / missing → Chicago.
    """
    if isinstance(field, str) and field.lower() in ("chicago", "nyc"):
        return _CITY_MARKER.sub("", query), field.lower()
    m = _CITY_MARKER.match(query)
    if m:
        return query[m.end():], m.group(1)
    return query, "chicago"


# ---------------------------------------------------------------------------
# Local test server (python agents/entrypoint.py → http://localhost:8080)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run()
