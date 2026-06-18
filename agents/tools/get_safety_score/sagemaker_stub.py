"""
SageMaker XGBoost inference stub
----------------------------------
This module wraps calls to the SageMaker real-time inference endpoint that
hosts the XGBoost food-safety model.

CURRENT STATE: STUB
  All calls return deterministic dummy predictions derived from the restaurant
  name + address hash so results are stable across repeated calls without
  hitting AWS. Replace _invoke_stub() with _invoke_real() when the SageMaker
  endpoint is live.

Swap procedure (single line change):
  In score_restaurants(), change:
      raw = _invoke_stub(feature_rows)
  to:
      raw = _invoke_real(feature_rows)

Real endpoint contract
-----------------------
  Endpoint name: food-safety-xgboost-<env>    (set via SAGEMAKER_ENDPOINT env var)
  Input:  CSV rows, one row per restaurant, columns in FEATURE_ORDER
  Output: JSON  {"predictions": [{"score": float, "shap": {...}}]}

  The XGBoost model output pipeline (SageMaker script mode):
    - Input:  feature vector (26 floats/ints, see FEATURE_ORDER)
    - Output: calibrated probability (sigmoid-scaled) 0.0–1.0
    - SHAP:   TreeExplainer values returned alongside score when
              RETURN_SHAP=1 environment variable is set on the endpoint

Feature ordering mirrors data/models/baseline_sigmoid_20260605_metadata.json.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
from typing import Any

# ---------------------------------------------------------------------------
# Feature contract (must match the training pipeline column order exactly)
# ---------------------------------------------------------------------------

FEATURE_ORDER: list[str] = [
    "prior_inspections",
    "prior_fails",
    "prior_priority_violations",
    "prior_core_violations",
    "prior_fail_or_priority_events",
    "days_since_last_inspection",
    "days_since_last_fail",
    "temporal_month",
    "temporal_quarter",
    "license_age_days",
    "license_n_history_rows",
    "static_facility_type",
    "static_risk_tier",
    "static_zip",
    "flag_kw_temperature",
    "flag_kw_cooling",
    "flag_kw_raw_food",
    "flag_kw_cross_contamination",
    "flag_kw_expired",
    "flag_kw_rodent",
    "flag_kw_pest",
    "flag_kw_no_soap",
    "flag_kw_no_paper_towels",
    "flag_kw_handwash_sink",
    "flag_kw_sewage",
    "flag_kw_certified_manager",
]

# Risk tier thresholds — mirror scores.ts in the web app.
def _tier(score: float) -> str:
    if score < 0.2:  return "Low"
    if score < 0.4:  return "Moderate"
    if score < 0.65: return "Elevated"
    return "High"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def score_restaurants(feature_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Score a batch of restaurants.

    Args:
        feature_rows: list of dicts.  Each dict must contain at minimum:
            - "osm_id"  (str)  — passed through unchanged
            - "name"    (str)  — used for stub hash; not sent to model
            Each dict should also contain all keys in FEATURE_ORDER with
            numeric values.  Missing features default to 0.

    Returns:
        list of dicts with keys:
            osm_id, risk_score (float 0–1), risk_tier (str),
            shap_drivers (list[dict]), stub (bool)
    """
    # ── Switch here when the real endpoint is live ──────────────────────────
    USE_STUB = os.environ.get("SAGEMAKER_USE_STUB", "true").lower() != "false"
    # ────────────────────────────────────────────────────────────────────────

    if USE_STUB:
        return _invoke_stub(feature_rows)
    else:
        return _invoke_real(feature_rows)


# ---------------------------------------------------------------------------
# Stub implementation
# ---------------------------------------------------------------------------

