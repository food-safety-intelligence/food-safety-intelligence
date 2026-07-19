"""
Lambda handler: visualize_data
------------------------------
Generate a chart from the ACTIVE CITY's precomputed data by running the model's
own pandas/matplotlib code in a sandbox, then hand the web app a rendered image
plus the exact script that produced it.

Why a sandbox (Bedrock AgentCore Code Interpreter):
  Filtering / sorting / aggregating / visualizing the data is open-ended — there
  is no fixed tool for every question a user might ask of it — so the model
  writes the analysis code. That code is UNTRUSTED, so it runs in an isolated,
  network-OFF microVM against the precomputed scores.json only; it can read the
  data and draw a figure, but it cannot reach the network or any secret. This is
  NOT request-time model scoring: the chart is built from the SAME precomputed
  batch scores.json the web app already serves (the batch-score-to-JSON design),
  aggregated — never a new prediction.

Grounding: the sandbox returns the code's stdout (the aggregated numbers the code
printed) as `summary`; the agent writes its caption from that, so every figure it
states is a real computed value, not a guess. The rendered PNG and the script are
uploaded to S3 and handed back as short-lived presigned URLs inside an
``eatelligence-chart`` block the web app renders inline.

Stub mode (default, and whenever no sandbox/bucket is configured): the code is
NOT executed — a placeholder image + the code echoed back is returned, so local
runs, tests, and the deterministic eval work without AWS and without ever running
untrusted code off the sandbox.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHART_FILENAME = "chart.png"  # the path the model's code must savefig() to
DATA_FILENAME = "scores.json"  # the data file the sandbox loads into `df`
MAX_CODE_CHARS = 8000  # a chart script is short; cap keeps a runaway arg out


def _scores_path(city: str) -> str:
    """Per-city scores.json path, warmed to /tmp by the runtime (multi-city, DR 0016)."""
    if city == "nyc":
        return os.environ.get("SCORES_JSON_PATH_NYC", "/opt/nyc_scores.json")
    if city == "la":
        return os.environ.get("SCORES_JSON_PATH_LA", "/opt/la_scores.json")
    return os.environ.get("SCORES_JSON_PATH", "/opt/scores.json")


def _use_stub() -> bool:
    """Stub unless a real sandbox is explicitly enabled. Default-safe: no AWS, no
    untrusted-code execution, in local dev / tests / CI."""
    return os.environ.get("FSI_SANDBOX_USE_STUB", "true").lower() != "false"


def _chart_region() -> str:
    """Region of the Code Interpreter + charts bucket. Distinct from AWS_REGION
    (which targets the Bedrock model + the data bucket in us-east-1) — the sandbox
    and charts bucket live in the runtime's own region (us-west-2)."""
    return os.environ.get("FSI_CHART_REGION", "us-west-2")


# Setup cell run in the sandbox BEFORE the model's code: loads the city's data
# into `df` and adds the driver-topic columns the "common drivers" charts use.
# The hazard families mirror the keyword flags in interface_contracts.md and the
# frontend's driver-icons taxonomy, so "common drivers" means the same thing
# across the product. Kept as source the sandbox executes; documented to the model
# via the tool docstring below.
SETUP_CODE = f"""
import json
import matplotlib
matplotlib.use("Agg")  # headless: render to a file, no display
import pandas as pd

_raw = json.load(open({DATA_FILENAME!r}, encoding="utf-8"))
df = pd.DataFrame(_raw["scores"] if isinstance(_raw, dict) else _raw)

# Driver-topic families for "common drivers" questions.
# Prefix -> family. More specific prefixes are matched in order, so distinct
# families like license_age vs license_n_history don't shadow each other.
_TOPICS = {{
    "was_fail": "inspection_outcome",
    "n_priority": "priority_violations",
    "n_core": "core_violations",
    "priority_violation_trend": "violation_trend",
    "prior_complaint": "complaint_history",
    "prior_priority": "priority_violations",
    "prior_core": "core_violations",
    "prior_fail": "prior_failures",
    "prior_inspections": "inspection_history",
    "days_since_last": "recency",
    "license_age": "license_age",
    "license_n_history": "inspection_history",
    "temporal": "seasonality",
    "static_inspection": "inspection_type",
    "static_risk": "assigned_risk",
    "flag_kw_temp": "temperature", "flag_kw_cool": "temperature",
    "flag_kw_raw": "raw_food", "flag_kw_cross": "cross_contamination",
    "flag_kw_expired": "expired", "flag_kw_rodent": "pest", "flag_kw_pest": "pest",
    "flag_kw_no_soap": "handwashing", "flag_kw_handwash": "handwashing",
    "flag_kw_no_paper": "handwashing", "flag_kw_sewage": "sewage",
    "flag_kw_certified": "certified_manager",
}}


def driver_topic(feature):
    \"\"\"Map a SHAP feature name to its plain hazard/topic family.\"\"\"
    if not feature:
        return "other"
    for prefix, topic in _TOPICS.items():
        if str(feature).startswith(prefix):
            return topic
    return "other"


# Per-row driver helpers: the ordered feature list, the dominant driver, and its topic.
df["driver_features"] = df["top_drivers"].apply(
    lambda ds: [d.get("feature") for d in (ds or [])]
)
df["top_driver"] = df["driver_features"].apply(lambda xs: xs[0] if xs else None)
df["top_driver_topic"] = df["top_driver"].apply(driver_topic)
"""


