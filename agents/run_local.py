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
    3. scores.json present (scoring reads precomputed batch scores; no model is
       called at request time)

Environment variables:
    AWS_REGION              default: us-east-1
    SCORES_JSON_PATH        default: app/public/data/scores.json (no-record if absent)
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
    os.path.join(_AGENTS_DIR, "tools", "look_up_establishment"),
    os.path.join(_AGENTS_DIR, "tools", "find_reviews"),
    os.path.join(_AGENTS_DIR, "tools", "find_inspection_records"),
    os.path.join(_AGENTS_DIR, "tools", "food_safety_info"),
    os.path.join(_AGENTS_DIR, "tools", "visualize_data"),
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

# ---------------------------------------------------------------------------
# Strands imports (after path setup)
# ---------------------------------------------------------------------------
# Tool handlers — each wraps its Lambda handler as a Strands @tool.
# We import handler.py from each tool directory directly (they're on sys.path).
import importlib.util as _ilu  # noqa: E402
import types as _types  # noqa: E402

import city_context  # noqa: E402 — shared per-city framing (also used by entrypoint.py)
from strands import Agent, tool  # noqa: E402
from strands.models.bedrock import BedrockModel  # noqa: E402

# Active city for a run. The deployed runtime scopes each request via a contextvar;
# run_local drives one agent synchronously per process, so a module global is enough.
# The CLI stays Chicago; the eval calls set_active_city() to exercise NYC / LA.
_ACTIVE_CITY = "chicago"

# Chart blocks generated during one query (mirrors entrypoint._PENDING_CHARTS).
# The visualize_data wrapper appends; finalize() merges them into the reply and
# clears the list, so local runs and the eval match the deployed invoke().
_PENDING_CHARTS: list = []


def finalize(text: str) -> str:
    """Apply the deployed chart-block guarantee to a raw agent reply, then clear
    the per-query collector. Call on every reply so local == production."""
    merged = _viz_handler.merge_chart_blocks(text, list(_PENDING_CHARTS))
    _PENDING_CHARTS.clear()
    return merged


def set_active_city(city: str) -> None:
    """Set the city all tool wrappers + the prompt prefix use for this run."""
    global _ACTIVE_CITY
    _ACTIVE_CITY = city if city in ("chicago", "nyc", "la") else "chicago"


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
_lookup_handler = _load_handler("look_up_establishment")
_reviews_handler = _load_handler("find_reviews")
_records_handler = _load_handler("find_inspection_records")
_info_handler = _load_handler("food_safety_info")
_viz_handler = _load_handler("visualize_data")


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
    Find restaurants near a neighborhood or lat/lon coordinates in the ACTIVE CITY
    using OpenStreetMap (free, no API key). Filters by cuisine when provided.
    Returns name, address, coordinates, cuisine, and opening hours.
    ALWAYS call this first before get_safety_score.

    Args:
        neighborhood: a neighborhood name in the active city, e.g. "Wicker Park"
        lat: Latitude (use instead of neighborhood if you have coordinates)
        lon: Longitude (use instead of neighborhood if you have coordinates)
        radius_km: Search radius in kilometres (default 1.0)
        cuisine: Cuisine type e.g. "sushi", "ramen", "thai", "pizza" (optional)
        limit: Maximum number of restaurants to return (default 20, max 50)
    """
    event: dict = {"radius_km": radius_km, "limit": limit, "city": _ACTIVE_CITY}
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
    Look up the precomputed batch risk score for each restaurant in the ACTIVE
    CITY from its scores.json. Does not call any model — a venue that matches the
    published batch run returns that calibrated score, tier and drivers directly,
    and a venue not in the batch run returns no score (no inspection record found).
    Returns risk_score (0-1 or null), risk_tier, trend, SHAP drivers, and
    whether an inspection record was found (matched_scores_json).
    Call after find_restaurants. Pass the full restaurant list from that call.

    Args:
        restaurants: List of restaurant dicts from find_restaurants
    """
    return _score_handler.handler({"restaurants": restaurants, "city": _ACTIVE_CITY}, None)


@tool
def explain_restaurant(license_id: str) -> dict:
    """
    Get the full SHAP driver breakdown and inspection history for one restaurant
    identified by its license_id (from get_safety_score results — the active city's
    native establishment id). Call this for the 2-3 lowest predicted-risk results.

    Args:
        license_id: the establishment id from a get_safety_score result
    """
    return _explain_handler.handler({"license_id": license_id, "city": _ACTIVE_CITY}, None)


