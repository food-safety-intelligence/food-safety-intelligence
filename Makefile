# Food Safety Intelligence — top-level commands.
#
# What's REAL vs aspirational, as of 2026-06-03:
#   Real (scripts exist + tested):
#     retrain    — end-to-end train + score + export scores.json
#     history    — export per-restaurant inspection history → JSON sidecar
#     normalize  — clean nbformat cell IDs on all notebooks
#     test, lint
#   Aspirational (not yet written — current pipeline runs from notebooks):
#     data, features
#
# To rebuild scores.json today:  make retrain history
# To run the EDA / labels / feature build:  open notebooks/0{0..6}_*.ipynb

.PHONY: help retrain history normalize test lint clean

help:
	@echo "Python pipeline (working today):"
	@echo "  retrain    Retrain baseline w/ sigmoid calibration → scores.json"
	@echo "  history    Export inspections_labeled.parquet → inspection_history.json"
	@echo "  normalize  Rewrite notebooks so nbformat cell IDs are persisted"
	@echo ""
	@echo "Not yet scripted — run from notebooks/:"
	@echo "  data       Fetch raw datasets (run notebooks/00_feasibility_eda.ipynb)"
	@echo "  features   Build features.parquet (run notebooks/03_feature_engineering.ipynb)"
	@echo ""
	@echo "Quality:"
	@echo "  test       Run pytest"
	@echo "  lint       Run ruff check + format --check"
	@echo "  clean      Remove __pycache__, .pytest_cache, .ruff_cache"
	@echo ""
	@echo "Web app (run separately, see README): cd app && npm run dev"

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
