"""
Local agent runner — Food Safety Intelligence
----------------------------------------------
Runs the full agent pipeline on your laptop using Strands Agents + Amazon
Bedrock (Nova 2 Lite).  No AgentCore deployment needed to test.

Usage:
    # One-shot query
    python agents/run_local.py "safe sushi near Wicker Park"

    # Interactive REPL (no arguments)
    python agents/run_local.py

Prerequisites (see README below):
    1. AWS credentials configured  (aws configure  OR  env vars)
    2. Nova 2 Lite enabled in your Bedrock console (us-east-1)
    3. SAGEMAKER_USE_STUB=true  (default — no SageMaker endpoint needed yet)

Environment variables:
    AWS_REGION              default: us-east-1
    SAGEMAKER_USE_STUB      default: true  (set false + SAGEMAKER_ENDPOINT to use real model)
    SAGEMAKER_ENDPOINT      required only when SAGEMAKER_USE_STUB=false
    SCORES_JSON_PATH        default: app/public/data/scores.json (falls back to mock)
    HISTORY_JSON_PATH       default: app/public/data/inspection_history.json
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Resolve paths so tool modules import correctly regardless of working dir.
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))

# Add each tool directory to sys.path so cross-module imports work locally.
for _tool_dir in [
    os.path.join(_AGENTS_DIR, "tools", "find_restaurants"),
    os.path.join(_AGENTS_DIR, "tools", "get_safety_score"),
    os.path.join(_AGENTS_DIR, "tools", "explain_restaurant"),
]:
    if _tool_dir not in sys.path:
        sys.path.insert(0, _tool_dir)

# Default data file paths — point at the Next.js public/data directory.
os.environ.setdefault(
    "SCORES_JSON_PATH",
    os.path.join(_REPO_ROOT, "app", "public", "data", "scores.json"),
)
os.environ.setdefault(
    "HISTORY_JSON_PATH",
    os.path.join(_REPO_ROOT, "app", "public", "data", "inspection_history.json"),
)

# Stub mode on by default — no SageMaker endpoint needed.
os.environ.setdefault("SAGEMAKER_USE_STUB", "true")

# ---------------------------------------------------------------------------
# Strands imports (after path setup)
# ---------------------------------------------------------------------------
# Tool handlers — each wraps its Lambda handler as a Strands @tool.
# We import handler.py from each tool directory directly (they're on sys.path).
import importlib.util as _ilu  # noqa: E402
import types as _types  # noqa: E402

from strands import Agent, tool  # noqa: E402
from strands.models.bedrock import BedrockModel  # noqa: E402


def _load_handler(tool_name: str) -> _types.ModuleType:
    """Load a tool's handler.py by absolute path, avoiding package-name collisions."""
    path = os.path.join(_AGENTS_DIR, "tools", tool_name, "handler.py")
    spec = _ilu.spec_from_file_location(f"_{tool_name}_handler", path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_find_handler = _load_handler("find_restaurants")
_score_handler = _load_handler("get_safety_score")
_explain_handler = _load_handler("explain_restaurant")


# ---------------------------------------------------------------------------
# Tool wrappers — Strands @tool converts Python functions into agent tools.
# The docstring becomes the tool description the model reads.
# ---------------------------------------------------------------------------


@tool
def find_restaurants(
    neighborhood: str = "",
    lat: float = 0.0,
    lon: float = 0.0,
    radius_km: float = 1.0,
    cuisine: str = "",
    limit: int = 20,
) -> list | dict:
    """
    Find restaurants near a Chicago neighborhood or lat/lon coordinates using
    OpenStreetMap (free, no API key). Filters by cuisine when provided.
    Returns name, address, coordinates, cuisine, and opening hours.
    ALWAYS call this first before get_safety_score.

    Args:
        neighborhood: Chicago neighborhood name, e.g. "Wicker Park", "Lincoln Square"
        lat: Latitude (use instead of neighborhood if you have coordinates)
        lon: Longitude (use instead of neighborhood if you have coordinates)
        radius_km: Search radius in kilometres (default 1.0)
        cuisine: Cuisine type e.g. "sushi", "ramen", "thai", "pizza" (optional)
        limit: Maximum number of restaurants to return (default 20, max 50)
    """
    event: dict = {"radius_km": radius_km, "limit": limit}
    if neighborhood:
        event["neighborhood"] = neighborhood
    if lat and lon:
        event["lat"] = lat
        event["lon"] = lon
    if cuisine:
        event["cuisine"] = cuisine
    return _find_handler.handler(event, None)


@tool
def get_safety_score(restaurants: list) -> list:
    """
    Look up Chicago food inspection risk scores for a list of restaurants.
    Calls the XGBoost model (stub during development — set SAGEMAKER_USE_STUB=false
    and SAGEMAKER_ENDPOINT to use the real SageMaker endpoint).
    Returns risk_score (0-1), risk_tier, trend, SHAP drivers, and whether a
    Chicago inspection record was found.
    Call after find_restaurants. Pass the full restaurant list from that call.

    Args:
        restaurants: List of restaurant dicts from find_restaurants
    """
    return _score_handler.handler({"restaurants": restaurants}, None)


@tool
def explain_restaurant(license_id: str) -> dict:
    """
    Get the full SHAP driver breakdown and inspection history for one restaurant
    identified by its Chicago license_id (from get_safety_score results).
    Call this for the 2-3 lowest predicted-risk results to give the user meaningful context.

    Args:
        license_id: Chicago business license ID (from get_safety_score result)
    """
    return _explain_handler.handler({"license_id": license_id}, None)


# ---------------------------------------------------------------------------
# System prompt — single source of truth in system_prompt.txt (shared with
# entrypoint.py, which reads the same file for the deployed agent).
# ---------------------------------------------------------------------------

_PROMPT_FILE = os.path.join(_AGENTS_DIR, "system_prompt.txt")
SYSTEM_PROMPT = open(_PROMPT_FILE).read() if os.path.exists(_PROMPT_FILE) else ""


# ---------------------------------------------------------------------------
# Agent factory
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


def build_agent() -> Agent:
    region = os.environ.get("AWS_REGION", "us-east-1")
    # Nova 2 Lite — cost-effective AWS-native model with tool-use support.
    # Note: the `thinking` field is only valid on Nova Premier; Nova 2 Lite
    # does multi-step reasoning natively without it.
    model = BedrockModel(
        model_id="us.amazon.nova-2-lite-v1:0",
        region_name=region,
        max_tokens=4096,
        # Low temperature: this is a factual lookup-and-report task, not a
        # creative one. Sampling variance only adds room for fabricated
        # scores or names.
        temperature=0.2,
        **_guardrail_kwargs(),
    )
    return Agent(
        model=model,
        tools=[find_restaurants, get_safety_score, explain_restaurant],
        system_prompt=SYSTEM_PROMPT,
    )


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def _banner():
    stub_mode = os.environ.get("SAGEMAKER_USE_STUB", "true").lower() != "false"
    endpoint = os.environ.get("SAGEMAKER_ENDPOINT", "not set")
    scores_path = os.environ.get("SCORES_JSON_PATH", "")
    scores_exists = os.path.exists(scores_path)

    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║   Food Safety Intelligence — Local Agent (Strands)       ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print("║  Model        : Nova 2 Lite (us.amazon.nova-2-lite-v1:0)        ║")
    print(
        f"║  SageMaker    : {'STUB (deterministic hash)' if stub_mode else f'REAL → {endpoint}':<34}║"
    )
    print(f"║  scores.json  : {'FOUND ✓' if scores_exists else 'NOT FOUND — using mock':<34}║")
    print("╠══════════════════════════════════════════════════════════╣")
    print("║  Try: 'safe sushi near Wicker Park'                      ║")
    print("║       'low risk ramen Lincoln Square immunocompromised'  ║")
    print("║       'thai food near the loop, no fails'                ║")
    print("║  Type 'quit' or Ctrl-C to exit.                          ║")
    print("╚══════════════════════════════════════════════════════════╝\n")


def main():
    # One-shot mode: query passed as CLI argument.
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        _banner()
        print(f"Query: {query}\n")
        agent = build_agent()
        response = agent(query)
        print(f"\n{response}")
        return

    # Interactive REPL mode.
    _banner()
    agent = build_agent()

    while True:
        try:
            query = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break
        if not query:
            continue
        if query.lower() in {"quit", "exit", "q"}:
            print("Bye.")
            break

        try:
            response = agent(query)
            print(f"\nAgent: {response}\n")
        except Exception as exc:
            print(f"\n[Error] {exc}\n")
            print("Check that Bedrock Nova 2 Lite is enabled in your AWS console.")


if __name__ == "__main__":
    main()