@tool
def look_up_establishment(names: list) -> list:
    """
    Look up one or more establishments BY NAME in the ACTIVE CITY's inspection
    data and return each one's authoritative record (address, ZIP, facility type,
    last inspection, risk score/tier/trend, license_id) straight from the city
    data. Use this in general chat when the user names a place directly ("what's
    the address of Lou Malnati's?", "compare Giordano's and Pequod's") — it does
    NOT need find_restaurants first. Pass ALL the names in one call.

    Always call this before stating any fact about a named establishment, so the
    address and every other detail come from the data, not from memory. Each
    result has a `status`: "matched" (use `match`), "ambiguous" (several venues
    share the name — ask the user which, by address/neighborhood, using
    `candidates`), or "no_inspection_record" (say there is no city record and
    give no address or score). On a detail page where a license_id is already
    provided, use explain_restaurant instead of this.

    Args:
        names: establishment names to look up, e.g. ["Lou Malnati's", "Pequod's"]
    """
    return _lookup_handler.handler({"names": names, "city": _ACTIVE_CITY}, None)


@tool
def find_reviews(name: str, address: str = "", topics: list | None = None) -> dict:
    """
    Find THIRD-PARTY diner reviews (Yelp, Google, web) for one restaurant,
    focused on food-safety topics: cleanliness, pests, food_quality, illness.
    Use ONLY when the user asks what reviewers say about a place. Returns
    attributed "view reviews" deep links the user can click through to.

    Reviews are unverified opinion and are NOT part of the risk score — present
    them separately and always pass along the returned `disclaimer`. Never use a
    review to change or justify a risk score or tier.

    Args:
        name: Restaurant name (from find_restaurants / get_safety_score)
        address: Street address — improves link and match quality (optional)
        topics: Subset of ["cleanliness", "pests", "food_quality", "illness"];
                omit for all topics
    """
    return _reviews_handler.handler(
        {"name": name, "address": address, "topics": topics or []}, None
    )


@tool
def find_inspection_records(
    license_ids: list | None = None,
    zip_code: str = "",
    lat: float | None = None,
    lon: float | None = None,
    radius_m: float | None = None,
) -> dict:
    """
    Build a link to the ACTIVE CITY's AUTHORITATIVE food-inspection records for a
    SET of establishments — a comparison, a short list, or an area. This is the
    city's own data (the source behind the risk score), so it needs no disclaimer.
    Use it when the user compares/lists several places, or asks about an area, and
    would want to see or verify the underlying city records. Returns a {url, mode,
    note} link the user clicks through to — nothing is fetched. (Chicago and NYC
    return a filtered grid; LA returns its county inspections page.)

    Provide EXACTLY ONE filter:
      license_ids: the establishments to compare/list. Use the license_id values
        get_safety_score returned, and pass ONLY non-null ones (a place with no
        inspection record has none). Preferred for named places.
      zip_code: a ZIP in the active city, for "records in <ZIP>".
      lat + lon + radius_m: a point and radius in metres, for "records near here".

    Args:
        license_ids: license_id strings from get_safety_score (non-null only)
        zip_code: a ZIP in the active city (area mode)
        lat: latitude of the area centre (with lon + radius_m)
        lon: longitude of the area centre (with lat + radius_m)
        radius_m: search radius in metres (with lat + lon)
    """
    return _records_handler.handler(
        {
            "license_ids": license_ids or [],
            "zip": zip_code,
            "lat": lat,
            "lon": lon,
            "radius_m": radius_m,
            "city": _ACTIVE_CITY,
        },
        None,
    )


@tool
def food_safety_info(query: str, topics: list | None = None) -> dict:
    """
    Answer a GENERAL food-safety or foodborne-illness question (what a germ is,
    how common illness is, safe cooking temperatures, who is most at risk, how to
    prevent it) with short vetted facts AND a citation to an authoritative public
    health source (CDC, FDA, USDA, FoodSafety.gov, WHO, NIH, or the active city's
    local public health department). Use this for general questions that are NOT
    about one specific restaurant's score.

    Base any statistic you state on the returned `summary`, and cite the returned
    `sources` links so the user can verify them. This is education, not medical
    advice — never use it to tell someone what is safe for them personally.

    Args:
        query: The user's general food-safety question, passed through verbatim
        topics: Optional explicit subset of topic keys (e.g. ["salmonella",
                "cooking_temperatures"]); omit to match on the query text
    """
    return _info_handler.handler(
        {"query": query, "topics": topics or [], "city": _ACTIVE_CITY}, None
    )


