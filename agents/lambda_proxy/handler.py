"""
Lambda proxy — Food Safety Intelligence
-----------------------------------------
Sits between the public ALB and the AgentCore Runtime.  Accepts plain JSON
from the internet, signs the InvokeAgentRuntime call with the Lambda execution
role, and returns the agent response.

Environment variables (set in Lambda config):
    AGENT_RUNTIME_ARN   ARN of the deployed AgentCore Runtime agent
    AWS_REGION          default: us-east-1

Request (from ALB):
    POST /
    Content-Type: application/json
    { "query": "safe sushi near Wicker Park", "session_id": "abc123" }

Response:
    200 OK
    { "result": "1. Mirai Sushi ..." }
"""

from __future__ import annotations

import json
import os
import uuid

import boto3

AGENT_ARN = os.environ["AGENT_RUNTIME_ARN"]
REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-west-2"))

# Re-use the client across warm invocations.
_client = boto3.client("bedrock-agentcore", region_name=REGION)


def handler(event: dict, _ctx) -> dict:
    # Handle CORS preflight before anything else.
    if event.get("httpMethod") == "OPTIONS":
        return _response(200, {})

    # ALB wraps the body as a JSON string.
    try:
        body: dict = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _response(400, {"error": "Request body must be valid JSON"})

    query = (body.get("query") or "").strip()
    session_id = (body.get("session_id") or "").strip()

    if not query:
        return _response(400, {"error": "query field is required"})

    if len(query) > 500:
        return _response(400, {"error": "query must be 500 characters or fewer"})

    if len(session_id) < 33:
        # str(uuid4()) is 36 chars (with hyphens); uuid4().hex is only 32 (below min).
        session_id = f"{session_id}-{uuid.uuid4()}" if session_id else str(uuid.uuid4())

    payload = json.dumps({"query": query}).encode("utf-8")

    try:
        resp = _client.invoke_agent_runtime(
            agentRuntimeArn=AGENT_ARN,
            runtimeSessionId=session_id,
            payload=payload,
            qualifier="DEFAULT",
        )
    except _client.exceptions.ResourceNotFoundException:
        return _response(503, {"error": "Agent runtime not found. Check AGENT_RUNTIME_ARN."})
    except Exception as exc:
        return _response(502, {"error": f"AgentCore invocation failed: {exc}"})

    # Collect streaming response chunks.
    chunks: list[str] = []
    for chunk in resp.get("response", []):
        chunks.append(chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk)

    raw = "".join(chunks)
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # AgentCore emits an SSE stream: each line is `data: "<json_string>"`.
        # Parse it into a single clean text string for the browser.
        result = {"result": _parse_sse(raw)}

    return _response(200, result)


def _parse_sse(raw: str) -> str:
    """Extract and concatenate text payloads from an SSE data stream."""
    parts: list[str] = []
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        try:
            parts.append(json.loads(payload))
        except json.JSONDecodeError:
            parts.append(payload)
    return "".join(parts)


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": os.environ.get(
                "ALLOWED_ORIGIN", "*"
            ),
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
        },
        "body": json.dumps(body),
    }
