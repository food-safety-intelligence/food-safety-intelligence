# Design: Weekly idempotent raw-data ingestion → S3

- **Date:** 2026-06-28
- **Owner:** Jun (PM) — implementation likely Arun (DE workstream)
- **Status:** Approved design, pre-implementation
- **Scope tag:** Phase-2 roadmap item "Periodic incremental ingestion" (see `CLAUDE.md` Roadmap)

---

## Problem

The pipeline needs fresh Chicago data without manual re-pulls. Today the raw
fetches for inspections / 311 / licenses live in notebook cells (only
building-violations is scripted), and there is no schedule. The end-state Jun is
targeting:

> weekly new data lands in S3 → a SageMaker notebook reads the latest, retrains,
> and publishes a new `scores.json` to S3 → the app reads that JSON.

This design covers **only the first hop**: a scheduled weekly job that
incrementally fetches the SODA datasets and lands deduplicated raw parquet in S3,
idempotently. The retrain + publish step stays manual/notebook-driven for now,
preserving the human-in-the-loop promotion gate.

## Goals

- Weekly automated pull of the five Chicago SODA datasets into S3.
- **Idempotent:** no full-history re-download, no duplicate rows, safe to re-run.
- Catch edits to already-ingested records (Chicago data is mutable).
- "Latest" is trivial for the SageMaker notebook to read (stable S3 key).
- Reproducible infra (defined as code), near-zero cost, AWS-native.

## Non-goals (explicitly out, this iteration)

- Retrain automation / `scores.json` publish — stays manual SageMaker for now.
- A DAG orchestrator (Airflow/MWAA, Step Functions, SageMaker Pipeline). One
  weekly task does not need one; revisit when the full
  `fetch → features → train → gate → publish` flow is automated.
- dbt — wrong tool (SQL transform on a warehouse; no warehouse here, no API
  extract).
- Any change to the model, features, label, or the temporal-split discipline.

## Decisions (locked during brainstorming)

| Decision | Choice | Why |
|---|---|---|
| Orchestration tier | Serverless AWS (not Airflow) | ~$0–$1/mo vs ~$70–360/mo always-on MWAA for 52 runs/yr; IAM-native; sits next to S3/SageMaker |
| Compute | **ECS Fargate task** | No 15-min Lambda cap; same image runs locally; pennies/run |
| Trigger | **EventBridge Scheduler**, weekly cron | ~$0; cron expression checked into IaC |
| Edit handling | **Lookback window** (~60–90d re-pull + past watermark, upsert) | Catches almost all late edits with simple SoQL |
| S3 layout | **Canonical single object** `raw/<dataset>.parquet`, atomically overwritten | "Latest" is always the same key; trivial notebook read; fine at single-digit-MB sizes |
| Incremental cursor | watermark = `max(cursor_col)` of existing S3 file | No separate state store to corrupt |
| Dedupe | upsert on per-dataset natural key | Removes boundary re-fetches and re-pulled edits |

## Architecture / data flow

```
EventBridge Scheduler (cron: weekly, e.g. Mon 06:00 America/Chicago)
        │  triggers
        ▼
ECS Fargate task  ── runs ──▶  python scripts/fetch_all.py
        │                          │  for each dataset (sequential):
        │                          │   1. read watermark = max(cursor_col) of existing S3 file
        │                          │   2. fetch_soda_keyset(cursor_start = watermark − lookback)
        │                          │   3. merge + upsert-on-PK into existing rows
        │                          │   4. atomic write: temp key → copy → canonical key
        ▼                          ▼
   CloudWatch Logs        s3://food-safety-intelligence-data/raw/<dataset>.parquet
                                   │
                                   ▼  (later, unchanged, manual)
                          SageMaker notebook reads latest → retrain → scores.json → S3 → app
```

One Fargate task runs all five fetches sequentially — they are independent and
small, so no parallelism or DAG is warranted.

## Datasets and keys

| Dataset | SODA id | Cursor column | Upsert key |
|---|---|---|---|
| Food Inspections | `4ijn-s7e5` | `inspection_date` | `inspection_id` |
| 311 Service Requests | `v6vf-nfxy` | `created_date` | `sr_number` |
| Business Licenses (current) | `uupf-x98q` | license issue/term date | `id` |
| Business Licenses (historical) | `vgg9-bn8p` | license issue/term date | `id` |
| Building Violations | `22u3-xenr` | `violation_date` | `id` |

> Exact PK/cursor column names per dataset must be confirmed against the live
> Socrata schema during implementation. `license_id` alone is **not** unique
> across renewals — use the row `id`. 311 keeps only `RELEVANT_SR_TYPES`
> (`config.RELEVANT_SR_TYPES`) as `where_extra`.

## Components

### Fetch scripts (the real work)
Lift the inspections / 311 / licenses pulls out of notebooks into
`scripts/fetch_inspections.py`, `scripts/fetch_311.py`, `scripts/fetch_licenses.py`,
mirroring the existing `scripts/fetch_building_violations.py`. Each:
- keeps its **primary-key column** (needed for upsert — the current
  building-violations script drops it to save space; that script gains the PK
  column too),
