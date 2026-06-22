# Food Safety Intelligence — top-level commands.
#
# Pipeline scripts (all read/write FOODSAFETY_DATA_DIR — local by default, or an
# s3:// base):
#     data       — pull raw SODA datasets → RAW_DIR
#     features   — build the feature set → processed/features/<name>.parquet
#     retrain    — train + score + export scores.json
#     history    — export per-restaurant inspection history → JSON sidecar
#     publish    — upload the built deploy artifacts (model, features, scores, JSON) → S3
#     normalize  — clean nbformat cell IDs on all notebooks
#     test, lint
#
# Full local rebuild:           make data features retrain history
# Against S3:  FOODSAFETY_DATA_DIR=s3://food-safety-intelligence-data make data features retrain history
# Publish a local build to S3:  make features retrain history && make publish
# The EDA / label-construction steps still run from notebooks/0{1,2}_*.ipynb.

.PHONY: help data features retrain history publish normalize test lint clean

help:
	@echo "Python pipeline (working today):"
	@echo "  data       Pull raw SODA datasets → RAW_DIR"
	@echo "  features   Build the feature set → processed/features/<name>.parquet"
	@echo "  retrain    Retrain baseline w/ sigmoid calibration → scores.json"
	@echo "  history    Export inspections_labeled.parquet → inspection_history.json"
	@echo "  publish    Upload the built deploy artifacts to S3 (scripts/publish.py)"
	@echo "  normalize  Rewrite notebooks so nbformat cell IDs are persisted"
	@echo ""
	@echo "  data/features/retrain/history read/write FOODSAFETY_DATA_DIR (local or s3://)."
	@echo "  Label construction still runs from notebooks/0{1,2}_*.ipynb."
	@echo ""
	@echo "Quality:"
	@echo "  test       Run pytest"
	@echo "  lint       Run ruff check + format --check"
	@echo "  clean      Remove __pycache__, .pytest_cache, .ruff_cache"
	@echo ""
	@echo "Web app (run separately, see README): cd app && npm run dev"

data:
	PYTHONPATH=src $(PYTHON) scripts/ingest_raw.py

features:
	PYTHONPATH=src $(PYTHON) scripts/build_features.py

retrain:
	PYTHONPATH=src $(PYTHON) scripts/retrain_baseline_sigmoid.py

history:
	PYTHONPATH=src $(PYTHON) scripts/export_inspection_history.py

publish:
	PYTHONPATH=src $(PYTHON) scripts/publish.py

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
