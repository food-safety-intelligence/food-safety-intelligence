"""
Tests for visualize_data — the chart-generation tool, in STUB mode.

Stub mode (the default) never runs a sandbox or executes the code: it echoes a
placeholder image + the code, so the handler's contract (validation, block
format, city scoping) is testable offline with no AWS and without executing
untrusted code. The live sandbox path is validated on deploy, not here.
"""

from __future__ import annotations

import json
import os
import sys

_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from handler import (  # noqa: E402
    MAX_CODE_CHARS,
    build_chart_block,
    handler,
    merge_chart_blocks,
)

CODE = "import matplotlib.pyplot as plt\nplt.plot([1,2,3]); plt.savefig('chart.png')\nprint('n=3')"


def _parse_block(block: str) -> dict:
    """Pull the JSON out of a fenced eatelligence-chart block (as the web app does)."""
    assert block.startswith("```eatelligence-chart\n")
    assert block.rstrip().endswith("```")
    body = block.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(body)


def test_ok_returns_parseable_block_with_inline_script():
    out = handler({"code": CODE, "title": "My chart", "city": "chicago"}, None)
    assert out["status"] == "ok"
    assert out["chart_id"].startswith("chart-")
    assert out["summary"]  # stub stdout is non-empty

    obj = _parse_block(out["chart_block"])
    assert obj["id"] == out["chart_id"]
    assert obj["title"] == "My chart"
    assert obj["lang"] == "python"
    # No bucket configured in tests → image inlined as a data URL, script inlined verbatim.
    assert obj["img"].startswith("data:image/")
    assert obj["scriptText"] == CODE
    assert "script" not in obj  # no presigned URL without a bucket


def test_empty_code_errors():
    out = handler({"code": "   ", "title": "x", "city": "chicago"}, None)
    assert out["status"] == "error"
    assert "no chart code" in out["error"]


def test_overlong_code_errors():
    out = handler({"code": "x" * (MAX_CODE_CHARS + 1), "title": "x", "city": "chicago"}, None)
    assert out["status"] == "error"
    assert "too long" in out["error"]


def test_missing_title_defaults():
    out = handler({"code": CODE, "city": "chicago"}, None)
    assert out["status"] == "ok"
    assert _parse_block(out["chart_block"])["title"] == "Chart"


def test_city_passthrough_and_coercion():
    for city in ("nyc", "la", "chicago"):
        out = handler({"code": CODE, "title": "t", "city": city}, None)
        assert out["status"] == "ok"
    # An unknown city is coerced, not errored.
    out = handler({"code": CODE, "title": "t", "city": "boston"}, None)
    assert out["status"] == "ok"


def test_sandbox_enabled_without_bucket_fails_fast(monkeypatch):
    # Real sandbox but no bucket: must error, NOT inline a huge base64 PNG into the reply.
    monkeypatch.setenv("FSI_SANDBOX_USE_STUB", "false")
    monkeypatch.delenv("FSI_CHART_BUCKET", raising=False)
    out = handler({"code": CODE, "title": "x", "city": "chicago"}, None)
    assert out["status"] == "error"
    assert "FSI_CHART_BUCKET" in out["error"]


def test_block_uses_presigned_urls_when_provided():
    urls = {"img": "https://cdn.example/c.png", "script": "https://cdn.example/c.py"}
    run = {"image_kind": "png_b64", "image": "AAAA"}
    block = build_chart_block("chart-abc", "Title", urls, run, CODE)
    obj = _parse_block(block)
    assert obj["img"] == urls["img"]
    assert obj["script"] == urls["script"]
    assert "scriptText" not in obj  # the long script travels as a URL, not inline


# merge_chart_blocks — the server-side guarantee that a generated chart renders
# even when the model drops or reformats the block (the prod bug it fixes).

_BLOCK = build_chart_block("chart-1", "T", None, {"image_kind": "svg", "image": "<svg/>"}, CODE)


def test_merge_appends_dropped_block_and_strips_fabricated_markdown_image():
    # Model dropped the block and fabricated a markdown image instead (the live bug).
    text = "Here is your chart.\n![T](data:image/svg+xml;utf8,%3Csvg/%3E)\nHope it helps."
    out = merge_chart_blocks(text, [_BLOCK])
    assert "![" not in out  # fabricated markdown image stripped
    assert _BLOCK in out  # authoritative block appended
    assert out.count("eatelligence-chart") == 1


def test_merge_does_not_double_when_block_already_present():
    text = "Here is your chart.\n" + _BLOCK
    out = merge_chart_blocks(text, [_BLOCK])
    assert out.count("eatelligence-chart") == 1


def test_merge_is_noop_without_generated_charts():
    text = "no charts here, just a link [CDC](https://cdc.gov)"
    assert merge_chart_blocks(text, []) == text