# ---------------------------------------------------------------------------
# Sandbox execution
# ---------------------------------------------------------------------------


def _stub_run(code: str, city: str) -> dict[str, Any]:
    """Do NOT execute the code. Return a placeholder image + the code echoed, so
    the flow works end-to-end without a sandbox or executing untrusted code."""
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='640' height='400'>"
        "<rect width='640' height='400' fill='#ffffff'/>"
        "<text x='320' y='200' font-family='sans-serif' font-size='18' "
        "fill='#6b7f6e' text-anchor='middle'>chart preview (sandbox disabled)</text>"
        "</svg>"
    )
    return {
        "ok": True,
        "image_kind": "svg",
        "image": svg,
        "stdout": (
            "Chart generation is not fully enabled in this environment yet, so this is a "
            f"placeholder preview rather than a real chart of the {city} data."
        ),
    }


def _sandbox_run(code: str, city: str) -> dict[str, Any]:
    """Run the model's code in a network-isolated AgentCore Code Interpreter.

    NOTE: the exact bedrock_agentcore Code Interpreter SDK surface is validated on
    the first live deploy (it is not exercised by the stub-based tests). Any error
    is returned as a clean {ok: False, error} so the agent can relay or retry.
    """
    scores_path = _scores_path(city)
    try:
        with open(scores_path, encoding="utf-8") as f:
            scores_text = f.read()
    except FileNotFoundError:
        return {"ok": False, "error": f"no data file for {city}"}

    try:
        # Lazy import: only the deployed runtime has (and needs) this SDK.
        from bedrock_agentcore.tools.code_interpreter_client import code_session

        region = _chart_region()
        interpreter_id = os.environ.get("FSI_CODE_INTERPRETER_ID")
        session_kwargs = {"identifier": interpreter_id} if interpreter_id else {}

        with code_session(region, **session_kwargs) as client:
            client.invoke("writeFiles", {"content": [{"path": DATA_FILENAME, "text": scores_text}]})
            setup = _drain(client.invoke("executeCode", {"language": "python", "code": SETUP_CODE}))
            if setup.get("isError"):
                return {"ok": False, "error": f"setup failed: {setup.get('text', '')[:300]}"}
            run = _drain(client.invoke("executeCode", {"language": "python", "code": code}))
            if run.get("isError"):
                # The model's own code raised — hand the traceback back so it can fix it.
                return {"ok": False, "error": run.get("text", "chart code raised an error")[:600]}
            files = _drain(client.invoke("readFiles", {"paths": [CHART_FILENAME]}))
            png_b64 = _extract_file_b64(files, CHART_FILENAME)
            if not png_b64:
                return {"ok": False, "error": "the code did not save a chart to chart.png"}
        return {
            "ok": True,
            "image_kind": "png_b64",
            "image": png_b64,
            "stdout": run.get("text", ""),
        }
    except Exception as exc:  # noqa: BLE001 — surface any sandbox/SDK error as a clean tool error
        return {"ok": False, "error": f"sandbox error: {exc}"}


def _drain(stream: Any) -> dict[str, Any]:
    """Collapse a Code Interpreter invoke() event stream into a single result dict."""
    text_parts: list[str] = []
    result: dict[str, Any] = {}
    for event in stream:
        res = event.get("result", event) if isinstance(event, dict) else {}
        if isinstance(res, dict):
            result.update(res)
            for item in res.get("content", []) or []:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
    if text_parts:
        result.setdefault("text", "\n".join(text_parts))
    return result