def _invoke_stub(feature_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Returns realistic dummy scores without hitting AWS.

    Score derivation: deterministic hash of (name + address) so the same
    restaurant always gets the same score — useful for repeatable integration
    testing.  The distribution mimics the real model output: ~10% High,
    ~16% Elevated, ~53% Moderate, ~21% Low (mirrors the mock scores.json
    tier_counts ratios).
    """
    results: list[dict[str, Any]] = []

    for row in feature_rows:
        seed_str = f"{row.get('name', '')}|{row.get('address', '')}".lower()
        seed = int(hashlib.md5(seed_str.encode()).hexdigest(), 16) % (2**32)
        rng = random.Random(seed)

        # Skew distribution toward lower scores (most restaurants are safe).
        # Beta(1.5, 8) peaks around 0.16 which matches Chicago's ~10% positive rate.
        raw_u = rng.betavariate(1.5, 8.0)
        score = round(raw_u, 4)
        tier = _tier(score)

        # Build plausible SHAP drivers based on score range.
        shap_drivers = _stub_shap_drivers(score, rng)

        results.append({
            "osm_id":      row.get("osm_id", ""),
            "name":        row.get("name", ""),
            "risk_score":  score,
            "risk_tier":   tier,
            "shap_drivers": shap_drivers,
            # Signals to downstream code and the UI that this is stub data.
            "stub":        True,
            "stub_note":   (
                "Score from stub — SageMaker endpoint not yet configured. "
                "Set SAGEMAKER_USE_STUB=false and SAGEMAKER_ENDPOINT to use real model."
            ),
        })

    return results


def _stub_shap_drivers(score: float, rng: random.Random) -> list[dict[str, Any]]:
    """
    Generate a plausible SHAP driver list proportional to the stub score.

    High-score restaurants get positive (risk-increasing) drivers.
    Low-score restaurants get negative (risk-decreasing) drivers.
    """
    POSITIVE_DRIVERS = [
        ("prior_priority_violations", "Prior priority violations",
         "Recurring priority-class violations in the past 2 years"),
        ("flag_kw_temperature",       "Temperature violation on record",
         "Cold- or hot-holding temperature cited in a prior inspection"),
        ("flag_kw_rodent",            "Pest / vermin violation on record",
         "Rodent or pest citation in inspection history"),
        ("days_since_last_inspection","Long gap since last inspection",
         "Inspection cadence is above the 220–300 day typical range"),
        ("prior_fails",               "Prior failed inspections",
         "One or more Fail results in the past 2 years"),
        ("flag_kw_cross_contamination","Cross-contamination violation",
         "Raw/ready-to-eat food separation issue cited previously"),
        ("flag_kw_cooling",           "Improper cooling on record",
         "Food not cooled from 135 °F to 70 °F within required window"),
    ]

    NEGATIVE_DRIVERS = [
        ("prior_fails",               "No failed inspections",
         "All recent inspections resulted in Pass or Pass w/ Conditions"),
        ("prior_priority_violations", "No priority violations",
         "No priority-class violations (codes 1–29) in the past 2 years"),
        ("license_age_days",          "Established license history",
         "Business has operated under this license for 5+ years"),
        ("flag_kw_rodent",            "No pest complaints nearby",
         "No 311 rodent or pest complaints within 300 m in the past 90 days"),
        ("days_since_last_inspection","Recently inspected",
         "Inspected within the last 180 days"),
    ]

    drivers: list[dict[str, Any]] = []

    if score >= 0.4:
        # Pick 2–4 positive drivers scaled by score magnitude.
        n = 2 + int((score - 0.4) / 0.25 * 2)
        chosen = rng.sample(POSITIVE_DRIVERS, min(n, len(POSITIVE_DRIVERS)))
        for i, (feature, label, detail) in enumerate(chosen):
            shap_val = round(score * (0.35 - i * 0.05) * rng.uniform(0.8, 1.2), 3)
            drivers.append({
                "feature": feature,
                "label":   label,
                "detail":  detail,
                "shap":    shap_val,
                "direction": "positive",
            })
    else:
        # Pick 1–3 negative drivers for safer restaurants.
        n = 1 + int((0.4 - score) / 0.4 * 2)
        chosen = rng.sample(NEGATIVE_DRIVERS, min(n, len(NEGATIVE_DRIVERS)))
        for i, (feature, label, detail) in enumerate(chosen):
            shap_val = round(-1 * (0.3 - score) * (0.4 - i * 0.06) * rng.uniform(0.8, 1.2), 3)
            drivers.append({
                "feature": feature,
                "label":   label,
                "detail":  detail,
                "shap":    shap_val,
                "direction": "negative",
            })

    return sorted(drivers, key=lambda d: abs(d["shap"]), reverse=True)


# ---------------------------------------------------------------------------
# Real SageMaker implementation (inactive until endpoint is provisioned)
# ---------------------------------------------------------------------------

def _invoke_real(feature_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Invoke the live SageMaker XGBoost endpoint.

    Environment variables required:
        SAGEMAKER_ENDPOINT  — endpoint name, e.g. "food-safety-xgboost-prod"
        AWS_REGION          — default "us-east-1"

    The endpoint is expected to accept CSV (one row per restaurant,
    features in FEATURE_ORDER) and return JSON:
        {"predictions": [{"score": float, "shap": {feature: float, ...}}]}
    """
    import boto3  # noqa: PLC0415 — only imported when real endpoint is active

    endpoint_name = os.environ["SAGEMAKER_ENDPOINT"]
    region        = os.environ.get("AWS_REGION", "us-east-1")

    client = boto3.client("sagemaker-runtime", region_name=region)

    # Build CSV payload — one row per restaurant, features in FEATURE_ORDER.
    csv_lines: list[str] = []
    for row in feature_rows:
        values = [str(row.get(f, 0)) for f in FEATURE_ORDER]
        csv_lines.append(",".join(values))
    payload = "\n".join(csv_lines)

    response = client.invoke_endpoint(
        EndpointName=endpoint_name,
        ContentType="text/csv",
        Accept="application/json",
        Body=payload.encode("utf-8"),
    )

    body = json.loads(response["Body"].read().decode("utf-8"))
    predictions: list[dict] = body["predictions"]

    results: list[dict[str, Any]] = []
    for row, pred in zip(feature_rows, predictions):
        score = float(pred["score"])
        shap_raw: dict[str, float] = pred.get("shap", {})

        # Convert raw SHAP dict → sorted driver list matching the UI contract.
        shap_drivers = [
            {
                "feature":   feat,
                "label":     feat.replace("_", " ").replace("flag kw ", "").title(),
                "shap":      round(val, 4),
                "direction": "positive" if val > 0 else "negative",
            }
            for feat, val in sorted(shap_raw.items(), key=lambda kv: abs(kv[1]), reverse=True)
            if abs(val) > 0.005  # suppress near-zero contributors
        ][:5]  # top-5 drivers

        results.append({
            "osm_id":      row.get("osm_id", ""),
            "name":        row.get("name", ""),
            "risk_score":  round(score, 4),
            "risk_tier":   _tier(score),
            "shap_drivers": shap_drivers,
            "stub":        False,
        })

    return results
