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

# Override DATA_DIR via env var to point at a different cache location (e.g. an
# SSD, a shared NAS, or — in a future iteration — an S3 mount). The default
# resolves to <project_root>/data regardless of where the import happens.
DATA_DIR: Path = Path(os.environ.get("FOODSAFETY_DATA_DIR") or (_PROJECT_ROOT / "data"))

RAW_DIR: Path = DATA_DIR / "raw"
INTERIM_DIR: Path = DATA_DIR / "interim"
PROCESSED_DIR: Path = DATA_DIR / "processed"
MODELS_DIR: Path = DATA_DIR / "models"
PREDICTIONS_DIR: Path = DATA_DIR / "predictions"

# Chicago SODA (Socrata) API base. All four datasets are served from here.
SODA_BASE: str = "https://data.cityofchicago.org/resource"

# Dataset IDs map to the Socrata "4x4" identifiers in each dataset's URL.
DATASETS: dict[str, str] = {
    "inspections":         "4ijn-s7e5",  # Chicago Food Inspections (2010-present)
    "complaints_311":      "v6vf-nfxy",  # Chicago 311 Service Requests
    "licenses_current":    "uupf-x98q",  # Business Licenses — current active
    "licenses_historical": "vgg9-bn8p",  # Business Licenses — historical
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
