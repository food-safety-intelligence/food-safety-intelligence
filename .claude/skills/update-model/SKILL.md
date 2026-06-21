---
name: update-model
description: Land a feature or model change end-to-end across the food-safety-intelligence repo — feature code + ALL_FEATURES + driver labels, leak-free test, parquet rebuild, train + evaluate both models, ethics/fairness check, and (if kept) the docs + served app artifacts. Use when the user says "update the model", "add a feature to the model", "ship this feature", "/update-model", or wires a new feature into training. Mirrors the Run 1 (current-inspection outcome) flow.
---

# update-model

End-to-end playbook for adding or changing a **model feature** in the
`food-safety-intelligence` repo, touching every place that must stay in sync:
Python feature code, the feature contract, tests, the rebuilt parquet, both
trained models, the per-feature driver labels, the ethics/fairness record, and
the served app JSON. The point is that none of these drift apart — a feature in
`ALL_FEATURES` that isn't in the parquet crashes training; one with no
`FEATURE_LABELS` entry ships a raw `snake_case` column name as its UI
"explanation" the moment it ranks in a restaurant's top drivers; a kept feature
whose `scores.json` wasn't re-shipped leaves the demo on the old model.

This encodes the convention from `CLAUDE.md` + `docs/decisions/0001-0005`. Read
the relevant notebook headers and `docs/interface_contracts.md` first (per the
repo "before changing an area" rule).

## Environment
- Use the repo venv directly: `.venv/bin/python`, `.venv/bin/jupyter` (base conda
  lacks `shap`/`xgboost`). `foodsafety` is editable-installed there.
- Use `npm` (not `pnpm`) in `app/`.
- Run notebooks in place so outputs are saved for review:
  `.venv/bin/jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=1800 <nb>`
  (nbstripout strips them again on commit).

## Step 1 — Feature code
- Add/modify the feature in the right module under `src/foodsafety/features/`
  (`inspection_features.py` for per-license history, `complaint_features.py` for
  311, `keyword_flags.py`, `temporal_features.py`, `license_*`). New module → wire
  it into `src/foodsafety/features/build.py` (`build_features`).
- **Leak guard is mandatory and must be commented with WHY** (`CLAUDE.md` code
  style). Two leak-free patterns already in `inspection_features.py`: exclusive
  cumsum (`group[x].cumsum() - x`) and ffill-then-shift. Current-inspection-own
  features (observed at `as_of_date`, label window strictly after) are leak-free
  *without* a shift — say so explicitly.
- Register it for the models: add the column(s) to `NUMERIC_FEATURES` /
  `CATEGORICAL_FEATURES` / `BOOLEAN_FEATURES` in `src/foodsafety/models/baseline.py`
  (→ `ALL_FEATURES`, the single source of truth consumed by **both** LogReg and
  XGBoost). Add a short WHY comment.
- **Add an entry to the `FEATURES` registry** in
  `src/foodsafety/explain/feature_labels.py` for any feature that can surface as a
  top driver — without it the served `scores.json` (and the UI driver list) shows
  the raw column name. Each entry is a `FeaturePresentation(name, label)`:
  - `name` — a generic, value-free label for the **global feature-impact chart**
    on the methodology page (no `{value}`);
  - `label` — the **per-row driver label**: a `{value}` format string
    (`{value:.0f}` for counts), or — for a **binary outcome that surfaces in both
    directions** (e.g. `was_fail`: a fail pushes risk up, a pass pulls it down) —
    a `{True/False}` dict so it reads correctly both ways, not a static string.
  `FEATURE_LABELS` and `display_name()` are **derived** from this registry, and
  `shap_drivers` re-exports `FEATURE_LABELS` (so existing imports are unchanged).
  `ALL_FEATURES` and `FEATURES` must stay in sync — every model feature needs an
  entry (the global chart and the per-row label both read it).
- Add a leak-free test in `tests/test_features.py` on tiny synthetic data with a
  known answer (mirror `test_prior_features_do_not_leak_anchor`).
- `.venv/bin/python -m pytest tests/test_features.py -q` should pass. The
  `test_features_baseline_alignment` integration test will FAIL until Step 3
  rebuilds the parquet — that's the expected tripwire, not a bug.

## Step 2 — Commit the code BEFORE running (provenance)
Experiment-tracking rule (`docs/decisions/0001`): commit the feature code first so
the run's git SHA → run-id provenance points at the exact committed code. One
experiment per commit boundary.

