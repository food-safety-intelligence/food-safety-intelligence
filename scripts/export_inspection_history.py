"""Export per-restaurant inspection history to JSON for the web app.

The web app's restaurant detail page renders a timeline of past inspections.
That data lives in `data/processed/inspections_labeled.parquet` (~225k rows)
and was never plumbed through to `scores.json` — the original export script
skipped it to keep the main payload small.

This script writes a sidecar file `app/public/data/inspection_history.json`
keyed by `license_id` so the web app can read it server-side at request time.

Run with the project's Python (anaconda or uv):
    /Users/jun/anaconda3/bin/python scripts/export_inspection_history.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
INSPECTIONS_PATH = REPO_ROOT / "data" / "processed" / "inspections_labeled.parquet"
OUT_PATH = REPO_ROOT / "app" / "public" / "data" / "inspection_history.json"

# Distribution of events per restaurant: p99 = 30, max = 799. Capping at the
# 30 most-recent inspections covers 99.6% of all events while bounding the
# JSON payload (with no cap the full export is ~54MB).
MAX_EVENTS_PER_LICENSE = 30
HEADLINE_MAX_CHARS = 100


def main() -> None:
    print(f"reading {INSPECTIONS_PATH}")
    df = pd.read_parquet(INSPECTIONS_PATH)

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

    # Headline = first violation line, truncated. Keeps the row dense without
    # shipping the full multi-kilobyte violations text.
    def _headline(v: object) -> str:
        if pd.isna(v):
            return ""
        s = str(v).split("|")[0].strip()
        return s[:HEADLINE_MAX_CHARS] + ("…" if len(s) > HEADLINE_MAX_CHARS else "")

    df["headline"] = df["violations"].apply(_headline) if "violations" in df.columns else ""

    # Group into {license_id: [events]}, capped to most-recent N per license.
    history: dict[str, list[dict]] = {}
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
    print(
        f"  truncated to {MAX_EVENTS_PER_LICENSE} most-recent events for "
        f"{truncated_licenses:,} restaurants (rest are full history)"
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"writing {OUT_PATH}: {len(history):,} restaurants, "
        f"{sum(len(v) for v in history.values()):,} inspection events"
    )
    with open(OUT_PATH, "w") as f:
        json.dump(history, f, separators=(",", ":"))

    size_mb = OUT_PATH.stat().st_size / 1024 / 1024
    print(f"  {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
