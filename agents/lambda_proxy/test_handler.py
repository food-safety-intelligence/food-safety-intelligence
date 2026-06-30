"""
Tests for the ALB → AgentCore proxy Lambda — the deterministic, offline parts:

  1. `_bounded_history`: the size guard on untrusted client history.
  2. The handler forwards `query` AND `history` to invoke_agent_runtime (the bug
     this fixes: history used to be dropped, so multi-turn context never reached
     the agent), with the session id as runtimeSessionId.

The boto3 call is stubbed — nothing here hits the network or AWS.
"""

from __future__ import annotations

import json
import os
import sys

# AGENT_RUNTIME_ARN is read at import time; set a dummy before importing.
os.environ.setdefault("AGENT_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-west-2:0:runtime/test")
os.environ.setdefault("AWS_REGION", "us-west-2")

# Allow running from the repo root or from this directory.
_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import handler as h  # noqa: E402

_SID = "0123456789-0123456789-0123456789-0123"  # >= 33 chars so it's kept as-is


def _invoke(body: dict):
    """Call the handler with the boto3 invoke stubbed; return (response, payload)."""
    captured: dict = {}

    def fake_invoke(**kwargs):
        captured.update(kwargs)
        return {"response": [json.dumps({"result": "ok"}).encode("utf-8")]}

    # Replace only the one method, so _client.exceptions (used in the handler's
    # except clauses) still resolves on the real client.
    h._client.invoke_agent_runtime = fake_invoke
    resp = h.handler({"httpMethod": "POST", "body": json.dumps(body)}, None)
    payload = json.loads(captured["payload"].decode("utf-8")) if "payload" in captured else None
    return resp, payload, captured


def test_history_is_forwarded():
    body = {
        "query": "is the second one safe too?",
        "session_id": _SID,
        "history": [
            {"role": "user", "content": "Tell me about Mirai Sushi."},
            {"role": "agent", "content": "Mirai Sushi is Low risk."},
        ],
    }
    resp, payload, captured = _invoke(body)
    assert resp["statusCode"] == 200
    assert payload["query"] == "is the second one safe too?"
    # The fix: history reaches the runtime (it used to be dropped here).
    assert payload["history"] == body["history"]
    # Session id is passed as the runtime session, not in the body payload.
    assert captured["runtimeSessionId"] == _SID
    assert "session_id" not in payload


def test_no_history_key_when_absent_or_not_a_list():
    for hist in (None, "nope", {}, []):
        body = {"query": "hi", "session_id": _SID}
        if hist is not None:
            body["history"] = hist
        _resp, payload, _ = _invoke(body)
        assert payload["query"] == "hi"
        assert "history" not in payload


def test_history_is_bounded_in_count_and_length():
    long = "x" * (h._MAX_MESSAGE_CHARS + 500)
    raw = [{"role": "user", "content": f"{long}-{i}"} for i in range(h._MAX_HISTORY_MESSAGES + 12)]
    _resp, payload, _ = _invoke({"query": "q", "session_id": _SID, "history": raw})
    fwd = payload["history"]
    # Only the last N turns survive...
    assert len(fwd) == h._MAX_HISTORY_MESSAGES
    # ...and each is truncated to the per-message cap.
    assert all(len(t["content"]) == h._MAX_MESSAGE_CHARS for t in fwd)
    # The kept window is the most-recent one (tail of the input).
    assert fwd[-1]["content"].startswith("x")


def test_malformed_history_entries_are_dropped():
    raw = [
        {"role": "user", "content": "keep me"},
        {"role": "user", "content": ""},  # empty → dropped
        {"role": "user", "content": "   "},  # whitespace → dropped
        {"role": "user"},  # no content → dropped
        "not a dict",  # wrong type → dropped
        {"role": "agent", "content": 123},  # non-str content → dropped
    ]
    _resp, payload, _ = _invoke({"query": "q", "session_id": _SID, "history": raw})
    assert payload["history"] == [{"role": "user", "content": "keep me"}]


def test_query_still_validated():
    resp, _payload, _ = _invoke({"query": "", "session_id": _SID})
    assert resp["statusCode"] == 400
