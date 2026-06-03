# CLAUDE.md — Food Safety Intelligence (capstone)

This file OVERRIDES `/Users/jun/projects/CLAUDE.md` for everything inside
`/Users/jun/projects/food-safety-intelligence/`. If anything here conflicts
with the workspace file, this file wins.

---

## Project goal (this iteration only)

Predict forward-window food-safety risk for Chicago restaurants from public
Chicago data (Food Inspections, Business Licenses, 311). Ship two things:

1. A measured, calibrated model (logistic regression baseline + XGBoost) with
   SHAP explainability.
2. A demoable **Next.js web app** that runs on Jun's laptop.

Success = model performance on a **time-held-out** test set + a web app that
loads in <5s and renders a restaurant detail page. Not deployment. Not AWS.

Three product questions the UI must answer for any restaurant:

1. Does it show elevated predicted risk?
2. Is risk improving / worsening / stable over time?
3. What's driving the signal?

---

## What is IN scope

- Chicago Food Inspections, Business Licenses (current + historical), 311
- Training data: inspections from **2019-01-01 onward** (the July 2018
  procedure change makes pre/post labels non-comparable). Pre-2019 inspections
  are used only as burn-in to compute `prior_*` features at the start of 2019.
- **Label**: `y_fail_or_critical_next_180d` — 1 if the restaurant has a Fail
  result OR a priority violation (codes 1–29) within 180 days of the
  `as_of_date`, else 0.
- **Prediction unit**: one row per `(license_id, as_of_date)` rolling daily,
  where `as_of_date = max(inspection_date_seen_so_far) + 1d`. Per-restaurant-
  per-day, not per-scheduled-inspection.
- Time-aware train/val/test split (chronological cutoffs, never random shuffle)
- LogReg baseline → XGBoost, both calibrated
- SHAP explainability (TreeExplainer for XGBoost; coefficients for logreg)
- Metrics: PR-AUC, ROC-AUC, precision@K, top-decile lift, calibration curve,
  fail-rate-by-decile
- Basic group-performance check by `facility_type` and zip prefix
- Web app (Next.js): search (substring on `dba_name`) + map + restaurant detail
  + methodology page
- Local laptop training only

### Violation-text NLP strategy (in scope, hybrid)

Three layers, in this order — A and B are required, C is a stretch:

1. **Structured violation codes (A)** — count of each code 1–29 plus
   `n_priority` and `n_core` rollups. Already extractable from EDA.
2. **Keyword flags (B)** — ~20 hand-picked regex flags on the residual
   text (e.g. `temperature`, `vermin`/`rodent`, `raw chicken`,
   `cross-contamination`, `expired`, `no soap`, `no paper towels`). Each
   flag becomes one SHAP-friendly column.
3. **TF-IDF → TruncatedSVD(50) (C, optional)** — only added in Phase 6
   if there's slack. Defensible "we did NLP" addition without dumping a
   5k-column sparse matrix into XGBoost.

---

## What is OUT of scope — do not add, do not stub, do not leave seams

- **AWS this iteration** — no `boto3`, no S3 paths in code, no SageMaker /
  Lambda / Bedrock references. The Phase-2 plan IS hosted training and
  scoring on AWS (see Roadmap) — but no AWS code lands in this iteration.
  The seam for the future migration is one env var (`FOODSAFETY_DATA_DIR`);
  no other seams should be added pre-emptively.
- Deployment of any kind this iteration (Vercel, Streamlit Cloud, Docker,
  K8s). The web app runs `next dev` locally.
- Hosted inference / FastAPI / REST endpoints / Next.js API routes that hit
  a live model
- NOAA weather data
- Yelp Open Dataset + Yelp fuzzy join
- LLM / Bedrock / transformer NLP (TF-IDF + SVD is the ceiling, layer C only)
- Production fairness audit (disparate impact tests, reweighting). Group-perf
  *tables* are in scope; full audit is later.
- Real-time ingestion, authentication, multi-city support
- **Scheduled / periodic ingestion (Airflow, Prefect, cron, etc.)** — see
  "Roadmap" below; not in this iteration
- **Live model inference at request time** — the web app never calls the
  model on a page load, even after AWS arrives. The batch-score-to-JSON
  pattern (Python pipeline writes `scores.parquet` → script writes
  `scores.json` → app reads the precomputed JSON) is **permanent by design**;
  what changes in Phase 2 is *where* the batch job runs (laptop now,
  SageMaker / scheduled Lambda later) and *where* the JSON lives
  (`app/public/data/` now, CloudFront-fronted S3 later).

If a teammate proposes any of the above, the answer is "Phase 2, after demo."
Do not write a `# TODO: AWS later` comment. Do not import then comment-out a
dep. Just don't write the seam.

### Roadmap (acknowledged, not now)

