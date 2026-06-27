# 0003 — Phase 2: hosted experiment tracking and feature versioning

- **Status**: Proposed (deferred to Phase 2 — not adopted this iteration)
- **Date**: 2026-06-14
- **Owners to weigh in**: Bella, Deepak, Jun (modeling); Arun (data)

> Note: this record was drafted by Claude (Claude Code) at Bella's request,
> as a suggested plan. It is **Proposed**, not Accepted — it captures the
> reasoning while it's fresh so Phase 2 doesn't restart the discussion. Flip
> it to Accepted (or supersede it) when Phase 2 actually begins.

## Context

Decision record 0001 set the current scheme: a flat, git-tracked JSON ledger
(`reports/metrics/*.json`) plus content-hash data versioning (`features_sha256`
+ `feature_set_version`), with **no MLflow or AWS this iteration**. 0001 §6 says
to adopt MLflow only "if run volume outgrows the flat JSON ledger," and that
hosted tracking (SageMaker / S3) is Phase 2.

This record answers the natural follow-up: *when* Phase 2 arrives (hosted
training/scoring on AWS — see CLAUDE.md Roadmap), what should experiment
tracking and feature versioning look like, and is MLflow the right tool?

## Decision (proposed)

1. **Don't adopt MLflow on schedule — adopt it on a trigger.** The flat JSON
   ledger is simpler, free, diffable in PRs, and fully reproducible at our
   current scale (low run volume, local training). MLflow earns its cost only
   when one of these is true:
   - many runs / hyperparameter sweeps to compare in a UI,
   - a team needing one shared run history,
   - a model registry / stage-promotion workflow,
   - artifact lineage across many models.
   "AWS now exists" is **not** a trigger. Keep the ledger until a trigger hits.

2. **When the trigger hits, use Amazon SageMaker managed MLflow.** AWS hosts the
   tracking server; we log with the standard `mlflow` API, artifacts (models,
   plots, the features parquet) land in S3, and it integrates with SageMaker
   training jobs and the MLflow model registry. Self-hosting MLflow
   (ECS/Fargate + RDS Postgres + S3) is the fallback only if managed MLflow is
   unavailable — it adds operational overhead for no benefit at our scale.

3. **Feature versioning: keep the content hash; add durable storage in stages.**
   - **Keep** `features_sha256` + `feature_set_version` — they survive any
     rebase/merge and already pin data + feature-contract identity.
   - **Phase 2 (light):** store `features.parquet` in S3 with bucket
     **versioning on**, and record the S3 object version id next to the hash.
     Same model, durable storage, no new tooling.
   - **Only if daily-rolling online features land:** evaluate **SageMaker
     Feature Store** for point-in-time-correct reads (relevant to our leakage
     guards) and online serving. It's a meaningful commitment — overkill unless
     we actually need online features, so it stays deferred until then.

## Consequences

- No code, infra, dependencies, or seams added now (consistent with CLAUDE.md
  scope — AWS is Phase 2). This is a plan, not an implementation.
- The reproducibility guarantees from 0001 are preserved either way: the hash
  is the permanent data anchor whether or not MLflow is in the picture.
- A clear, written trigger means Phase 2 starts from "do we meet the trigger?"
  rather than re-litigating MLflow-vs-ledger from scratch.
- If this plan goes stale before Phase 2, it's `Proposed` — cheap to revise or
  discard.

## References

- Decision record `0001` (experiment tracking; ledger + hash versioning),
  CLAUDE.md § "Experiment tracking" and § "Roadmap (acknowledged, not now)"
