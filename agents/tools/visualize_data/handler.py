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

import concurrent.futures
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


# Driver-topic families for "common drivers" questions. Prefix -> family, matched
# in order so distinct families (license_age vs license_n_history) don't shadow each
# other. Mirrors the keyword flags in interface_contracts.md and the frontend's
# driver-icons taxonomy, so "common drivers" means the same thing across the product.
# Applied in the RUNTIME (not the sandbox) — see _slim_record.
_TOPIC_PREFIXES = {
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
    "flag_kw_temp": "temperature",
    "flag_kw_cool": "temperature",
    "flag_kw_raw": "raw_food",
    "flag_kw_cross": "cross_contamination",
    "flag_kw_expired": "expired",
    "flag_kw_rodent": "pest",
    "flag_kw_pest": "pest",
    "flag_kw_no_soap": "handwashing",
    "flag_kw_handwash": "handwashing",
    "flag_kw_no_paper": "handwashing",
    "flag_kw_sewage": "sewage",
    "flag_kw_certified": "certified_manager",
}


def _driver_topic(feature: Any) -> str:
    """Map a SHAP feature name to its plain hazard/topic family."""
    if not feature:
        return "other"
    for prefix, topic in _TOPIC_PREFIXES.items():
        if str(feature).startswith(prefix):
            return topic
    return "other"


def _slim_record(r: dict) -> dict:
    """Project one score record to the columns a chart actually needs."""
    drivers = [d for d in (r.get("top_drivers") or []) if isinstance(d, dict)]
    top = drivers[0].get("feature") if drivers else None
    return {
        "license_id": r.get("license_id"),
        "dba_name": r.get("dba_name"),
        "as_of_date": r.get("as_of_date"),
        "risk_score": r.get("risk_score"),
        "risk_tier": r.get("risk_tier"),
        "trend_slope": r.get("trend_slope"),
        "neighborhood": r.get("neighborhood"),
        "zip": r.get("zip"),
        "facility_type": r.get("facility_type"),
        "top_driver": top,
        "top_driver_shap": drivers[0].get("shap") if drivers else None,
        "top_driver_topic": _driver_topic(top),
    }


SLIM_COLUMNS = (
    "license_id",
    "dba_name",
    "as_of_date",
    "risk_score",
    "risk_tier",
    "trend_slope",
    "neighborhood",
    "zip",
    "facility_type",
    "top_driver",
    "top_driver_shap",
    "top_driver_topic",
)


def _slim_payload(path: str) -> str:
    """A city's scores.json projected to the slim chart frame, as COLUMNAR JSON.

    The published scores.json is 20-40MB per city, dominated by fields a chart never
    needs (address, lat/lon, five nested top_drivers structs per row) — shipping all
    of it into the sandbox AND parsing it there blew the 60s request timeout.

    Two size levers, both material at ~42k rows:
      * project to chart columns and precompute the driver topic in the RUNTIME, so
        the sandbox never does a per-row rollup;
      * emit COLUMNAR ({col: [values]}) rather than a list of records — a records
        payload repeats all twelve key names on every row, which alone is megabytes.
    `pd.DataFrame(dict_of_lists)` consumes this directly.
    """
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    records = raw.get("scores", raw) if isinstance(raw, dict) else raw
    cols: dict[str, list] = {c: [] for c in SLIM_COLUMNS}
    for r in records:
        slim = _slim_record(r)
        for c in SLIM_COLUMNS:
            cols[c].append(slim[c])
    return json.dumps({"cols": cols})


