"""Export per-restaurant inspection history to JSON for the web app.

The web app's restaurant detail page renders a timeline of past inspections.
That data lives in `data/processed/inspections_labeled.parquet` (~225k rows)
and was never plumbed through to `scores.json` — the original export script
skipped it to keep the main payload small.

This script writes a sidecar file `app/public/data/inspection_history.json`
keyed by `license_id` so the web app can read it server-side at request time.

It ALSO writes the full violation-comment text, sharded into
`app/public/data/comments/<xx>.json` (xx = first two md5 hex chars of the
license_id). The detail-page timeline shows only a 100-char `headline` inline;
clicking a row expands to the full comments, which live in these shards. The
full text can't ride in `inspection_history.json` — across all establishments
it's ~277MB, over GitHub's 100MB file limit and too large to hold in one blob.
Sharding keeps each file ~1MB so the static build only reads the handful of
shards covering its pre-generated pages, and the comments dir is gitignored
(S3 is the source of truth at build time). The shard's per-license array is
index-aligned to that license's `inspection_history` events — both are built
in the same pass below from the same sorted frame, so event[i] ↔ comments[i].

Run with the project's Python (anaconda or uv):
    /Users/jun/anaconda3/bin/python scripts/export_inspection_history.py
"""

from __future__ import annotations

import hashlib
import json

import pandas as pd

from foodsafety.config import PROCESSED_DIR, WEB_APP_DATA_DIR
from foodsafety.io import storage

INSPECTIONS_PATH = storage.join(str(PROCESSED_DIR), "inspections_labeled.parquet")
OUT_PATH = storage.join(str(WEB_APP_DATA_DIR), "inspection_history.json")
# Full-comment shards live alongside the history JSON under web-app-data/comments/
# (local or S3, same base as OUT_PATH). Gitignored; S3 is the source of truth.
COMMENTS_DIR = storage.join(str(WEB_APP_DATA_DIR), "comments")

# Distribution of events per restaurant: p99 = 30, max = 799. Capping at the
# 30 most-recent inspections covers 99.6% of all events while bounding the
# JSON payload (with no cap the full export is ~54MB).
MAX_EVENTS_PER_LICENSE = 30
HEADLINE_MAX_CHARS = 100


def _shard_of(license_id: str) -> str:
    # md5 first two hex chars → 256 even buckets. Must match the web app's
    # shard() in scores-server.ts so it reads the right file at build time.
    return hashlib.md5(license_id.encode()).hexdigest()[:2]


def _comments(v: object) -> str:
    # Full violation text for one inspection: the pipe-delimited entries
    # rejoined as newlines so the UI can list each violation on its own line.
    # Each entry is "<code>. <NAME> - Comments: <free text>".
    if pd.isna(v):
        return ""
    return "\n".join(p.strip() for p in str(v).split("|") if p.strip())


def main() -> None:
    print(f"reading {INSPECTIONS_PATH}")
    df = storage.read_parquet(INSPECTIONS_PATH)

    # The web app's InspectionEvent type wants {date, type, result, headline}.
    # Map columns; the inspections table uses `inspection_date`, `inspection_type`,
    # `results`, `violations` (long text).
    needed = {
        "license_id": "license_id",
        "inspection_date": "date",
        "inspection_type": "type",
        "results": "result",
        "violations": "violations",
    }
    df = df[[c for c in needed if c in df.columns]].rename(columns=needed)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df["license_id"] = df["license_id"].astype(str)
    df = df.sort_values(["license_id", "date"], ascending=[True, False])

    # Headline = first violation's NAME, truncated. The "- Comments:" inspector
    # note is dropped — it stays hidden in the collapsed timeline row and only
    # appears (in full) when the row is expanded, from the comment shards.
    def _headline(v: object) -> str:
        if pd.isna(v):
            return ""
        s = str(v).split("|")[0].split(" - Comments:")[0].strip()
        return s[:HEADLINE_MAX_CHARS] + ("…" if len(s) > HEADLINE_MAX_CHARS else "")

    df["headline"] = df["violations"].apply(_headline) if "violations" in df.columns else ""

    df["comments"] = df["violations"].apply(_comments) if "violations" in df.columns else ""

    # Group into {license_id: [events]}, capped to most-recent N per license.
    # In the same pass, accumulate the per-license comment arrays into shards.
    # `comments[i]` lines up with `events[i]` because both come from `group`,
    # which is the same sorted/capped slice.
    history: dict[str, list[dict]] = {}
    shards: dict[str, dict[str, list[str]]] = {}
    truncated_licenses = 0
    for license_id, group in df.groupby("license_id", sort=False):
        if len(group) > MAX_EVENTS_PER_LICENSE:
            truncated_licenses += 1
            group = group.head(MAX_EVENTS_PER_LICENSE)  # df is pre-sorted desc by date
        events = [
            {
                "date": row["date"],
                "type": "" if pd.isna(row.get("type")) else str(row["type"]),
                "result": "" if pd.isna(row.get("result")) else str(row["result"]),
                "headline": row["headline"],
            }
            for _, row in group.iterrows()
        ]
        history[license_id] = events
        shards.setdefault(_shard_of(license_id), {})[license_id] = list(group["comments"])
    print(
        f"  truncated to {MAX_EVENTS_PER_LICENSE} most-recent events for "
        f"{truncated_licenses:,} restaurants (rest are full history)"
    )

    print(
        f"writing {OUT_PATH}: {len(history):,} restaurants, "
        f"{sum(len(v) for v in history.values()):,} inspection events"
    )
    # OUT_PATH may be local or s3:// — route through storage (creates local parents).
    storage.write_text(json.dumps(history, separators=(",", ":")), OUT_PATH)

    # Comment shards under web-app-data/comments/ (local or S3, via storage).
    # Gitignored; the static build reads only the shards covering its pages.
    total_bytes = 0
    for shard, by_license in shards.items():
        payload = json.dumps(by_license, separators=(",", ":"))
        storage.write_text(payload, storage.join(COMMENTS_DIR, f"{shard}.json"))
        total_bytes += len(payload.encode())
    print(
        f"writing {COMMENTS_DIR}/<xx>.json: {len(shards)} shards, "
        f"{total_bytes / 1024 / 1024:.1f} MB total"
    )


if __name__ == "__main__":
    main()
