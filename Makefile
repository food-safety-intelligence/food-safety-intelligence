# Food Safety Intelligence — top-level commands.
# Targets are intentionally minimal in week 1; expand as scripts land.

.PHONY: help data features train predict export test lint all clean

help:
	@echo "Python pipeline:"
	@echo "  data       Fetch raw datasets from Chicago SODA (~15 min first run)"
	@echo "  features   Build interim + processed parquet tables"
	@echo "  train      Train baseline + XGBoost; write data/models/*.joblib"
	@echo "  predict    Write data/predictions/scores.parquet"
	@echo "  export     Convert scores.parquet -> app/public/data/scores.json (web-app input)"
	@echo "  all        data -> features -> train -> predict -> export"
	@echo ""
	@echo "Quality:"
	@echo "  test       Run pytest"
	@echo "  lint       Run ruff check + format --check"
	@echo "  clean      Remove __pycache__, .pytest_cache, .ruff_cache"
	@echo ""
	@echo "Web app (run separately, see README): cd app && pnpm dev"

data:
	uv run python scripts/fetch_data.py

features:
	uv run python scripts/build_features.py

train:
	uv run python scripts/train_baseline.py
	uv run python scripts/train_xgb.py

predict:
	uv run python scripts/run_pipeline.py --stage predict

export:
	uv run python scripts/parquet_to_json.py

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

all: data features train predict export

clean:
	find . -name __pycache__ -type d -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