These are likely Phase 2 work. They are NOT in current scope — same rules
as the OUT list above (no stubs, no seams, no TODO comments). Listed here so
when someone asks "what about X?" the answer is "noted, post-demo."

- **Periodic incremental ingestion (Airflow / Prefect / scheduled job)** —
  daily or weekly pulls of new inspection, complaint, and license records.
  Note: `fetch_soda_keyset` is already cursor-based, so when this comes back
  it can resume from a stored `created_date` / `inspection_date` watermark
  without re-pulling the world. No scheduling code lives in this repo for
  this iteration.
- AWS (Bedrock, SageMaker, S3) for hosted training / inference
- NOAA weather features, Yelp Open Dataset + fuzzy join
- LLM-based violation-text classification or NLP search
- Production fairness audit (disparate-impact tests, reweighting)
- Multi-city support beyond Chicago
- Deployment (Vercel, Docker, K8s, etc.)

---

## Tech stack (locked)

The repo is **two languages joined at the JSON seam**. Python builds the
model + writes `scores.parquet`; a small Python script converts that to
`app/public/data/scores.json`; the Next.js web app reads only the JSON.

### Python (model + data pipeline)

- Python 3.11, managed via `uv` (one `pyproject.toml`, one `uv.lock`)
- pandas + DuckDB for joins/aggregations; pyarrow for parquet
- scikit-learn for baseline + preprocessing pipelines + calibration
- xgboost for the "good" model
- shap for explainability
- matplotlib for notebook charts (not the web app)
- pytest + ruff (line length 100) for tests/lint

### Web app (TypeScript, in `app/`)

- **Next.js 16 (App Router)** + **React 19** + **TypeScript strict mode**
  (no `any`; type at boundaries, let inference do the rest)
- **Tailwind CSS** for styling
- **shadcn/ui** components built on Radix primitives
- **lucide-react** for icons
- **Map**: `react-map-gl` + `maplibre-gl` with OpenStreetMap-style raster
  tiles (no API key needed). Can swap to Mapbox vector tiles later if we
  want, but only after demo.
- **Charts**: Recharts. No plotly in the web app.
- **Server components by default**. Use `"use client"` only when the
  component needs interactivity, state, or browser-only APIs.
- No new top-level deps without a PR comment justifying it.

Notably absent: Streamlit (replaced), Mapbox (deferred), Google Maps (no
billing), Redux/Zustand (small state, use React hooks).

---

## Folder conventions (hard rules)

- `notebooks/` — exploratory + modeling. Numbered `NN_topic.ipynb`. Owner
  named in the first markdown cell. Outputs cleared on commit (nbstripout).
- `src/foodsafety/` — the importable Python package. Anything used in two
  places lives here.
- `app/` — Next.js project root (its own `package.json`, `next.config.js`,
  `tsconfig.json`, `tailwind.config.ts`). Routes live in `app/src/app/`
  (App Router with src/ directory). The web app reads only from
  `app/public/data/*.json` — never from `data/raw/` or `data/processed/`
  directly, never from the Python side, never from a live API.
- `data/` — fully gitignored. Subfolders: `raw/`, `interim/`, `processed/`,
  `models/`, `predictions/`. Test fixtures live under `tests/fixtures/`, NOT `data/`.
- `design/` — temporary design artifacts (HTML mockups, screenshots,
  references). Removable once the final UI is built.
- Saved models: `data/models/<name>_<YYYYMMDD>.joblib` plus a sidecar
  `metadata.json` (train cutoff, features, metrics). **Never overwrite.**
- `reports/figures/` — small PNGs referenced by the writeup. Checked in.
- `reports/metrics/` — one JSON per training run. Checked in, diffable.
- `scripts/` — Python CLI entry points called from the Makefile.
- `tests/` — pytest, mirrors `src/foodsafety/`.
- `docs/` — short markdown only. No auto-generated API docs.
- `docs/weekly/YYYY-MM-DD.md` — Friday async check-in per teammate.

---

## Interface contracts (do not break silently)

Three parquets + one JSON are the cross-team contract. **Schema changes
require a PR tagging every owner** (Arun, Bella, Deepak, Aurelia, Jun).

| Artifact | Key | Owner | Notes |
|---|---|---|---|
| `data/processed/inspections_labeled.parquet` | `(license_id, inspection_date)` | Arun | Includes label `y_fail_or_critical_next_180d`. Burn-in rows (pre-2019) flagged `is_burnin=True` |
| `data/processed/features.parquet` | `(license_id, as_of_date)` | Bella + Deepak | All `prior_*` features MUST use `.shift()` or `< as_of_date` guards |
| `data/predictions/scores.parquet` | `(license_id, as_of_date)` | Bella | Columns: `license_id, dba_name, address, lat, lon, as_of_date, risk_score, risk_tier, top_drivers (list[dict]), trend_slope_90d` |
| `app/public/data/scores.json` | same | Bella (auto-generated) | `scores.parquet` converted via `scripts/parquet_to_json.py`. Dates as ISO strings, `top_drivers` as array of objects. The web app reads this. |

