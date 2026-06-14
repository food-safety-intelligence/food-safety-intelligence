# 0001 — Experiment tracking and served-model reconcile

- **Status**: Accepted
- **Date**: 2026-06-14
- **Owners to ack**: Bella, Deepak, Jun (modeling); Arun, Aurelia (consumers)

## Context

Two problems made model results hard to trust and compare:

1. **Eval ≠ served.** Notebooks 04/05 trained **isotonic**-calibrated models,
   evaluated on the **full** chronological split, and wrote thin metrics. The
   model actually serving the web app (`scripts/retrain_baseline_sigmoid.py`)
   used **sigmoid** calibration on a **right-truncation-filtered** split and
   wrote `scores.json` but **no tracked metrics**. So the committed numbers
   described a model that wasn't deployed.
2. **No provenance.** Metrics/metadata recorded only `features_parquet_mtime`
   (which changes on every rebuild), so you couldn't tell which code or data
   produced a number, and same-day reruns collided on date-only filenames.

We want reproducible, comparable experiment tracking for upcoming feature and
model work — **without AWS or MLflow this iteration** (see CLAUDE.md scope).

## Decision

1. **Version data by hash, not by committing it.** `data/` stays gitignored.
   Each run records `features_sha256` (content hash of `features.parquet`) and a
   `feature_set_version` (hash of the ordered feature contract) — never mtime.
2. **`reports/metrics/*.json` is the git-tracked, diffable experiment ledger.**
   Every run — notebooks 04/05 and the served script — stamps the same Tier-0
   block via `src/foodsafety/tracking.provenance()`: `git_commit`, `git_dirty`,
   `features_sha256`, `feature_set_version`, and `run_id` (`<date>_<short-sha>`),
   plus the shared `models.evaluate.evaluate()` metric schema (incl.
   `top_decile_lift`).
3. **Commit code before a tracked run; one experiment per commit boundary.**
   The `run_id` ties to the commit so reruns don't overwrite each other. Commit
   the metrics JSON after reviewing it. Never commit `data/` artifacts.
4. **Run experiments via the script / existing notebooks that use the shared
   helper** — don't add a new notebook per experiment.
5. **Served model = baseline logistic regression, sigmoid (Platt) calibration,
   evaluated on the right-truncation-filtered split**, and it now writes its
   metrics to the ledger (reconciling eval ≠ served). Sigmoid was chosen
   because isotonic produced only ~60 distinct probabilities across ~23k
   restaurants (UI ties); sigmoid gives continuous, strictly-ordered scores.
   Note: sigmoid vs isotonic preserves ranking, so PR-AUC / precision are
   unchanged by the calibration choice — only the right-truncation filter
   changes those numbers.
6. **No MLflow or AWS this iteration.** Adopt MLflow (local file backend) only
   if run volume outgrows the flat JSON ledger; hosted tracking (SageMaker
   Experiments / S3) is Phase 2.

## Consequences

- Each metric record is reproducible (code + data identity) and comparable
  across baseline / xgb / served runs; the deployed model's performance is now
  tracked. No new infra or dependencies.
- `git_dirty` is often `true` during notebook `--inplace` runs because the
  notebook gains output cells — `git_commit` remains the reliable identity.
- The script and notebooks both assemble metadata; duplication is mitigated by
  the shared `tracking.provenance()` helper.
- Right-truncation filtering changes eval numbers vs the old unfiltered ones
  (the recent test slice ~halves); the filtered numbers are the honest ones.
- The flat-file ledger has scaling limits; revisit MLflow if/when needed.

## References

- `src/foodsafety/tracking.py`, `scripts/retrain_baseline_sigmoid.py`
- `docs/interface_contracts.md`, CLAUDE.md § "Experiment tracking"
