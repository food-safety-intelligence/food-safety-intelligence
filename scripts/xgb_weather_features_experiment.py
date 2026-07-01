"""NOAA / Open-Meteo daily temperature features — A/B experiment.

Motivated by the 2014 Chicago food-safety forecasting paper (Kang et al.),
which used a 3-day rolling high temperature as a predictor. This experiment
tests whether replacing the current month/quarter calendar proxies with
actual temperature data unlocks signal the proxies obscure.

Features tested (all computed from daily temperature at Chicago O'Hare,
via Open-Meteo historical archive — no API key required):

  weather_temp_max_f    Daily high (°F) on the inspection date. Heat drives
                        cold-chain failures; cold drives hot-holding failures.

  weather_temp_3d_max_f Rolling 3-day max temp ending on inspection date.
                        The exact feature from the 2014 paper.

  weather_hot_days_30d  Count of days with daily high > 86 °F (30 °C) in
                        the 30 days ending on the inspection date. Captures
                        cumulative heat-stress on refrigeration equipment.

  weather_temp_30d_mean_f  30-day rolling mean temp. Seasonal baseline that
                        is more precise than temporal_month/quarter (already
                        in the model) — tests whether continuous temperature
                        beats the calendar proxy.

Leak-free: temperature on and before the inspection date is known at
inspection time; the label window is strictly after it.

Temperature cache is written to data/interim/chicago_temperature.parquet
on first run and reused on subsequent runs (no re-fetch).

Protocol: single train→val A/B → 3-fold expanding-window CV on train-only
→ test evaluation vs same-run control (same gate as all prior experiments).

Run with:
    PYTHONPATH=src uv run python scripts/xgb_weather_features_experiment.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from foodsafety.config import (
    FEATURES_PATH,
    INTERIM_DIR,
    LABEL_WINDOW_DAYS,
    PROCESSED_DIR,
    RANDOM_STATE,
)
from foodsafety.io import storage
from foodsafety.models.baseline import ALL_FEATURES, LABEL_COL
from foodsafety.models.evaluate import evaluate
from foodsafety.models.xgb import (
    build_xgb_estimator,
    compute_scale_pos_weight,
    extract_categorical_dtypes,
    monotone_constraints_for,
    prepare_xgb_features,
)
from foodsafety.utils.time import expanding_year_folds, temporal_split

# Resolve features file — falls back to legacy flat path if versioned not present.
_FEATURES_FALLBACK = Path(str(PROCESSED_DIR)) / "features.parquet"
_RESOLVED_FEATURES_PATH = (
    str(FEATURES_PATH) if storage.exists(FEATURES_PATH) else str(_FEATURES_FALLBACK)
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports" / "metrics" / "experiments"
WEATHER_CACHE = Path(str(INTERIM_DIR)) / "chicago_temperature.parquet"

TRAIN_END = "2024-07-01"
VAL_END = "2025-07-01"

# Production baseline from xgb_monotone_sigmoid_20260627_ac236faed.json
PROD_TEST_PR_AUC = 0.382016
PROD_TEST_P10 = 0.415121

# Chicago O'Hare coordinates (GHCND station USW00094846).
CHICAGO_LAT = 41.9742
CHICAGO_LON = -87.9073

# Temperature thresholds (°F)
HOT_DAY_THRESHOLD_F = 86.0  # 30 °C — heat stress on refrigeration
COLD_DAY_THRESHOLD_F = 20.0  # -7 °C — extreme cold → hot-holding failures

WEATHER_FEATURES = [
    "weather_temp_max_f",
    "weather_temp_3d_max_f",
    "weather_hot_days_30d",
    "weather_temp_30d_mean_f",
]
ALL_FEATURES_WITH_WEATHER = list(ALL_FEATURES) + WEATHER_FEATURES


# ---------------------------------------------------------------------------
# Temperature data fetch + cache
# ---------------------------------------------------------------------------


def fetch_temperature(start_date: str, end_date: str) -> pd.DataFrame:
    """Download daily max/mean temperature for Chicago from Open-Meteo.

    Returns a DataFrame with columns: date (datetime64[ns]), temp_max_f,
    temp_mean_f.  Data comes from the ERA5 reanalysis matched to
    Chicago O'Hare coordinates — consistent with GHCND observations.
    """
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": CHICAGO_LAT,
        "longitude": CHICAGO_LON,
        "start_date": start_date,
        "end_date": end_date,
        "daily": "temperature_2m_max,temperature_2m_mean",
        "timezone": "America/Chicago",
        "temperature_unit": "fahrenheit",
    }
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()["daily"]
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(data["time"]),
            "temp_max_f": data["temperature_2m_max"],
            "temp_mean_f": data["temperature_2m_mean"],
        }
    )
    return df.astype({"temp_max_f": "float32", "temp_mean_f": "float32"})


def load_temperature(
    features_min_date: pd.Timestamp, features_max_date: pd.Timestamp
) -> pd.DataFrame:
    """Load temperature from cache, fetching if stale or absent.

    Extends the cache when the features data has grown past the cached end date.
    Always covers (features_min_date - 30d) through features_max_date so every
    rolling window is fully populated.
    """
    # Need 30 extra days before the first inspection for the rolling windows.
    need_start = (features_min_date - pd.Timedelta(days=31)).strftime("%Y-%m-%d")
    need_end = features_max_date.strftime("%Y-%m-%d")

    if WEATHER_CACHE.exists():
        cached = pd.read_parquet(WEATHER_CACHE)
        cached_start = cached["date"].min()
        cached_end = cached["date"].max()
        # Extend if the features set now has inspections past the cached tail.
        if cached_start <= pd.Timestamp(need_start) and cached_end >= pd.Timestamp(need_end):
            print(f"  Using cached temperature data ({cached_start.date()} → {cached_end.date()})")
            return cached

        print(
            f"  Cache covers {cached_start.date()}→{cached_end.date()}; need through {need_end} — extending"
        )
        extension = fetch_temperature(
            (cached_end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), need_end
        )
        df = pd.concat([cached, extension], ignore_index=True).drop_duplicates("date")
    else:
        print(f"  Fetching temperature data {need_start} → {need_end} from Open-Meteo")
        df = fetch_temperature(need_start, need_end)

    WEATHER_CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(WEATHER_CACHE, index=False)
    print(f"  Cached → {WEATHER_CACHE}  ({len(df):,} days)")
    return df


# ---------------------------------------------------------------------------
# Feature computation
# ---------------------------------------------------------------------------


def add_weather_features(inspections: pd.DataFrame, temp: pd.DataFrame) -> pd.DataFrame:
    """Join daily temperature to inspections and compute rolling weather features.

    All windows are left-inclusive of the inspection date (temperature is
    known on the day of the inspection — exogenous, no leak).
    """
    t = temp.set_index("date").sort_index()

    # Pre-compute rolling series aligned to the full temperature calendar.
    # Rolling is on the temperature index (one row per day), then we look up
    # each inspection's date.
    t["temp_3d_max_f"] = t["temp_max_f"].rolling(3, min_periods=1).max()
    t["hot_days_30d"] = (
        (t["temp_max_f"] > HOT_DAY_THRESHOLD_F).astype("float32").rolling(30, min_periods=1).sum()
    )
    t["temp_30d_mean_f"] = t["temp_mean_f"].rolling(30, min_periods=1).mean()

    out = inspections.copy()
    dates = pd.to_datetime(out["inspection_date"]).dt.normalize()

    out["weather_temp_max_f"] = dates.map(t["temp_max_f"]).astype("float32")
    out["weather_temp_3d_max_f"] = dates.map(t["temp_3d_max_f"]).astype("float32")
    out["weather_hot_days_30d"] = dates.map(t["hot_days_30d"]).astype("float32")
    out["weather_temp_30d_mean_f"] = dates.map(t["temp_30d_mean_f"]).astype("float32")

    n_missing = out["weather_temp_max_f"].isna().sum()
    if n_missing:
        print(
            f"  Warning: {n_missing:,} inspections have no temperature match (outside cache range)"
        )

    return out


# ---------------------------------------------------------------------------
# Model helpers (same production recipe as retrain_xgb_sigmoid.py)
# ---------------------------------------------------------------------------


def _build_xgb(features: list[str], spw: float):
    return build_xgb_estimator(
        n_estimators=300,
        max_depth=3,
        learning_rate=0.05,
        scale_pos_weight=spw,
        early_stopping_rounds=None,
        monotone_constraints=monotone_constraints_for(features),
    )


def _prepare(df: pd.DataFrame, features: list[str], cat_dtypes: dict | None = None):
    from foodsafety.models.baseline import BOOLEAN_FEATURES, CATEGORICAL_FEATURES

    cat_cols = [c for c in features if c in CATEGORICAL_FEATURES]
    bool_cols = [c for c in features if c in BOOLEAN_FEATURES]
    num_cols = [c for c in features if c not in cat_cols and c not in bool_cols]

    out = df[features].copy()
    for c in cat_cols:
        if cat_dtypes and c in cat_dtypes:
            out[c] = out[c].astype("category").cat.set_categories(cat_dtypes[c].categories)
        else:
            out[c] = out[c].astype("category")
    for c in bool_cols:
        out[c] = out[c].astype("int8")
    for c in num_cols:
        out[c] = out[c].astype("float32")
    return out


def _cv_pr_auc(df: pd.DataFrame, features: list[str], folds) -> list[float]:
    scores = []
    for train_idx, val_idx in folds:
        fold_tr = df.iloc[train_idx].reset_index(drop=True)
        fold_vl = df.iloc[val_idx].reset_index(drop=True)
        y_tr = fold_tr[LABEL_COL].astype(int).to_numpy()
        y_vl = fold_vl[LABEL_COL].astype(int).to_numpy()
        if y_tr.sum() == 0 or y_vl.sum() == 0:
            continue
        spw = compute_scale_pos_weight(y_tr)
        X_tr = _prepare(fold_tr, features)
        cat_dt = {c: X_tr[c].dtype for c in features if hasattr(X_tr[c], "cat")}
        X_vl = _prepare(fold_vl, features, cat_dt)
        est = _build_xgb(features, spw)
        est.fit(X_tr, y_tr, verbose=False)
        p = est.predict_proba(X_vl)[:, 1]
        scores.append(evaluate(y_vl, p).pr_auc)
    return scores


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print(f"Loading {_RESOLVED_FEATURES_PATH}")
    raw = storage.read_parquet(_RESOLVED_FEATURES_PATH)
    print(f"  shape: {raw.shape}")

    if "right_truncated" in raw.columns:
        n_before = len(raw)
        raw = raw.loc[~raw["right_truncated"]].reset_index(drop=True)
        print(f"  dropped {n_before - len(raw):,} right-truncated rows → {len(raw):,}")

    # Load / fetch temperature data.
    dates = pd.to_datetime(raw["inspection_date"])
    temp = load_temperature(dates.min(), dates.max())

    # Join temperature features.
    features_df = add_weather_features(raw, temp)

    split = temporal_split(features_df, train_end=TRAIN_END, val_end=VAL_END)
    print(f"  train={len(split.train):,}  val={len(split.val):,}  test={len(split.test):,}")

    # -------------------------------------------------------------------
    # Univariate sanity check
    # -------------------------------------------------------------------
    print("\n--- Univariate sanity check (train split) ---")
    label = split.train[LABEL_COL]
    for feat in WEATHER_FEATURES:
        col = split.train[feat]
        pos_med = col[label == 1].median()
        neg_med = col[label == 0].median()
        nan_pct = col.isna().mean() * 100
        ratio = pos_med / neg_med if neg_med and neg_med != 0 else float("nan")
        print(
            f"  {feat}: pos_median={pos_med:.1f}  neg_median={neg_med:.1f}  ratio={ratio:.3f}x  NaN={nan_pct:.1f}%"
        )

    y_train = split.train[LABEL_COL].astype(int).to_numpy()
    y_val = split.val[LABEL_COL].astype(int).to_numpy()
    y_test = split.test[LABEL_COL].astype(int).to_numpy()
    spw = compute_scale_pos_weight(y_train)

    # -------------------------------------------------------------------
    # Pass 1: single train→val A/B
    # -------------------------------------------------------------------
    print("\n--- Pass 1: single train→val A/B ---")

    X_tr_ctrl = prepare_xgb_features(split.train[ALL_FEATURES])
    cat_dtypes_ctrl = extract_categorical_dtypes(X_tr_ctrl)
    X_val_ctrl = prepare_xgb_features(split.val[ALL_FEATURES], categorical_dtypes=cat_dtypes_ctrl)
    X_test_ctrl = prepare_xgb_features(split.test[ALL_FEATURES], categorical_dtypes=cat_dtypes_ctrl)

    est_ctrl = _build_xgb(list(ALL_FEATURES), spw)
    est_ctrl.fit(X_tr_ctrl, y_train, verbose=False)
    p_val_ctrl = est_ctrl.predict_proba(X_val_ctrl)[:, 1]
    val_ctrl = evaluate(y_val, p_val_ctrl)
    print(f"  Control   — val PR-AUC={val_ctrl.pr_auc:.4f}  P@10={val_ctrl.precision_at_10pct:.4f}")

    X_tr_cand = _prepare(split.train, ALL_FEATURES_WITH_WEATHER)
    cat_dtypes_cand = {
        c: X_tr_cand[c].dtype for c in ALL_FEATURES_WITH_WEATHER if hasattr(X_tr_cand[c], "cat")
    }
    X_val_cand = _prepare(split.val, ALL_FEATURES_WITH_WEATHER, cat_dtypes_cand)
    X_test_cand = _prepare(split.test, ALL_FEATURES_WITH_WEATHER, cat_dtypes_cand)

    est_cand = _build_xgb(ALL_FEATURES_WITH_WEATHER, spw)
    est_cand.fit(X_tr_cand, y_train, verbose=False)
    p_val_cand = est_cand.predict_proba(X_val_cand)[:, 1]
    val_cand = evaluate(y_val, p_val_cand)
    print(f"  +weather  — val PR-AUC={val_cand.pr_auc:.4f}  P@10={val_cand.precision_at_10pct:.4f}")
    print(
        f"  Delta     — ΔPR-AUC={val_cand.pr_auc - val_ctrl.pr_auc:+.4f}"
        f"  ΔP@10={val_cand.precision_at_10pct - val_ctrl.precision_at_10pct:+.4f}"
    )

    # -------------------------------------------------------------------
    # Pass 2: 3-fold expanding-window CV on train-only
    # -------------------------------------------------------------------
    all_folds = expanding_year_folds(split.train.reset_index(drop=True))
    recent_folds = all_folds[-3:] if len(all_folds) >= 3 else all_folds
    print(f"\n--- Pass 2: {len(recent_folds)}-fold CV on train-only ---")

    train_df = split.train.reset_index(drop=True)
    cv_ctrl = _cv_pr_auc(train_df, list(ALL_FEATURES), recent_folds)
    cv_cand = _cv_pr_auc(train_df, ALL_FEATURES_WITH_WEATHER, recent_folds)
    cv_deltas = [c - b for c, b in zip(cv_cand, cv_ctrl, strict=True)]
    cv_wins = sum(d > 0 for d in cv_deltas)

    print(f"  Control   per-fold: {[round(s, 4) for s in cv_ctrl]}  mean={np.mean(cv_ctrl):.4f}")
    print(f"  +weather  per-fold: {[round(s, 4) for s in cv_cand]}  mean={np.mean(cv_cand):.4f}")
    print(
        f"  Δ per-fold:         {[round(d, 4) for d in cv_deltas]}  mean={np.mean(cv_deltas):+.4f}"
    )
    print(f"  Candidate wins {cv_wins}/{len(recent_folds)} folds on PR-AUC")

    # -------------------------------------------------------------------
    # Pass 3: test evaluation
    # -------------------------------------------------------------------
    print("\n--- Pass 3: test evaluation ---")
    p_test_ctrl = est_ctrl.predict_proba(X_test_ctrl)[:, 1]
    p_test_cand = est_cand.predict_proba(X_test_cand)[:, 1]
    test_ctrl = evaluate(y_test, p_test_ctrl)
    test_cand = evaluate(y_test, p_test_cand)

    delta_pr = test_cand.pr_auc - test_ctrl.pr_auc
    delta_p10 = test_cand.precision_at_10pct - test_ctrl.precision_at_10pct

    print(f"\n=== A/B vs same-run control (test n={len(y_test):,}, base={y_test.mean():.3f}) ===")
    print("                  PR-AUC    P@10     ROC-AUC  Lift@10")
    print(
        f"  Control:       {test_ctrl.pr_auc:.4f}   "
        f"{test_ctrl.precision_at_10pct:.4f}   "
        f"{test_ctrl.roc_auc:.4f}   "
        f"{test_ctrl.top_decile_lift:.3f}"
    )
    print(
        f"  +weather:      {test_cand.pr_auc:.4f}   "
        f"{test_cand.precision_at_10pct:.4f}   "
        f"{test_cand.roc_auc:.4f}   "
        f"{test_cand.top_decile_lift:.3f}"
    )
    print(f"  Delta:         {delta_pr:+.4f}   {delta_p10:+.4f}")

    beats_pr = delta_pr > 0
    beats_p10 = delta_p10 > 0
    gate = "PASS" if beats_pr and beats_p10 else "FAIL"
    print(
        f"\nBoth-metrics gate: {gate}  "
        f"(PR-AUC {'↑' if beats_pr else '↓'}, P@10 {'↑' if beats_p10 else '↓'})"
    )

    # XGBoost feature gain for the weather columns
    booster = est_cand.get_booster()
    gain = booster.get_score(importance_type="gain")
    gain_sorted = sorted(gain.items(), key=lambda x: x[1], reverse=True)
    print("\nWeather feature gains (rank out of all features):")
    for feat in WEATHER_FEATURES:
        g = gain.get(feat, 0.0)
        rank = next((i + 1 for i, (k, _) in enumerate(gain_sorted) if k == feat), "—")
        print(f"  {feat}: gain={g:.2f}  rank={rank}/{len(gain)}")

    # -------------------------------------------------------------------
    # Save report
    # -------------------------------------------------------------------
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "experiment": "xgb_weather_features",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "label_window_days": LABEL_WINDOW_DAYS,
        "random_state": RANDOM_STATE,
        "train_end": TRAIN_END,
        "val_end": VAL_END,
        "weather_source": "Open-Meteo historical archive (ERA5 reanalysis, Chicago O'Hare coords)",
        "new_features": WEATHER_FEATURES,
        "hot_day_threshold_f": HOT_DAY_THRESHOLD_F,
        "n_features_control": len(ALL_FEATURES),
        "n_features_candidate": len(ALL_FEATURES_WITH_WEATHER),
        "production_baseline_stored": {"test_pr_auc": PROD_TEST_PR_AUC, "test_p10": PROD_TEST_P10},
        "val": {
            "control": {
                "pr_auc": round(val_ctrl.pr_auc, 6),
                "p10": round(val_ctrl.precision_at_10pct, 6),
            },
            "candidate": {
                "pr_auc": round(val_cand.pr_auc, 6),
                "p10": round(val_cand.precision_at_10pct, 6),
            },
            "delta_pr_auc": round(val_cand.pr_auc - val_ctrl.pr_auc, 6),
            "delta_p10": round(val_cand.precision_at_10pct - val_ctrl.precision_at_10pct, 6),
        },
        "cv": {
            "n_folds": len(recent_folds),
            "control_per_fold": [round(s, 6) for s in cv_ctrl],
            "candidate_per_fold": [round(s, 6) for s in cv_cand],
            "deltas_per_fold": [round(d, 6) for d in cv_deltas],
            "mean_delta": round(float(np.mean(cv_deltas)), 6),
            "wins": f"{cv_wins}/{len(recent_folds)}",
        },
        "test": {
            "control": test_ctrl.to_dict(),
            "candidate": test_cand.to_dict(),
            "delta_pr_auc": round(delta_pr, 6),
            "delta_p10": round(delta_p10, 6),
        },
        "both_metrics_gate": gate,
        "weather_feature_gain": {f: round(gain.get(f, 0.0), 4) for f in WEATHER_FEATURES},
    }
    report_path = REPORTS_DIR / f"xgb_weather_features_{ts}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nSaved report → {report_path}")


if __name__ == "__main__":
    main()