# Setup cell run in the sandbox BEFORE the model's code. The frame is already slim
# and the driver topics are precomputed in the runtime, so this is just a load.
SETUP_CODE = f"""
import json
import matplotlib
matplotlib.use("Agg")  # headless: render to a file, no display
import pandas as pd

df = pd.DataFrame(json.load(open({DATA_FILENAME!r}, encoding="utf-8"))["cols"])
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
        scores_text = _slim_payload(scores_path)
    except FileNotFoundError:
        return {"ok": False, "error": f"no data file for {city}"}
    except (json.JSONDecodeError, TypeError, AttributeError) as exc:
        return {"ok": False, "error": f"could not read {city} chart data: {exc}"}

    try:
        # Lazy import: only the deployed runtime has (and needs) this SDK.
        from bedrock_agentcore.tools.code_interpreter_client import code_session

        region = _chart_region()
        interpreter_id = os.environ.get("FSI_CODE_INTERPRETER_ID")
        session_kwargs = {"identifier": interpreter_id} if interpreter_id else {}

        with code_session(region, **session_kwargs) as client:
            client.invoke("writeFiles", {"content": [{"path": DATA_FILENAME, "text": scores_text}]})
            # Setup + the model's snippet run as ONE cell, so `df` is guaranteed to
            # exist in the same execution rather than relying on variables surviving
            # across separate executeCode invocations.
            cell = SETUP_CODE + "\n" + code
            run = _drain(client.invoke("executeCode", {"language": "python", "code": cell}))
            output = (run.get("text") or "").strip()
            if run.get("isError"):
                return {"ok": False, "error": f"your chart code raised an error:\n{output[:800]}"}
            files = _drain(client.invoke("readFiles", {"paths": [CHART_FILENAME]}))
            png_b64 = _extract_file_b64(files, CHART_FILENAME)
            if not png_b64:
                # Say WHY and include whatever the cell printed/raised. Without this
                # the model can't tell what went wrong and just retries the same
                # broken snippet until the request times out.
                detail = f"\nThe code's output was:\n{output[:800]}" if output else ""
                return {
                    "ok": False,
                    "error": (
                        f"no {CHART_FILENAME} was produced. `df` is ALREADY loaded in the "
                        "sandbox — do NOT read any file (no pd.read_csv / pd.read_json / "
                        "open); there is no CSV. Use `df` directly and finish with "
                        f"fig.savefig('{CHART_FILENAME}')." + detail
                    ),
                }
        return {
            "ok": True,
            "image_kind": "png_b64",
            "image": png_b64,
            "stdout": output,
        }
    except Exception as exc:  # noqa: BLE001 — surface any sandbox/SDK error as a clean tool error
        return {"ok": False, "error": f"sandbox error: {exc}"}


_SANDBOX_TIMEOUT_S = int(os.environ.get("FSI_CHART_TIMEOUT_SECONDS", "25"))


def _run_sandbox_guarded(code: str, city: str, timeout_s: float | None = None) -> dict[str, Any]:
    """Run the sandbox under a hard wall-clock cap.

    A chart is generated inside a synchronous chat request whose gateway budget is
    ~60s (ALB idle / CloudFront origin timeout), so a slow or hung run surfaces as an
    opaque 504. Capping it returns a clean tool error the agent can relay instead.

    `timeout_s` lets the caller shrink the cap to whatever request budget is actually
    left. That matters because a single cap is NOT enough: on a timeout the model may
    call the tool again, and two capped attempts still add up past the ceiling. The
    caller passes the remaining budget so retries can never overrun it.
    """
    cap = float(timeout_s) if timeout_s else float(_SANDBOX_TIMEOUT_S)
    cap = max(5.0, min(cap, float(_SANDBOX_TIMEOUT_S)))
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return ex.submit(_sandbox_run, code, city).result(timeout=cap)
    except concurrent.futures.TimeoutError:
        return {
            "ok": False,
            "timed_out": True,
            "error": (
                f"chart generation timed out after {cap:.0f}s — the dataset is large; "
                "try a simpler chart or a narrower filter"
            ),
        }
    finally:
        ex.shutdown(wait=False)  # never block the request on an orphaned run


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

    run = (
        _stub_run(code, city)
        if _use_stub()
        else _run_sandbox_guarded(code, city, event.get("timeout_s"))
    )
    if not run.get("ok"):
        out: dict[str, Any] = {"status": "error", "error": run.get("error", "chart failed")}
        if run.get("timed_out"):
            # Terminal for this turn: retrying stacks another cap onto an already
            # spent request budget and lands on the gateway's 504.
            out["retryable"] = False
        return out

    chart_id = f"chart-{uuid.uuid4().hex[:12]}"
    urls = _upload_artifacts(chart_id, run, code)
    block = build_chart_block(chart_id, title, urls, run, code)
    return {
        "status": "ok",
        "chart_id": chart_id,
        "summary": run.get("stdout", ""),
        "chart_block": block,
    }
