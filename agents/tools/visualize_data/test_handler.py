"""
Tests for visualize_data — the chart-generation tool, in STUB mode.

Stub mode (the default) never runs a sandbox or executes the code: it echoes a
placeholder image + the code, so the handler's contract (validation, block
format, city scoping) is testable offline with no AWS and without executing
untrusted code. The live sandbox path is validated on deploy, not here.
"""

from __future__ import annotations

import base64
import json
import os
import sys

_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from handler import (  # noqa: E402
    MAX_CODE_CHARS,
    SLIM_COLUMNS,
    _missing_column,
    _setup_code,
    _slim_payload,
    _slim_record,
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


# _slim_record — the runtime-side projection that keeps the sandbox payload small
# (shipping the full 20-40MB scores.json blew the 60s request timeout).


def test_slim_record_drops_heavy_fields_and_rolls_up_driver_topics():
    s = _slim_record(
        {
            "license_id": "1",
            "dba_name": "X",
            "address": "123 Main",
            "lat": 1.0,
            "lon": 2.0,
            "as_of_date": "2026-01-01",
            "risk_score": 0.5,
            "risk_tier": "Low",
            "trend_slope": 0.01,
            "neighborhood": "N",
            "zip": "60622",
            "facility_type": "Restaurant",
            "trend_ci_low": 0,
            "trend_ci_high": 1,
            "top_drivers": [
                {"feature": "flag_kw_rodent_x", "shap": 0.9},
                {"feature": "n_priority_this_inspection", "shap": 0.2},
            ],
        }
    )
    # heavy / unused fields dropped
    for dropped in ("address", "lat", "lon", "trend_ci_low", "top_drivers"):
        assert dropped not in s
    # driver topic precomputed in the runtime, not the sandbox
    assert s["top_driver"] == "flag_kw_rodent_x"
    assert s["top_driver_topic"] == "pest"
    assert s["top_driver_shap"] == 0.9
    # charting columns kept
    assert s["risk_tier"] == "Low"
    assert s["neighborhood"] == "N"


def test_slim_record_handles_a_record_with_no_drivers():
    s = _slim_record({"license_id": "2"})
    assert s["top_driver"] is None
    assert s["top_driver_topic"] == "other"


def test_timeout_is_capped_and_marked_non_retryable(monkeypatch):
    """A timed-out run must be terminal for the turn: the model retrying would stack
    a second cap onto the request budget and hit the gateway's 504 (the prod bug)."""
    import time as _time

    import handler as h

    monkeypatch.setenv("FSI_SANDBOX_USE_STUB", "false")
    monkeypatch.setenv("FSI_CHART_BUCKET", "some-bucket")
    monkeypatch.setattr(h, "_sandbox_run", lambda code, city: _time.sleep(30))
    out = h.handler({"code": CODE, "title": "t", "city": "chicago", "timeout_s": 5}, None)
    assert out["status"] == "error"
    assert out["retryable"] is False
    assert "timed out" in out["error"]


# A minimal whole PNG: magic header + body + the closing IEND chunk.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"payload" + b"IEND\xaeB`\x82"
_PNG_B64 = base64.b64encode(_PNG_BYTES).decode()


def test_split_chart_b64_extracts_png_and_strips_it_from_the_summary():
    """The PNG rides back on stdout (readFiles response shapes proved unreliable),
    but the base64 must never reach the model as part of the caption summary."""
    from handler import CHART_B64_MARKER, _split_chart_b64

    text = "pest    10\ntemperature 4\n" + CHART_B64_MARKER + _PNG_B64 + "\ntrailing note"
    b64, rest = _split_chart_b64(text)
    assert b64 == _PNG_B64
    assert CHART_B64_MARKER not in rest
    assert _PNG_B64 not in rest
    assert "pest    10" in rest and "trailing note" in rest


def test_split_chart_b64_is_noop_without_the_marker():
    from handler import _split_chart_b64

    assert _split_chart_b64("just some printed output") == ("", "just some printed output")


def test_split_chart_b64_rejects_a_truncated_or_non_png_payload():
    """Truncated stdout would otherwise hand the app a corrupt image that renders as a
    silently broken chart. Returning no PNG lets the readFiles fallback try instead."""
    from handler import CHART_B64_MARKER, _split_chart_b64

    truncated = base64.b64encode(_PNG_BYTES[:-6]).decode()  # header intact, IEND lost
    for bad in (base64.b64encode(b"not a png").decode(), truncated, "!!!not base64!!!"):
        b64, rest = _split_chart_b64("counts\n" + CHART_B64_MARKER + bad + "\ntail")
        assert b64 == ""
        assert "counts" in rest and "tail" in rest


def test_slim_payload_is_columnar(tmp_path):
    """Columnar ({col: [values]}) — a records payload repeats every key name on
    every row, which is megabytes at 20-40k rows."""
    p = tmp_path / "scores.json"
    p.write_text(
        json.dumps(
            {
                "scores": [
                    {
                        "license_id": "1",
                        "risk_tier": "Low",
                        "top_drivers": [{"feature": "flag_kw_pest_x", "shap": 0.4}],
                    },
                    {"license_id": "2", "risk_tier": "High", "top_drivers": []},
                ]
            }
        )
    )
    payload, live = _slim_payload(str(p))
    d = json.loads(payload)
    # Columns empty in every row are dropped (see the empty-column guard); the
    # fixture populates only some, so compare against what came back as live.
    assert set(d["cols"]) == set(live)
    assert set(live) <= set(SLIM_COLUMNS)  # never invents a column
    assert d["cols"]["license_id"] == ["1", "2"]
    assert d["cols"]["risk_tier"] == ["Low", "High"]
    assert d["cols"]["top_driver_topic"] == ["pest", "other"]


# ---------------------------------------------------------------------------
# Empty-column guard
#
# The bug these exist for: neighborhood / zip / facility_type were shipped as
# advertised chart filters while being EMPTY in every row of every city. The
# model's filter then matched nothing and got back a valid empty frame with no
# error, so it concluded the city had no such places and apologised. A dead
# filter is worse than a missing one, because nothing anywhere raises.
# ---------------------------------------------------------------------------


def _payload_with(records: list[dict], tmp_path):
    p = tmp_path / "scores.json"
    p.write_text(json.dumps({"scores": records}))
    text, live = _slim_payload(str(p))
    return json.loads(text), live


def test_column_empty_in_every_row_is_dropped(tmp_path):
    # Chicago's real shape: zip populated, neighborhood empty on every row.
    records = [
        {"license_id": "1", "risk_tier": "Low", "zip": "60614", "neighborhood": ""},
        {"license_id": "2", "risk_tier": "High", "zip": "60618", "neighborhood": ""},
    ]
    d, live = _payload_with(records, tmp_path)

    assert "neighborhood" not in live
    assert "neighborhood" not in d["cols"]
    assert "zip" in live and d["cols"]["zip"] == ["60614", "60618"]


def test_column_populated_in_only_some_rows_is_kept(tmp_path):
    # Partial coverage is real data (NYC zip is 98.9%), not a dead column.
    records = [
        {"license_id": "1", "risk_tier": "Low", "neighborhood": "Manhattan"},
        {"license_id": "2", "risk_tier": "High", "neighborhood": ""},
    ]
    _, live = _payload_with(records, tmp_path)
    assert "neighborhood" in live


def test_identity_columns_survive_even_when_empty(tmp_path):
    # Dropping dba_name would break every chart that labels a bar, so the frame's
    # identity/measure columns are exempt from the guard.
    records = [{"license_id": "1", "dba_name": "", "risk_tier": "Low"}]
    _, live = _payload_with(records, tmp_path)
    assert {"license_id", "dba_name", "risk_tier"} <= set(live)


def test_setup_code_names_the_live_columns():
    code = _setup_code(("license_id", "zip"))
    assert "license_id, zip" in code
    assert "pd.DataFrame" in code


def test_missing_column_identifies_a_dropped_filter():
    tb = "Traceback (most recent call last):\n  ...\nKeyError: 'neighborhood'"
    assert _missing_column(tb, ("license_id", "zip")) == "neighborhood"


def test_missing_column_ignores_a_genuine_code_bug():
    # A KeyError on something that was never a chart column is the model's own bug;
    # it must keep its real traceback rather than be reported as a city data gap.
    tb = "KeyError: 'not_a_real_column'"
    assert _missing_column(tb, ("license_id", "zip")) == ""
    # And a non-KeyError error is never reinterpreted.
    assert _missing_column("ValueError: bad shape", ("license_id",)) == ""


def test_missing_column_ignores_a_column_that_is_live():
    tb = "KeyError: 'zip'"
    assert _missing_column(tb, ("license_id", "zip")) == ""
