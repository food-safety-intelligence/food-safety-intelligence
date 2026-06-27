"""Offline builder: embed each inspection's violation free-text once, cache to parquet.

This is the dense-NLP (Layer-C) batch pass that feeds
``foodsafety.features.text_features.add_text_embedding_features``. It runs the
permanent batch -> cache pattern: embed every distinct non-empty violations
comment ONCE with Amazon Titan Text Embeddings V2 (Bedrock), then write one row
per **distinct comment**, keyed by a content hash (``text_hash``). The web app
and the model never call Bedrock at request time — they read this cache.

Why key by text content (not the inspection): identical comment text recurs
across inspections, and the inspection key ``(license_id, as_of_date)`` is NOT
unique (a licence can have two inspections on one day with different text).
Hashing the text dedupes the ~90k distinct comments natively; the modelling-time
join in ``text_features`` hashes each row's own text and looks it up here.

Leak-free: each cached row is the embedding of one comment's OWN text (observed
at as_of_date). No aggregation across rows happens here.

Run with the project's Python:
    PYTHONPATH=src uv run python scripts/build_text_embeddings.py
    PYTHONPATH=src uv run python scripts/build_text_embeddings.py --limit 50   # smoke test

Resumable: distinct-text embeddings are checkpointed to a sidecar parquet keyed
by a content hash; re-running skips text already embedded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
import pandas as pd
from botocore.config import Config

REPO_ROOT = Path(__file__).resolve().parent.parent
FEATURES_PATH = REPO_ROOT / "data" / "processed" / "features.parquet"
INTERIM_DIR = REPO_ROOT / "data" / "interim"
OUT_PATH = INTERIM_DIR / "text_embeddings_titanv2.parquet"
# Sidecar keyed by text-hash so a re-run resumes without re-embedding.
CKPT_PATH = INTERIM_DIR / "text_embeddings_titanv2_bytext.parquet"

MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBED_DIM = 256  # Titan v2 native output dim (256 / 512 / 1024); 256 keeps the cache lean.
MAX_CHARS = 20_000  # defensive cap; Titan v2's 8k-token limit is well above our p-max (~3k tokens).
EMBED_PREFIX = "txt_emb_"


def _text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _embed_one(client, text: str) -> list[float]:
    """One Titan v2 embedding call with exponential backoff on throttling."""
    body = json.dumps({"inputText": text[:MAX_CHARS], "dimensions": EMBED_DIM, "normalize": True})
    delay = 0.5
    for attempt in range(8):
        try:
            resp = client.invoke_model(modelId=MODEL_ID, body=body)
            return json.loads(resp["body"].read())["embedding"]
        except Exception as exc:  # noqa: BLE001 — retry any transient Bedrock error, re-raise if persistent
            name = type(exc).__name__
            transient = "Throttl" in name or "Timeout" in name or "ServiceUnavailable" in name
            if not transient or attempt == 7:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 16.0)
    raise RuntimeError("unreachable")


def _load_checkpoint() -> dict[str, list[float]]:
    if not CKPT_PATH.exists():
        return {}
    df = pd.read_parquet(CKPT_PATH)
    cols = sorted(c for c in df.columns if c.startswith(EMBED_PREFIX))
    return {row.text_hash: [getattr(row, c) for c in cols] for row in df.itertuples(index=False)}


def _write_checkpoint(by_hash: dict[str, list[float]]) -> None:
    cols = [f"{EMBED_PREFIX}{i:03d}" for i in range(EMBED_DIM)]
    rows = [{"text_hash": h, **dict(zip(cols, vec, strict=True))} for h, vec in by_hash.items()]
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(CKPT_PATH, index=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=0, help="embed only N distinct texts (smoke test)")
    ap.add_argument("--workers", type=int, default=16, help="concurrent Bedrock calls")
    ap.add_argument("--checkpoint-every", type=int, default=2000)
    args = ap.parse_args()

    df = pd.read_parquet(FEATURES_PATH, columns=["license_id", "as_of_date", "violations"])
    df["license_id"] = df["license_id"].astype("string")
    df["as_of_date"] = pd.to_datetime(df["as_of_date"])
    text = df["violations"].astype("string").fillna("").str.strip()
    has_text = text.str.len() > 0
    keyed = df.loc[has_text, ["license_id", "as_of_date"]].copy()
    keyed["text"] = text[has_text].to_numpy()
    keyed["text_hash"] = keyed["text"].map(_text_hash)
    print(f"rows with text: {len(keyed):,}  distinct texts: {keyed['text_hash'].nunique():,}")

    distinct = keyed.drop_duplicates("text_hash")[["text_hash", "text"]].reset_index(drop=True)
    by_hash = _load_checkpoint()
    todo = distinct[~distinct["text_hash"].isin(by_hash)]
    if args.limit:
        todo = todo.head(args.limit)
    print(f"already cached: {len(by_hash):,}  to embed now: {len(todo):,}")

    if len(todo):
        cfg = Config(retries={"max_attempts": 0}, read_timeout=30, connect_timeout=10)
        client = boto3.client("bedrock-runtime", config=cfg)
        done, failed, t0 = 0, 0, time.time()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {
                pool.submit(_embed_one, client, row.text): row.text_hash
                for row in todo.itertuples(index=False)
            }
            for fut in as_completed(futs):
                # One text that exhausts its retries must not kill the whole job —
                # it's checkpointed-resumable, but a crash wastes the in-flight work.
                # Skip the straggler; it falls through to has_violation_text=0.
                try:
                    by_hash[futs[fut]] = fut.result()
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    if failed <= 10:
                        print(f"  skip (embed failed): {type(exc).__name__}", flush=True)
                done += 1
                if done % args.checkpoint_every == 0:
                    _write_checkpoint(by_hash)
                    rate = done / (time.time() - t0)
                    print(f"  embedded {done:,}/{len(todo):,}  ({rate:.0f}/s)", flush=True)
        _write_checkpoint(by_hash)
        print(
            f"embedded {done - failed:,} new texts in {time.time() - t0:.0f}s ({failed} failed/skipped)"
        )

    # Write the cache keyed by text_hash — one row per DISTINCT comment present in
    # the data. The modelling-time join in text_features hashes each row's own
    # violations text and looks it up here (the inspection key (license_id,
    # as_of_date) is NOT unique, so the embedding is keyed by content instead).
    cols = [f"{EMBED_PREFIX}{i:03d}" for i in range(EMBED_DIM)]
    present = keyed["text_hash"].drop_duplicates()
    present = present[present.isin(by_hash)].reset_index(drop=True)
    if len(present) < keyed["text_hash"].nunique():
        missing = keyed["text_hash"].nunique() - len(present)
        print(f"WARNING: {missing:,} distinct texts not yet embedded (smoke/partial run) — omitted")
    emb_block = pd.DataFrame([by_hash[h] for h in present], columns=cols)
    out = pd.concat([present.rename("text_hash"), emb_block], axis=1)
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT_PATH, index=False)
    print(f"wrote {OUT_PATH}  ({len(out):,} rows x {EMBED_DIM} dims)")


if __name__ == "__main__":
    sys.exit(main())
