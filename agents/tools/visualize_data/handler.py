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

import base64
import binascii
import concurrent.futures
import functools
import gzip
import json
import os
import re
import uuid
from collections.abc import Sequence
from typing import Any
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHART_FILENAME = "chart.png"  # the path the model's code must savefig() to
# The sandbox prints the rendered PNG as base64 behind this marker. Reading the
# image back out of stdout avoids depending on the readFiles response shape (which
# varies by SDK version and silently yielded "no chart produced" in production even
# when the code had rendered fine). readFiles stays as a fallback.
CHART_B64_MARKER = "__FSI_CHART_B64__"
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
    # Themed violation families. LA and NYC name these `cur_theme_*`; they are listed
    # before the broader `cur_*` measures so a theme never falls through to a score or
    # count bucket. Without them LA collapsed to three topics, 57% of them "other",
    # which made every violation-category chart for that city meaningless.
    "cur_theme_pest_vermin": "pest",
    "cur_theme_temperature_control": "temperature",
    "cur_theme_hygiene_handwashing": "handwashing",
    "cur_theme_cross_contamination_protection": "cross_contamination",
    "cur_theme_plumbing_sewage_water": "sewage",
    "cur_theme_management_certification": "certified_manager",
    "cur_theme_food_contact_surface": "food_contact_surface",
    "cur_theme_equipment_nonfood_surface": "equipment_surface",
    "cur_theme_approved_source_food_safety": "approved_source",
    "cur_theme_other_administrative": "administrative",
    # Current / prior inspection measures in the LA and NYC feature sets.
    "cur_score": "inspection_score",
    "prev_score": "inspection_score",
    "prior_mean_score": "inspection_score",
    "cur_n_viol": "violation_count",
    "cur_n_critical": "violation_count",
    "prior_n_critical": "violation_count",
    "cur_sev": "violation_severity",
    "prior_cur_sev": "violation_severity",
    "cur_is_bad": "inspection_outcome",
    "cur_closed": "closure",
    "prior_closures": "closure",
    "prior_bad": "prior_failures",
    "tenure_days": "license_age",
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


def _round(x: Any, places: int) -> Any:
    """Round a float for the wire, leaving None and non-numerics untouched.

    A calibrated probability serialises at full float64 precision
    (0.16979999840259552 — 21 bytes), and the frame carries three such columns over
    tens of thousands of rows. No chart resolves past four decimals, so rounding is
    free accuracy-wise and takes a material bite out of the payload that has to be
    uploaded into the sandbox inside the request budget.
    """
    return round(x, places) if isinstance(x, (int, float)) and not isinstance(x, bool) else x


