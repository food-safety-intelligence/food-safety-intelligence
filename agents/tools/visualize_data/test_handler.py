"""
Tests for visualize_data — the chart-generation tool, in STUB mode.

Stub mode (the default) never runs a sandbox or executes the code: it echoes a
placeholder image + the code, so the handler's contract (validation, block
format, city scoping) is testable offline with no AWS and without executing
untrusted code. The live sandbox path is validated on deploy, not here.
"""

from __future__ import annotations

import base64
import gzip
import json
import os
import sys

import pytest

_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from handler import (  # noqa: E402
    MAX_CODE_CHARS,
    SLIM_COLUMNS,
    _driver_topic,
    _missing_column,
    _setup_code,
    _slim_payload,
    _slim_record,
    _wire_payload,
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


def test_wire_payload_round_trips_through_gzip(tmp_path):
    """The frame crosses into the sandbox gzipped, because that upload is the biggest
    cost inside the chart time budget (Los Angeles: 6.05MB of JSON -> ~1.6MB). The
    setup cell must be able to unpack exactly what was packed."""
    p = tmp_path / "scores.json"
    p.write_text(
        json.dumps(
            {
                "scores": [
                    {"license_id": "1", "risk_tier": "Low", "risk_score": 0.16979999840259552},
                    {"license_id": "2", "risk_tier": "High", "risk_score": 0.5821000933647156},
                ]
            }
        )
    )
    raw, raw_live = _slim_payload(str(p))
    wire, wire_live = _wire_payload(str(p))
    assert wire_live == raw_live
    assert gzip.decompress(base64.b64decode(wire)).decode("utf-8") == raw


def test_wire_payload_shrinks_a_realistic_frame(tmp_path):
    """Compression only pays at real row counts (base64 overhead dominates a handful
    of rows), and real frames repeat a small vocabulary of tiers, ZIPs and driver
    names — which is exactly what gzip collapses."""
    p = tmp_path / "scores.json"
    p.write_text(
        json.dumps(
            {
                "scores": [
                    {
                        "license_id": f"FA{i:07d}",
                        "dba_name": f"TEST RESTAURANT {i % 500}",
                        "risk_tier": ["Low", "Moderate", "Elevated", "High"][i % 4],
                        "zip": str(90001 + (i % 300)),
                        "risk_score": (i % 1000) / 1000,
                        "top_drivers": [{"feature": "cur_theme_pest_vermin", "shap": 0.4}],
                    }
                    for i in range(5000)
                ]
            }
        )
    )
    raw, _ = _slim_payload(str(p))
    wire, _ = _wire_payload(str(p))
    assert gzip.decompress(base64.b64decode(wire)).decode("utf-8") == raw
    # Measured about a quarter on the real Los Angeles frame; keep a loose bound so
    # this asserts the win without pinning an exact ratio.
    assert len(wire) < len(raw) / 2


def test_scores_are_rounded_for_the_wire(tmp_path):
    """A calibrated probability serialises at full float64 width (21 bytes) and the
    frame carries three such columns. No chart resolves past four decimals."""
    p = tmp_path / "scores.json"
    p.write_text(
        json.dumps(
            {
                "scores": [
                    {
                        "license_id": "1",
                        "risk_score": 0.16979999840259552,
                        "trend_slope": 0.123456789,
                        "top_drivers": [{"feature": "cur_theme_pest_vermin", "shap": 0.48551234}],
                    }
                ]
            }
        )
    )
    cols = json.loads(_slim_payload(str(p))[0])["cols"]
    assert cols["risk_score"] == [0.1698]
    assert cols["trend_slope"] == [0.12346]
    assert cols["top_driver_shap"] == [0.4855]


def test_wire_payload_is_cached_per_path(tmp_path):
    """Every other agent tool caches its loader; this one did not, so each chart
    re-read and re-projected the whole 20-42MB file inside the time budget. The cache
    sits on _wire_payload (not _slim_payload), so the raw JSON is not pinned too."""
    p = tmp_path / "scores.json"
    p.write_text(json.dumps({"scores": [{"license_id": "1", "risk_tier": "Low"}]}))
    first = _wire_payload(str(p))
    # Rewriting the file must NOT change the answer while the cache is warm — proof
    # the second call never touched disk.
    p.write_text(json.dumps({"scores": [{"license_id": "999", "risk_tier": "High"}]}))
    assert _wire_payload(str(p)) is first
    # The projection itself is intentionally uncached, so it re-reads.
    assert json.loads(_slim_payload(str(p))[0])["cols"]["license_id"] == ["999"]


@pytest.mark.parametrize(
    ("feature", "topic"),
    [
        # Los Angeles / New York publish themed violation features; none of these
        # matched the Chicago-only prefix table, so LA collapsed to three topics
        # with 57% of rows in "other" and violation-category charts were meaningless.
        ("cur_theme_pest_vermin", "pest"),
        ("cur_theme_temperature_control", "temperature"),
        ("cur_theme_hygiene_handwashing", "handwashing"),
        ("cur_theme_cross_contamination_protection", "cross_contamination"),
        ("cur_theme_plumbing_sewage_water", "sewage"),
        ("cur_theme_equipment_nonfood_surface", "equipment_surface"),
        ("cur_score", "inspection_score"),
        ("prior_mean_score", "inspection_score"),
        ("cur_n_viol", "violation_count"),
        ("cur_sev_T3", "violation_severity"),
        ("prior_cur_sev_T1", "violation_severity"),
        ("tenure_days", "license_age"),
        # Chicago's own vocabulary must be unaffected.
        ("was_fail", "inspection_outcome"),
        ("flag_kw_rodent", "pest"),
        ("days_since_last_inspection", "recency"),
    ],
)
def test_driver_topic_covers_every_city_vocabulary(feature, topic):
    assert _driver_topic(feature) == topic


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