- keeps its **cursor column**,
- uses `fetch_soda_keyset` with `cursor_start = watermark − lookback`.

A thin `scripts/fetch_all.py` runs them in sequence; a new `make ingest` target
wraps it.

### S3 I/O seam — `foodsafety/io/store.py`
`read_dataset(name) -> DataFrame` and `write_dataset(name, df)` that resolve to:
- **local `data/raw/`** when `FOODSAFETY_DATA_DIR` is a filesystem path (laptop /
  dry-run), and
- **S3** when `FOODSAFETY_DATA_DIR` is an `s3://…` URI (Fargate), via
  `s3fs` + `pyarrow`.

This reuses the **existing** `FOODSAFETY_DATA_DIR` seam (the one env var
`CLAUDE.md` always sanctioned for the AWS future) — scripts stay runnable
unchanged on the laptop; the Fargate task just sets
`FOODSAFETY_DATA_DIR=s3://food-safety-intelligence-data/raw`.

New Python deps (now in scope per the Phase-2 note): `s3fs`, `boto3`.

### Idempotency helpers (inside `store.py` / a fetch helper)
- **watermark:** `max(cursor_col)` of the existing dataset. Empty/missing file →
  full first pull from that dataset's existing start date (e.g. 2010 for
  inspections + building data), exactly as the notebooks/`fetch_building_violations.py`
  do today. This is the raw-pull horizon and is independent of the downstream
  2019 training cutoff, which is applied later in feature-building — unchanged.
- **lookback:** subtract N days (config, default ~90) from the watermark before
  pulling, so edits to recent rows are re-fetched.
- **upsert:** `pd.concat([existing, new]).drop_duplicates(subset=[pk], keep="last")`
  with `new` last so the freshest copy wins.
- **atomic write:** write to `raw/_tmp/<dataset>.<runid>.parquet`, then S3
  copy → `raw/<dataset>.parquet`, then delete temp. A failed run never leaves the
  canonical key half-written; re-running re-derives the same watermark.

## Infrastructure (IaC — CDK app, alongside existing `agentcore-deploy/`)

- **EventBridge Scheduler** rule, weekly cron, target = run-task on the Fargate
  task definition.
- **ECS Fargate** task, 0.5 vCPU / 1 GB, default VPC, image in **ECR** (slim
  Python 3.11 + the `foodsafety` package + `s3fs`).
- **IAM task role** scoped to `s3:GetObject/PutObject/ListBucket` on
  `food-safety-intelligence-data/raw/*` **only** (narrower than the existing
  deploy role). Creds never leave AWS.
- **CloudWatch Logs** for the task; a basic failure alarm/notification is a
  nice-to-have, not required for v1.

## Testing

- Unit tests (fixtures, no network), mirroring `tests/` style:
  - watermark extraction from a sample parquet,
  - upsert-on-PK: feed overlapping batches → assert one row per key, newest wins,
  - atomic-write path: temp key written then promoted; partial temp never
    becomes canonical.
- **Local dry-run mode:** `fetch_all.py` with `FOODSAFETY_DATA_DIR=./data/raw`
  runs the full flow on the laptop before it ever touches Fargate.

## Prerequisites (same regardless of compute choice)

1. Script-ify the three notebook-bound fetches.
2. Add the PK column to all fetch outputs (incl. building violations).
3. Add `s3fs` / `boto3` to `pyproject.toml`.

## Rollout

1. Land fetch scripts + `store.py` + tests; verify `make ingest` locally writing
   to `data/raw/`.
2. Backfill the canonical S3 objects once (manual run with `FOODSAFETY_DATA_DIR`
   pointed at S3) so subsequent runs are incremental.
3. Build/push the ECR image; deploy the CDK stack (Fargate task + EventBridge
   rule + IAM).
4. Trigger one manual Fargate run; confirm idempotency (run twice → row counts
   stable, no dupes).
5. Let the weekly schedule take over. SageMaker retrain stays manual.

## Open / deferred

- Failure alerting (SNS/email) — add after v1 if runs prove flaky.
- Automating the retrain + publish step (would justify a real DAG — Step
  Functions or SageMaker Pipeline, **not** MWAA) — separate future design.
- `:updated_at` cursor instead of lookback window — only if lookback proves to
  miss edits in practice.

## References

- `src/foodsafety/io/soda.py` — `fetch_soda_keyset` (watermark/keyset paging, shard resume)
- `scripts/fetch_building_violations.py` — template for the new fetch scripts
- `src/foodsafety/config.py` — `DATASETS`, `RELEVANT_SR_TYPES`, `FOODSAFETY_DATA_DIR`
- `CLAUDE.md` — Phase-2 status note (AWS in scope) + Roadmap (periodic ingestion)
- `scripts/deploy_aws.sh` — existing AWS account/region/bucket conventions
