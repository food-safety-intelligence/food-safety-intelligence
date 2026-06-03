# Food Safety Intelligence — Capstone

Predicting forward-window food-safety risk for Chicago restaurants from public
inspection, business-license, and 311-complaint data. UC Berkeley MIDS capstone.

**Team**: Jun Xu (PM), Arun Agarwal, Bella Davis, Deepak Srivastava, Aurelia Yang

> **Latest status**: see [`docs/weekly/`](docs/weekly/) — newest dated file is
> the current snapshot of what's built, what's open, and how to verify locally.

## What we're building this iteration

1. A measured model (logistic regression baseline → calibrated XGBoost) with
   SHAP explainability.
2. A Next.js web app that runs on a laptop and answers three questions for any
   Chicago restaurant: *Is risk elevated? Improving or worsening? What's driving it?*

No deployment, no AWS — see `CLAUDE.md` for the full scope contract.

## Run locally

The repo is two languages joined at a JSON seam: Python builds the model and
writes `scores.parquet`; a script converts that to JSON; Next.js reads it.

### Python (model + data pipeline)

Requires Python 3.11 and [`uv`](https://docs.astral.sh/uv/) (`brew install uv` on macOS).

```bash
git clone <repo> && cd food-safety-intelligence
uv sync --extra dev          # creates .venv, installs deps
uv run nbstripout --install  # one-time: wire the git filter that
                             # strips notebook outputs on commit
cp .env.example .env         # default settings work; edit if needed

# One-time data pull (or copy from teammate's data/raw/ to skip this — ~15 min)
make data

# End-to-end: build features → train baseline + XGBoost → write scores.parquet → export JSON
make all
```

### Web app (Next.js)

Requires Node 20+ and pnpm (or npm). After `make all` has produced
`app/public/data/scores.json`:

```bash
cd app
pnpm install        # or: npm install
pnpm dev            # http://localhost:3000
```

## Project layout

| Path | What lives there |
|---|---|
| `notebooks/` | Numbered EDA + modeling notebooks (`NN_topic.ipynb`) |
| `src/foodsafety/` | Importable Python package — loaders, features, models, eval, explain |
| `app/` | Next.js web app (App Router + TypeScript + Tailwind + shadcn/ui). Reads `app/public/data/*.json` only |
| `design/` | UI mockups + design references (pre-build exploration) |
| `data/` | Local cache (gitignored). `raw/`, `interim/`, `processed/`, `models/`, `predictions/` |
| `scripts/` | Python CLI entry points used by the Makefile |
| `tests/` | pytest, mirrors `src/foodsafety/` |
| `docs/` | Data dictionary, label definition, interface contracts, weekly check-ins |
| `reports/` | Figures + per-run metrics JSON + final writeup |

## Where to start (by role)

- **DE / loaders (Arun)**: `src/foodsafety/io/` — lift loader cell from `notebooks/01_dataset_overview_eda.ipynb`
- **EDA / labels (Aurelia)**: `notebooks/01_dataset_overview_eda.ipynb`, then `02_label_construction.ipynb`
- **Modeling (Bella + Deepak)**: `notebooks/04_baseline_logreg.ipynb`, then `05_xgboost_model.ipynb`
- **Eval / SHAP (Bella)**: `notebooks/06_eval_and_calibration.ipynb`, `07_shap_explanations.ipynb`
- **App (Aurelia + Jun)**: `app/src/app/page.tsx` against the mock `app/public/data/scores_mock.json` (converted from `tests/fixtures/scores_mock.parquet`)

See `CLAUDE.md` for the full project rules and `docs/interface_contracts.md`
for the cross-team parquet schemas.

## Weekly check-ins

Friday async: each teammate edits `docs/weekly/YYYY-MM-DD.md` with milestones
hit, next milestones, one learning, and help needed. 3–5 min team check-in
covers these in class.
