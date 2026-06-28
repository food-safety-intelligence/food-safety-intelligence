# Food Safety Intelligence — top-level commands.
#
# Pipeline order for a clean rebuild:
#   1. make features                — build features.parquet
#   2. make retrain                 — train baseline + write scores.json
#      make history                 — export per-restaurant inspection history
#
# Quick rebuild (raw data already fetched):
#   make features && make retrain history
#
# EDA / labels / other raw data: open notebooks/0{0..6}_*.ipynb

.PHONY: help fetch_bldg_violations features retrain history normalize test lint clean

help:
	@echo "Python pipeline:"
	@echo "  features               Build features.parquet (inspections + licenses)"
	@echo "  retrain                Retrain baseline w/ sigmoid calibration → scores.json"
	@echo "  history                Export inspections_labeled.parquet → inspection_history.json"
	@echo "  normalize              Rewrite notebooks so nbformat cell IDs are persisted"
	@echo ""
	@echo "Not yet scripted — run from notebooks/:"
	@echo "  data       Fetch raw datasets (run notebooks/00_feasibility_eda.ipynb)"
	@echo ""
	@echo "Optional (building-violation features are unwired — revisit only):"
	@echo "  fetch_bldg_violations  Fetch building violations → data/raw/building_violations.parquet"
	@echo ""
	@echo "Quality:"
	@echo "  test       Run pytest"
	@echo "  lint       Run ruff check + format --check"
	@echo "  clean      Remove __pycache__, .pytest_cache, .ruff_cache"
	@echo ""
	@echo "Web app (run separately, see README): cd app && npm run dev"

fetch_bldg_violations:
	PYTHONPATH=src $(PYTHON) scripts/fetch_building_violations.py

features:
	PYTHONPATH=src $(PYTHON) scripts/build_features.py

retrain:
	PYTHONPATH=src $(PYTHON) scripts/retrain_baseline_sigmoid.py

history:
	PYTHONPATH=src $(PYTHON) scripts/export_inspection_history.py

normalize:
	$(PYTHON) scripts/normalize_notebooks.py

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

clean:
	find . -name __pycache__ -type d -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache

# Override PYTHON via the environment to point at your venv:
#   make retrain PYTHON=/Users/jun/anaconda3/bin/python
# Defaults to `uv run python` if uv is on PATH, else system python3.
PYTHON ?= $(shell command -v uv >/dev/null 2>&1 && echo "uv run python" || echo "python3")