## Step 3 — Rebuild the parquet
`notebooks/03_feature_engineering.ipynb` in place → regenerates
`data/processed/features.parquet`. Verify the new columns materialized and
`ALL_FEATURES ⊆ columns` (the alignment test now passes).

## Step 4 — Train + evaluate both models
- LogReg: `notebooks/04_baseline_logreg.ipynb`; XGBoost: `notebooks/05_xgboost_model.ipynb`.
  Each writes `reports/metrics/<model>_<run>.json` with provenance.
- **Judge on lift over base rate**, not raw PR-AUC (a rarer label mechanically
  lowers raw PR-AUC). The **promotion gate is BOTH PR-AUC AND precision@10%**, on
  **both models** (`docs/decisions/0002`). Baseline stays the production estimator
  unless both clear.
- For a clean attribution, run a **controlled A/B on the same split**: train
  full-feature vs feature-removed using `temporal_split(train_end='2024-07-01',
  val_end='2025-07-01')` and `foodsafety.models.evaluate.evaluate`. Ranking metrics
  (PR-AUC, precision@k, lift) are calibration-invariant, so the uncalibrated
  pipeline is fine for the delta. If the group beats baseline → leave-one-out to
  attribute; if flat → drop it.
- **Fairness check**: per-group test metrics by `static_facility_type` and zip
  prefix. Report **recall@10% (coverage)** alongside PR-AUC — small groups have
  noisy PR-AUC; a PR-AUC dip with rising recall is an ordering artifact, not a
  coverage loss. Treat sub-~50-positive groups as noise (bootstrap the delta).

## Step 5 — Ethics (if the feature could raise a responsible-AI question)
Run the checks from `docs/decisions/0005`: is it a demographic proxy? coverage for
vulnerable-population facilities (children's/school/daycare/hospital/nursing/
shelter)? cold-start (first-inspection) effect? any feedback-loop risk? If a new
principle or residual risk applies, **extend `0005`** (add a numbered principle +
a residual-risk bullet + revision date) rather than spawning a new record.

## Step 6 — If KEPT (cleared the gate): docs + ship
- **Feature contract** `docs/interface_contracts.md`: add the column(s) to the
  section-2 table, bump the contract version, add a changelog row. Schema changes
  **need a PR tagging every owner** (Arun, Bella, Deepak, Aurelia, Jun).
- **`docs/experiments.md`**: one row — change+hypothesis / result (with caveats) /
  verdict / refs. Log negative results too.
- **Decision records**: update `0005` (ethics) if Step 5 found something; add a new
  `docs/decisions/NNNN-*.md` only for a genuine decision (confirm before creating).
- **Re-ship the served model + app JSON** (else the demo runs the old model):
  `PYTHONPATH=src .venv/bin/python scripts/retrain_baseline_sigmoid.py` →
  served model + `data/predictions/scores.parquet` → `app/public/data/scores.json`
  (schema `0.4.0`: **5** `top_drivers` per row + a top-level `calibration
  {a, b, intercept}` Platt triple — both written automatically) +
  `reports/metrics/baseline_sigmoid_<run>.json`; then
  `PYTHONPATH=src .venv/bin/python scripts/build_methodology_json.py` →
  `app/public/data/methodology.json` (also carries the **global feature-impact**
  ranking + the worked **calibrated-waterfall** example). A new feature flows into
  all of these automatically — the global-importance bar, the methodology worked
  example, and the per-establishment detail-page waterfall (which reconstructs
  client-side from the `calibration` triple + the row's `top_drivers`) — *provided
  it has a `FEATURES` entry* (Step 1). Sanity-check `scores.json`: row count, score
  range, `top_drivers` schema (5), **driver labels human-readable — no raw
  `snake_case`**, tier distribution, and that `calibration` is present (a
  per-profile waterfall reconciles when `sigmoid(base + Σdrivers + other) ==
  risk_score`).
- Commit the metrics JSONs (they're git-tracked; **never** commit `data/`).

## Step 7 — If FLAT (missed the gate)
Remove the column(s) from `ALL_FEATURES`, add a "Reverted" row to
`docs/experiments.md` (the negative result is the point), and drop the branch.
Feature *code* may stay if cheap and self-contained (note it's unwired).

## Before committing / PR
- `make test` (or `.venv/bin/python -m pytest -q`) green; `make lint` clean for the
  files you touched (don't expand scope to repo-wide lint debt).
- Notebook outputs stripped on commit (nbstripout / the `clear-outputs` skill).
- One PR per experiment; squash-merge. If a feature **resets the baseline** that
  later experiments are measured against, land it **first**.
- Run `/update-docs` to propagate to the changelog + handoff memory.
