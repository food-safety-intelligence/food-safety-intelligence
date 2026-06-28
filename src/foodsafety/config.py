"""Project-wide constants and paths.

Importable from anywhere as `from foodsafety.config import ...`.
Single source of truth for dataset IDs, the SODA base URL, and where data lives.
"""

from __future__ import annotations

import os
from pathlib import Path

# Reproducibility: every random seed in the pipeline reads this.
RANDOM_STATE: int = 42

# Project root resolved from this file's location. Robust to notebook CWD
# weirdness (notebooks run from notebooks/, scripts run from project root).
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent

# Override DATA_DIR via env var to point at a different base location. It may be a
# local path (default) or an ``s3://…`` URI (Phase-2 AWS, read via foodsafety.io.storage).
# The default resolves to <project_root>/data regardless of where the import happens.
_DATA_DIR: str = os.environ.get("FOODSAFETY_DATA_DIR") or str(_PROJECT_ROOT / "data")


def _join(base: str | Path, *parts: str) -> str | Path:
    """Join path parts onto a base that may be local or s3://.

    Keep local roots as ``Path`` (notebooks/scripts do Path ops on them); for an
    ``s3://`` base return a plain string prefix, because ``Path`` collapses the
    ``//`` after the scheme into ``s3:/bucket``.
    """
    if str(base).startswith("s3://"):
        out = str(base).rstrip("/")
        for part in parts:
            out = f"{out}/{part.strip('/')}"
        return out
    return Path(base).joinpath(*parts)


DATA_DIR: str | Path = _DATA_DIR if _DATA_DIR.startswith("s3://") else Path(_DATA_DIR)

RAW_DIR: str | Path = _join(_DATA_DIR, "raw")
INTERIM_DIR: str | Path = _join(_DATA_DIR, "interim")
PROCESSED_DIR: str | Path = _join(_DATA_DIR, "processed")
MODELS_DIR: str | Path = _join(_DATA_DIR, "models")
PREDICTIONS_DIR: str | Path = _join(_DATA_DIR, "predictions")

# Canonical feature-set artifact for the migrated pipeline. Versioned under
# processed/features/<name>.parquet (rather than a flat processed/features.parquet) so
# multiple experiments can keep distinctly-named sets side by side; the exact contract
# version is still recorded as the feature_set_version hash in each run's metadata.
# Override the name with FOODSAFETY_FEATURES_NAME. build_features.py writes this path;
# retrain reads it.
FEATURES_NAME: str = os.environ.get("FOODSAFETY_FEATURES_NAME") or "features_current_inspection"
FEATURES_PATH: str | Path = _join(PROCESSED_DIR, "features", f"{FEATURES_NAME}.parquet")

# Web-app JSON targets — the three files the Next.js app reads (scores.json,
# inspection_history.json, methodology.json). Default writes under app/public/data
# (committed fallback); override to s3://<bucket>/web-app-data for the hosted bucket.
_WEB_APP_DATA_DIR: str = os.environ.get("FOODSAFETY_WEB_APP_DATA_DIR") or str(
    _PROJECT_ROOT / "app" / "public" / "data"
)
WEB_APP_DATA_DIR: str | Path = (
    _WEB_APP_DATA_DIR if _WEB_APP_DATA_DIR.startswith("s3://") else Path(_WEB_APP_DATA_DIR)
)

# Chicago SODA (Socrata) API base. All datasets are served from here.
SODA_BASE: str = "https://data.cityofchicago.org/resource"

# Dataset IDs map to the Socrata "4x4" identifiers in each dataset's URL.
DATASETS: dict[str, str] = {
    "inspections": "4ijn-s7e5",  # Chicago Food Inspections (2010-present)
    "complaints_311": "v6vf-nfxy",  # Chicago 311 Service Requests
    "licenses_current": "uupf-x98q",  # Business Licenses — current active
    "licenses_historical": "vgg9-bn8p",  # Business Licenses — historical
    # Physical-plant condition, joined to food establishments by block-face
    # (lat/lon proximity). Genuinely orthogonal to inspection history — see
    # docs/model-experiments.md / the building-features run.
    "building_permits": "ydr8-5enu",  # Building Permits (2006-present)
    "building_violations": "22u3-xenr",  # Building Violations (2006-present)
}

# 311 SR types we treat as food-safety-relevant. Derived empirically by querying
#   GET /resource/v6vf-nfxy.json?$select=sr_type,count(*)&$group=sr_type&$order=count_desc
# and filtering for food / sanitation / rodent / restaurant keywords. The full
# 311 table is ~14M rows across 110 types — most are unrelated (potholes,
# aircraft noise, etc.) — so we pull only these 8 types when fetching 311 data.
RELEVANT_SR_TYPES: list[str] = [
    "Restaurant Complaint",
    "Pushcart Food Vendor Complaint",
    "Rodent Baiting/Rat Complaint",
    "Sanitation Code Violation",
    "Garbage Cart Maintenance",
    "Missed Garbage Pick-Up Complaint",
    "Fly Dumping Complaint",
    "Dead Animal Pick-Up Request",
]

# Label window: predict whether a restaurant will have a Fail OR priority
# violation (codes 1-29) within this many days of `as_of_date`.
LABEL_WINDOW_DAYS: int = 180

# Training cutoff. Inspections before this date are used only as burn-in for
# `prior_*` features at the start of 2019 (the July 2018 Chicago inspection-
# procedure change makes pre/post labels non-comparable, so we don't train on
# the pre-period).
TRAIN_START_DATE: str = "2019-01-01"