def _extract_file_b64(files_result: dict[str, Any], path: str) -> str:
    """Pull a base64 file body out of a readFiles result, tolerating shape variants."""
    for item in files_result.get("content", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("path") in (path, f"./{path}") or item.get("type") == "resource":
            return item.get("data") or item.get("blob") or item.get("text") or ""
    return files_result.get("data", "")


# ---------------------------------------------------------------------------
# Artifact upload + block building
# ---------------------------------------------------------------------------


def _upload_artifacts(chart_id: str, run: dict[str, Any], code: str) -> dict[str, str] | None:
    """Upload the PNG + script to S3, returning presigned GET URLs. Returns None
    when no bucket is configured (local / stub) so the caller inlines instead."""
    bucket = os.environ.get("FSI_CHART_BUCKET")
    if not bucket or run.get("image_kind") != "png_b64":
        return None
    import base64

    import boto3

    # Default 1h, not longer: a SigV4 presigned URL cannot outlive the runtime
    # execution role's temporary STS session (typically ~1h), so a larger value
    # is misleading — the URL 403s when the session expires regardless. Charts are
    # loaded immediately on render; a persisted transcript's chart may need
    # regenerating later.
    ttl = int(os.environ.get("FSI_CHART_URL_TTL_SECONDS", "3600"))
    s3 = boto3.client("s3", region_name=_chart_region())
    png_key = f"charts/{chart_id}.png"
    py_key = f"charts/{chart_id}.py"
    s3.put_object(
        Bucket=bucket, Key=png_key, Body=base64.b64decode(run["image"]), ContentType="image/png"
    )
    s3.put_object(Bucket=bucket, Key=py_key, Body=code.encode("utf-8"), ContentType="text/plain")
    return {
        "img": s3.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": png_key}, ExpiresIn=ttl
        ),
        "script": s3.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": py_key}, ExpiresIn=ttl
        ),
    }


def _inline_image(run: dict[str, Any]) -> str:
    """A data: URL for the image when there is no bucket (local / stub)."""
    if run.get("image_kind") == "svg":
        return "data:image/svg+xml;utf8," + quote(run["image"])
    return "data:image/png;base64," + run["image"]


def build_chart_block(
    chart_id: str, title: str, urls: dict[str, str] | None, run: dict, code: str
) -> str:
    """The fenced ``eatelligence-chart`` block the web app parses. The agent
    includes it verbatim in its reply; the image bytes and (long) script never
    have to round-trip through the model."""
    payload: dict[str, Any] = {"id": chart_id, "title": title, "lang": "python"}
    if urls:
        payload["img"] = urls["img"]
        payload["script"] = urls["script"]
    else:
        payload["img"] = _inline_image(run)
        payload["scriptText"] = code
    return "```eatelligence-chart\n" + json.dumps(payload) + "\n```"


# Markdown image the model sometimes fabricates from a chart's img URL — the chat
# renders `[label](url)` links but NOT `![alt](url)` images (and never a data: URL),
# so this never renders; strip it when we have the authoritative block to append.
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def merge_chart_blocks(text: str, blocks: list[str]) -> str:
    """Guarantee each generated chart block appears in the reply exactly once.

    The block must reach the web app inside the reply text (the wire contract is a
    single string), but the model (Nova 2 Lite) sometimes drops the block or
    reformats the chart as a markdown ``![alt](data:...)`` image the chat cannot
    render. Whenever a chart was generated this strips any markdown image the model
    fabricated and appends every block not already present — so the chart renders
    regardless of the model's compliance. A no-op when no chart was generated.
    """
    if not blocks:
        return text
    merged = _MD_IMAGE.sub("", text or "").rstrip()
    for block in blocks:
        b = (block or "").strip()
        if b and b not in merged:
            merged = (merged + "\n\n" + b).strip() if merged else b
    return merged


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], _ctx: Any) -> dict[str, Any]:
    """Entry point.

    Input event:
      { "code": str,          # pandas/matplotlib code; uses `df`, saves chart.png
        "title": str,         # short human title for the chart
        "city": str }         # active city (injected by the wrapper)

    Returns on success:
      { "status": "ok",
        "chart_id": str,
        "summary": str,       # the code's stdout — the real numbers, for the caption
        "chart_block": str }  # fenced eatelligence-chart block to include verbatim
    On failure:
      { "status": "error", "error": str }   # e.g. bad code, or the code raised
    """
    code = (event.get("code") or "").strip()
    title = (event.get("title") or "Chart").strip() or "Chart"
    city = event.get("city") or "chicago"
    if city not in ("chicago", "nyc", "la"):
        city = "chicago"

    if not code:
        return {"status": "error", "error": "no chart code provided"}
    if len(code) > MAX_CODE_CHARS:
        return {"status": "error", "error": "chart code is too long"}
    # A real sandbox run must have somewhere to put the PNG — otherwise the image
    # would be inlined into the model's reply as a 100KB+ base64 blob it has to
    # echo verbatim, which truncates. Fail fast on that misconfiguration.
    if not _use_stub() and not os.environ.get("FSI_CHART_BUCKET"):
        return {"status": "error", "error": "chart storage is not configured (FSI_CHART_BUCKET)"}

    run = _stub_run(code, city) if _use_stub() else _sandbox_run(code, city)
    if not run.get("ok"):
        return {"status": "error", "error": run.get("error", "chart generation failed")}

    chart_id = f"chart-{uuid.uuid4().hex[:12]}"
    urls = _upload_artifacts(chart_id, run, code)
    block = build_chart_block(chart_id, title, urls, run, code)
    return {
        "status": "ok",
        "chart_id": chart_id,
        "summary": run.get("stdout", ""),
        "chart_block": block,
    }