@tool
def visualize_data(code: str, title: str) -> dict:
    """
    Make a chart from the ACTIVE CITY's precomputed food-safety data by writing
    short pandas + matplotlib code that this tool runs in a secure sandbox. Use it
    when the user asks to chart / plot / graph / visualize / show a distribution or
    breakdown of the data: risk scores, risk tiers, trend direction, SHAP driver
    contributions, or the most common drivers, filtered / sorted / aggregated any
    way they ask. Only for the ACTIVE CITY's own food-safety data — decline other
    subjects as usual. Do NOT paste code into your chat reply; pass it here.

    A DataFrame `df` is already loaded (one row per establishment) with EXACTLY
    these columns — use ONLY these, anything else raises KeyError:
      license_id, dba_name, as_of_date, neighborhood, zip, facility_type,
      risk_score (0-1), risk_tier ("Low"|"Moderate"|"Elevated"|"High"),
      trend_slope (>0 worsening, <0 improving, stable within +/-0.0003),
      top_driver (dominant SHAP feature name), top_driver_shap (its contribution),
      top_driver_topic (its plain hazard family, e.g. "temperature", "pest",
      "handwashing", "priority_violations", "inspection_outcome"). Use
      top_driver_topic for "common drivers" / "violation category" questions —
      it is the category each establishment's STRONGEST driver falls into, so
      value_counts() gives the number of establishments per category.

    Your `code` MUST:
      - use the preloaded `df` DIRECTLY. Do NOT read any file — no pd.read_csv, no
        pd.read_json, no open(). There is NO csv/json file in the sandbox; `df` is
        already in memory and ready to use.
      - build a matplotlib figure and save it with fig.savefig("chart.png").
      - print() the aggregated numbers you plotted (counts / means) — you then base
        the caption ONLY on that printed summary, which this tool returns.
      - stay a chart of aggregates; never label a place "safe"/"unsafe" and never
        make a per-person or eat/don't-eat judgement. No network, no file access
        besides chart.png.

    On success returns {status:"ok", summary, chart_block}. Write a one or two
    sentence caption using the `summary` numbers, then include the returned
    `chart_block` VERBATIM in your reply (it renders the chart inline). On
    {status:"error"} tell the user briefly, or fix the code and call again.

    Args:
        code: pandas + matplotlib code that builds a `df`-based figure into chart.png
        title: a short plain-English chart title (also used for the download name)
    """
    result = _viz_handler.handler({"code": code, "title": title, "city": _ACTIVE_CITY}, None)
    if isinstance(result, dict) and result.get("status") == "ok" and result.get("chart_block"):
        _PENDING_CHARTS.append(result["chart_block"])
    return result


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


def build_agent(messages: list | None = None) -> Agent:
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
        messages=messages or [],
        tools=[
            find_restaurants,
            get_safety_score,
            explain_restaurant,
            look_up_establishment,
            find_reviews,
            find_inspection_records,
            food_safety_info,
            visualize_data,
        ],
        # Prepend the ACTIVE CITY block (grade framing + scope) exactly as the
        # deployed runtime does, so the local agent and the eval frame identically.
        system_prompt=city_context.city_prefix(_ACTIVE_CITY) + SYSTEM_PROMPT,
    )


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def _banner():
    # Scoring reads precomputed batch scores from scores.json; the agent never
    # calls a model at request time, so the score source shown is the JSON file.
    scores_path = os.environ.get("SCORES_JSON_PATH", "")
    scores_exists = os.path.exists(scores_path)

    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║   Food Safety Intelligence — Local Agent (Strands)       ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print("║  Model        : Nova 2 Lite (us.amazon.nova-2-lite-v1:0)        ║")
    print(
        f"║  Scores       : {'scores.json FOUND' if scores_exists else 'scores.json NOT FOUND':<34}║"
    )
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
        response = finalize(str(agent(query)))
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
            response = finalize(str(agent(query)))
            print(f"\nAgent: {response}\n")
        except Exception as exc:
            print(f"\n[Error] {exc}\n")
            print("Check that Bedrock Nova 2 Lite is enabled in your AWS console.")


if __name__ == "__main__":
    main()
