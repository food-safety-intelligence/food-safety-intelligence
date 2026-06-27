"""Offline builder: LLM-extract a structured hazard label per violation comment, cache to parquet.

The structured arm of Layer-C NLP. Feeds
``foodsafety.features.violation_labels.add_violation_label_features``. Runs the
permanent batch -> cache pattern: prompt Amazon Nova Lite (Bedrock, forced
tool-use for reliable JSON) over each DISTINCT non-empty comment ONCE, write one
row per distinct comment keyed by content hash (``text_hash``). The web app and
the model never call Bedrock at request time — they read this cache.

The prompt constrains the model to **observed conduct only** — it must never
infer cuisine, ethnicity, ownership, or neighborhood (a fairness guard, audited
at eval). Labels: primary hazard type, severity 1-3, imminent-health-hazard,
corrected-on-site.

Run with the project's Python:
    PYTHONPATH=src uv run python scripts/build_violation_labels.py
    PYTHONPATH=src uv run python scripts/build_violation_labels.py --limit 200   # sample

Resumable: distinct-comment labels are checkpointed to a sidecar parquet keyed
by content hash; re-running skips comments already labelled (a compute restart is
survivable — see the embedding builder's note).
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
import pandas as pd
from botocore.config import Config

from foodsafety.features.violation_labels import (
    HAZARD_VALUES,
    LABEL_COLS,
    violation_text_hash,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FEATURES_PATH = REPO_ROOT / "data" / "processed" / "features.parquet"
INTERIM_DIR = REPO_ROOT / "data" / "interim"
OUT_PATH = INTERIM_DIR / "violation_labels_novalite.parquet"
CKPT_PATH = INTERIM_DIR / "violation_labels_novalite_bytext.parquet"

MODEL_ID = "amazon.nova-lite-v1:0"
MAX_CHARS = 12_000  # the violations field p-max is ~12.7k chars; cap defensively.

SYSTEM = (
    "You label Chicago food-inspection violation comments for a food-safety risk model. "
    "Use ONLY the conduct and conditions described in the comment text. "
    "Never infer or use cuisine, ethnicity, ownership, language, or neighborhood. "
    "If the text is administrative or describes no real hazard, use primary_hazard='other' "
    "and severity=1."
)

TOOL = {
    "toolSpec": {
        "name": "record_violation",
        "description": "Record the single most serious food-safety hazard the inspector OBSERVED.",
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "primary_hazard": {
                        "type": "string",
                        "enum": list(HAZARD_VALUES),
                        "description": "the single most serious hazard type described",
                    },
                    "severity": {
                        "type": "integer",
                        "enum": [1, 2, 3],
                        "description": "1=minor/core, 2=priority, 3=imminent health hazard",
                    },
                    "imminent_health_hazard": {"type": "boolean"},
                    "corrected_on_site": {
                        "type": "boolean",
                        "description": "true ONLY if the text says it was corrected/abated during the visit",
                    },
                },
                "required": [
                    "primary_hazard",
                    "severity",
                    "imminent_health_hazard",
                    "corrected_on_site",
                ],
            }
        },
    }
}
TOOL_CONFIG = {"tools": [TOOL], "toolChoice": {"tool": {"name": "record_violation"}}}


def _label_one(client, text: str) -> dict:
    """One Nova Lite forced-tool call, retried on transient + tool-serialization errors.

    Two distinct failure modes, handled differently:
      * throttling / timeouts -> exponential backoff.
      * ModelErrorException "invalid sequence as part of ToolUse" -> Nova sometimes
        walks itself into a malformed tool call greedily (deterministic at temp 0).
        Retry with an escalating temperature to break out of the bad path.
    ``maxTokens`` is generous (1000) because the failure at 300 was the tool call
    being truncated mid-serialization.
    """
    delay = 0.5
    for attempt in range(6):
        # temp 0 for the first two tries (deterministic, best labels); escalate after
        # to escape a stuck greedy tool-serialization path.
        temperature = 0.0 if attempt < 2 else min(0.3 * attempt, 1.0)
        try:
            r = client.converse(
                modelId=MODEL_ID,
                system=[{"text": SYSTEM}],
                messages=[{"role": "user", "content": [{"text": text[:MAX_CHARS]}]}],
                toolConfig=TOOL_CONFIG,
                inferenceConfig={"temperature": temperature, "maxTokens": 1000},
            )
            for block in r["output"]["message"]["content"]:
                if "toolUse" in block:
                    return block["toolUse"]["input"]
            raise ValueError("no toolUse block in response")
        except Exception as exc:  # noqa: BLE001 — retry transient + tool-serialization, else re-raise
            name = type(exc).__name__
            throttle = "Throttl" in name or "Timeout" in name or "ServiceUnavailable" in name
            tool_glitch = "ModelError" in name  # invalid-tool-sequence; temp escalation may fix
            if attempt == 5 or not (throttle or tool_glitch):
                raise
            if throttle:
                time.sleep(delay)
                delay = min(delay * 2, 16.0)
    raise RuntimeError("unreachable")


def _coerce(label: dict) -> dict:
    """Normalise the model output to the cache schema (defensive against drift)."""
    hz = str(label.get("primary_hazard", "other"))
    if hz not in HAZARD_VALUES:
        hz = "other"
    sev = label.get("severity", 1)
    sev = sev if sev in (1, 2, 3) else 1
    return {
        "llm_hazard": hz,
        "llm_severity": int(sev),
        "llm_imminent_health_hazard": bool(label.get("imminent_health_hazard", False)),
        "llm_corrected_on_site": bool(label.get("corrected_on_site", False)),
    }


def _load_checkpoint() -> dict[str, dict]:
    if not CKPT_PATH.exists():
        return {}
    df = pd.read_parquet(CKPT_PATH)
    return {
        row.text_hash: {c: getattr(row, c) for c in LABEL_COLS}
        for row in df.itertuples(index=False)
    }


def _write_checkpoint(by_hash: dict[str, dict]) -> None:
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    rows = [{"text_hash": h, **lab} for h, lab in by_hash.items()]
    pd.DataFrame(rows).to_parquet(CKPT_PATH, index=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="label only N distinct comments (sample)")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--checkpoint-every", type=int, default=2000)
    args = ap.parse_args()

    df = pd.read_parquet(FEATURES_PATH, columns=["violations"])
    text = df["violations"].astype("string").fillna("").str.strip()
    keyed = pd.DataFrame({"text": text[text.str.len() > 0].to_numpy()})
    keyed["text_hash"] = violation_text_hash(keyed["text"])
    distinct = keyed.drop_duplicates("text_hash").reset_index(drop=True)
    print(f"rows with text: {len(keyed):,}  distinct comments: {len(distinct):,}")

    by_hash = _load_checkpoint()
    todo = distinct[~distinct["text_hash"].isin(by_hash)]
    if args.limit:
        todo = todo.head(args.limit)
    print(f"already cached: {len(by_hash):,}  to label now: {len(todo):,}")

    if len(todo):
        cfg = Config(retries={"max_attempts": 0}, read_timeout=40, connect_timeout=10)
        client = boto3.client("bedrock-runtime", config=cfg)
        done, failed, t0 = 0, 0, time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {
                pool.submit(_label_one, client, row.text): row.text_hash
                for row in todo.itertuples(index=False)
            }
            for fut in as_completed(futs):
                try:
                    by_hash[futs[fut]] = _coerce(fut.result())
                except Exception as exc:  # noqa: BLE001 — skip a straggler, don't kill the batch
                    failed += 1
                    if failed <= 10:
                        print(f"  skip (label failed): {type(exc).__name__}", flush=True)
                done += 1
                if done % args.checkpoint_every == 0:
                    _write_checkpoint(by_hash)
                    print(
                        f"  labelled {done:,}/{len(todo):,}  ({done / (time.time() - t0):.0f}/s)",
                        flush=True,
                    )
        _write_checkpoint(by_hash)
        print(
            f"labelled {done - failed:,} new in {time.time() - t0:.0f}s ({failed} failed/skipped)"
        )

    # Write the cache keyed by text_hash — one row per distinct comment present.
    present = distinct["text_hash"]
    present = present[present.isin(by_hash)].reset_index(drop=True)
    if len(present) < len(distinct):
        print(
            f"WARNING: {len(distinct) - len(present):,} comments unlabelled (sample/partial) — omitted"
        )
    out = pd.DataFrame([{"text_hash": h, **by_hash[h]} for h in present])
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)
    print(f"wrote {OUT_PATH}  ({len(out):,} comments)")


if __name__ == "__main__":
    sys.exit(main())