The full schema for each lives in `docs/interface_contracts.md` — that doc is
source of truth.

---

## Code style

### Python (`src/foodsafety/`, `scripts/`, modeling notebooks)

- Type hints on every function in `src/foodsafety/`. Notebook scratch exempt.
- Pure functions over classes. A class only if state is genuinely needed.
- Comment the WHY, not the WHAT. Mandatory comments for:
  - Any `.shift()` / `< as_of_date` leakage guard
  - The July 2018 Chicago inspection-procedure change (and the 2019 cutoff)
  - Class-imbalance handling decisions
  - Non-default model hyperparameters
  - The `RELEVANT_SR_TYPES` list (empirically derived via
    `$select=sr_type,count(*)` on the SODA API)
- No `print(df)` in committed notebooks — use `df.head()` or `peek(df, name)`.
- Every modeling notebook starts with: owner, date, train cutoff, label window,
  dataset version (parquet mtime). Ends with: saved artifact path + one-line metric.

### TypeScript (`app/`)

- **`strict: true`** in `tsconfig.json`. No `any`. Type at boundaries; let
  inference handle the rest.
- **Verify framework versions before writing code.** Next.js 16 + React 19
  have breaking changes from older guides and training data. Check the
  installed version (`app/package.json`) and the docs in `app/node_modules/next/dist/docs/`
  before assuming an API exists.
- **Server components by default**. Use `"use client"` only when you need
  interactivity, state, or browser-only APIs (the map, the search input).
- Co-locate small state in hooks; reach for context only if a value is
  consumed by 3+ unrelated subtrees.
- Use `shadcn/ui` components from `app/src/components/ui/` rather than
  rolling new primitives. If a needed component doesn't exist, add it via
  `pnpm dlx shadcn add <name>` (or `npx`).
- No emoji in committed code or UI unless explicitly asked.
- Accessibility is default: keyboard nav, ARIA labels on icon-only buttons,
  ≥44px tap targets, sufficient contrast.

---

## Team workflow

Workstreams + owners:

| Workstream | Primary | Backup |
|---|---|---|
| DE / loaders / joins | **Arun** | Deepak |
| EDA / label definition | **Aurelia** | Bella |
| Modeling (baseline + XGBoost) | **Bella + Deepak** | Jun |
| Eval + SHAP + `scores.parquet` | **Bella** | Deepak |
| Web app (Next.js) | **Aurelia + Jun** | Arun |
| PM / scope guard | **Jun** | Arun (tiebreaker) |

Process:

- Branch per workstream: `de/*`, `eda/*`, `mle/*`, `app/*`, `pm/*`.
- Squash-merge to `main`. No direct pushes to `main`.
- One reviewer required; backup owner is the default reviewer.
- PR review SLA = 24h. If silent past 24h on a clearly-scoped workstream
  branch, author may self-merge.
- **Friday async check-in**: each person edits `docs/weekly/YYYY-MM-DD.md`
  with milestones hit, next milestones, one learning, help needed.
- No daily standup. No story points. No sprint planning.

---

## What NOT to do

- Do NOT use `train_test_split(shuffle=True)` on inspections. Use the temporal
  splitter in `src/foodsafety/utils/time.py`.
- Do NOT compute features without `.shift()` or `< as_of_date` guards.
- Do NOT pull live SODA data inside the web app. **App reads `scores.json` only.**
- Do NOT call the Python model from the web app at runtime — even via a
  local Flask/FastAPI sidecar. The batch-write-JSON pattern is the contract.
- Do NOT refactor someone else's workstream while doing your own.
- Do NOT add a new dataset without updating `docs/data_dictionary.md`.
- Do NOT commit `data/`, `.env`, `*.joblib`, `.ipynb_checkpoints/`,
  `_partial_*/`, `app/node_modules/`, `app/.next/`.
- Do NOT introduce new Python dependencies without `pyproject.toml` + PR
  justification. Same for npm deps in `app/package.json`.
- Do NOT write a `README.md`, planning doc, or summary file unless asked.
- Do NOT use SMOTE on time-split data — it inflates apparent PR-AUC. Use
  `class_weight='balanced'` or XGBoost's `scale_pos_weight` instead.
- Do NOT train on pre-2019 inspections. They're burn-in only.
- Do NOT use emoji in UI copy or committed code unless explicitly asked.

---

## Reproducibility

- `RANDOM_STATE = 42` in `src/foodsafety/config.py`. Used everywhere.
- Python pipeline runnable end-to-end via `make all` on a fresh clone after
  `uv sync`. Web app runnable via `cd app && pnpm install && pnpm dev`.
- Cache dir configurable via `FOODSAFETY_DATA_DIR` env var (defaults to `./data/`).
  This is the **only** future-proofing seam we leave for AWS.