def _slim_record(r: dict) -> dict:
    """Project one score record to the columns a chart actually needs."""
    drivers = [d for d in (r.get("top_drivers") or []) if isinstance(d, dict)]
    top = drivers[0].get("feature") if drivers else None
    return {
        "license_id": r.get("license_id"),
        "dba_name": r.get("dba_name"),
        "as_of_date": r.get("as_of_date"),
        "risk_score": _round(r.get("risk_score"), 4),
        "risk_tier": r.get("risk_tier"),
        "trend_slope": _round(r.get("trend_slope"), 5),
        "neighborhood": r.get("neighborhood"),
        "zip": r.get("zip"),
        "facility_type": r.get("facility_type"),
        "top_driver": top,
        "top_driver_shap": _round(drivers[0].get("shap"), 4) if drivers else None,
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


# Columns that must survive even if empty — the frame's identity and measures. Only
# the descriptive/filter columns are subject to the empty-column guard below.
_REQUIRED_COLUMNS = ("license_id", "dba_name", "as_of_date", "risk_score", "risk_tier")


def _slim_payload(path: str) -> tuple[str, tuple[str, ...]]:
    """A city's scores.json projected to the slim chart frame, as COLUMNAR JSON.

    Returns (columnar_json, live_columns).

    Deliberately NOT cached: only `_wire_payload` calls it, and that is cached, so
    caching here too would pin ~12.5MB of raw JSON across the three cities that is
    never read again.

    The published scores.json is 20-40MB per city, dominated by fields a chart never
    needs (address, lat/lon, five nested top_drivers structs per row) — shipping all
    of it into the sandbox AND parsing it there blew the 60s request timeout.

    Two size levers, both material at ~42k rows:
      * project to chart columns and precompute the driver topic in the RUNTIME, so
        the sandbox never does a per-row rollup;
      * emit COLUMNAR ({col: [values]}) rather than a list of records — a records
        payload repeats all twelve key names on every row, which alone is megabytes.
    `pd.DataFrame(dict_of_lists)` consumes this directly.

    Empty-column guard: a descriptive column that is empty in EVERY row is dropped
    rather than shipped. Shipping it produced the worst possible failure — the
    model's filter matched nothing, so it got a valid empty frame back, no error,
    and concluded the city had no such places. Dropping it turns that silent wrong
    answer into a loud KeyError the handler converts into a retry naming the live
    columns. Geography legitimately varies by city (Chicago publishes no
    neighborhood, only zip), so this is a permanent condition, not a transient one.
    """
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    records = raw.get("scores", raw) if isinstance(raw, dict) else raw
    cols: dict[str, list] = {c: [] for c in SLIM_COLUMNS}
    for r in records:
        slim = _slim_record(r)
        for c in SLIM_COLUMNS:
            cols[c].append(slim[c])
    live = tuple(
        c
        for c in SLIM_COLUMNS
        if c in _REQUIRED_COLUMNS or any(v not in (None, "") for v in cols[c])
    )
    return json.dumps({"cols": {c: cols[c] for c in live}}), live


@functools.lru_cache(maxsize=3)
def _wire_payload(path: str) -> tuple[str, tuple[str, ...]]:
    """The slim frame as gzipped base64, which is what actually crosses into the box.

    `writeFiles` ships the frame as one text argument, and that upload is the single
    biggest cost inside the chart time budget — Los Angeles alone is 6.05MB of JSON.
    Columnar JSON of repeated tiers, ZIPs and driver names compresses to about a
    quarter (LA: 6.05MB -> 1.59MB), for ~0.05s to compress here and ~0.03s to
    unpack in the sandbox. Cached per city alongside the projection itself.
    """
    text, live = _slim_payload(path)
    return base64.b64encode(gzip.compress(text.encode("utf-8"), 1)).decode("ascii"), live


def _setup_code(live_columns: Sequence[str]) -> str:
    """Setup cell run in the sandbox BEFORE the model's code. The frame is already
    slim and the driver topics are precomputed in the runtime, so this is just a
    decompress and load. The live column list is noted here so a stale expectation
    fails loudly inside the cell rather than silently yielding an empty filter."""
    return f"""
import base64, gzip, json
import matplotlib
matplotlib.use("Agg")  # headless: render to a file, no display
import pandas as pd

with open({DATA_FILENAME!r}, encoding="ascii") as _fsi_f:
    df = pd.DataFrame(json.loads(gzip.decompress(base64.b64decode(_fsi_f.read())))["cols"])
# Columns available for THIS city: {", ".join(live_columns)}
"""


# Appended AFTER the model's snippet: emit the rendered PNG on stdout so the handler
# never has to parse a readFiles response. Only runs if the snippet actually saved a
# figure, so a snippet that raised still surfaces its traceback instead.
EPILOGUE_CODE = f"""
import base64 as _fsi_b64, os as _fsi_os
if _fsi_os.path.exists({CHART_FILENAME!r}):
    print("{CHART_B64_MARKER}" + _fsi_b64.b64encode(open({CHART_FILENAME!r}, "rb").read()).decode())
"""


MAX_SUMMARY_CHARS = 4000


def _capped_summary(stdout: str) -> str:
    """Bound the printed numbers handed back to the model.

    `summary` is whatever the model's code printed, and the model is told to print
    the rows it wants to talk about. One forgotten slice — `print(df)` on a 42,270-row
    frame — would otherwise push the entire dataset back through the context. The
    error paths were already capped; this is the success path.
    """
    if len(stdout) <= MAX_SUMMARY_CHARS:
        return stdout
    return stdout[:MAX_SUMMARY_CHARS] + (
        "\n[truncated — the code printed more than fits. Print only the rows or "
        "aggregates you need, e.g. a head()/nlargest() slice.]"
    )


def _split_chart_b64(text: str) -> tuple[str, str]:
    """Pull the marker-tagged base64 PNG out of the cell's stdout.

    Returns (png_base64, remaining_text). The base64 must never reach the model — it
    would be hundreds of KB of noise in the tool result — so it is stripped from the
    text that becomes the caption `summary`.
    """
    if not text or CHART_B64_MARKER not in text:
        return "", text or ""
    before, _, rest = text.partition(CHART_B64_MARKER)
    b64, _, after = rest.partition("\n")
    b64 = b64.strip()
    remainder = (before + after).strip()
    # A PNG is ~100KB of base64; if the sandbox truncated stdout we'd hand the app a
    # corrupt image, which renders as a silently broken chart. Check BOTH ends: the
    # magic-byte header alone still passes on a truncated file, so require the closing
    # IEND chunk too. Anything short of a whole PNG falls through to readFiles.
    try:
        png = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return "", remainder
    if not (png.startswith(b"\x89PNG\r\n\x1a\n") and png.endswith(b"IEND\xaeB`\x82")):
        return "", remainder
    return b64, remainder


# ---------------------------------------------------------------------------
# Sandbox execution
# ---------------------------------------------------------------------------


def _missing_column(traceback_text: str, live_columns: Sequence[str]) -> str:
    """The column name from a pandas KeyError, when it's one the chart frame knows
    about but this city doesn't publish. Returns "" for any other error, so a genuine
    bug in the model's code still surfaces its real traceback."""
    if "KeyError" not in traceback_text:
        return ""
    for name in re.findall(r"KeyError: ['\"]([^'\"]+)['\"]", traceback_text):
        if name in SLIM_COLUMNS and name not in live_columns:
            return name
    return ""


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
        scores_text, live_columns = _wire_payload(scores_path)
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
            cell = _setup_code(live_columns) + "\n" + code + "\n" + EPILOGUE_CODE
            run = _drain(client.invoke("executeCode", {"language": "python", "code": cell}))
            png_b64, output = _split_chart_b64(run.get("text") or "")
            output = output.strip()
            if not png_b64 and run.get("isError"):
                # A KeyError names a column this city doesn't publish (see the
                # empty-column guard in _slim_payload). Say which columns DO exist so
                # the retry can succeed instead of guessing the same name again.
                dead = _missing_column(output, live_columns)
                if dead:
                    return {
                        "ok": False,
                        "error": (
                            f"this city's data has no {dead!r} column, so that filter or "
                            f"grouping cannot work here. Available columns: "
                            f"{', '.join(live_columns)}. Rewrite the code using only "
                            f"those, or tell the user that breakdown isn't available "
                            f"for this city."
                        ),
                    }
                return {"ok": False, "error": f"your chart code raised an error:\n{output[:800]}"}
            files: dict[str, Any] = {}
            if not png_b64:
                # Fallback for SDK versions that don't stream stdout the same way.
                files = _drain(client.invoke("readFiles", {"paths": [CHART_FILENAME]}))
                png_b64 = _extract_file_b64(files, CHART_FILENAME)
            if not png_b64:
                # Diagnostic into CloudWatch: the response shapes we failed to parse.
                print(
                    f"[visualize_data] no PNG — exec_keys={sorted(run)[:8]} "
                    f"readFiles_keys={sorted(files)[:8]} out={output[:200]!r}"
                )
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
        "summary": _capped_summary(run.get("stdout", "")),
        "chart_block": block,
    }
