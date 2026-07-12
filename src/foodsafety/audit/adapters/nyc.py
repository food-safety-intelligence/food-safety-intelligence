"""NYC adapter — reproduce the DOHMH test-split predictions into the AuditFrame.

NYC has its own bespoke pipeline (event-anchored "next inspection graded B/C"
label, 2022+ post-COVID window, its own feature build) living in
``scripts/build_nyc_scores.py``. To stay faithful and avoid drift, this adapter
**imports that script's functions** (``build_events`` / ``fit_xgb_platt`` /
``xgb_proba``) and replicates only the short train/split/predict glue from its
``main`` — it does not re-implement the feature build.

Differences from Chicago handled here: neighborhood = borough; facility type is a
constant (NYC data is restaurants only); tenure is derived from the first-seen
inspection date per establishment (no license history); cuisine comes from a
separate DOHMH ``cuisine_description`` pull, since the cached feed omits it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import requests

from foodsafety.audit import frame
from foodsafety.config import RAW_DIR
from foodsafety.io import cache, storage
from foodsafety.serve.predict_batch import assign_risk_tiers
from foodsafety.utils.time import temporal_split

_REPO_ROOT = Path(__file__).resolve().parents[4]
_NYC_SODA = "https://data.cityofnewyork.us/resource/43nn-pn8j.json"


def _nyc_build_module():
    """Import ``scripts/build_nyc_scores.py`` as a module (lazy, path-based)."""
    path = _REPO_ROOT / "scripts" / "build_nyc_scores.py"
    spec = importlib.util.spec_from_file_location("build_nyc_scores", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _pull_cuisine() -> pd.Series:
    """camis -> cuisine_description from DOHMH (distinct), cached under RAW_DIR."""

    def _fetch() -> pd.DataFrame:
        params = {
            "$select": "camis,cuisine_description",
            "$group": "camis,cuisine_description",
            "$limit": "200000",
        }
        resp = requests.get(_NYC_SODA, params=params, timeout=120)
        resp.raise_for_status()
        df = pd.DataFrame(resp.json())
        # One camis can carry more than one cuisine label over time; keep the first.
        df = df.dropna(subset=["camis"]).drop_duplicates("camis", keep="first")
        return df

    df = cache.load_or_fetch("nyc_cuisine", _fetch, cache_dir=storage.join(str(RAW_DIR)))
    return df.set_index(df["camis"].astype(str))["cuisine_description"]


class NycAdapter:
    """Builds the NYC ``AuditFrame`` by reproducing build_nyc_scores' test split."""

    city = "nyc"

    def build_audit_frame(self) -> pd.DataFrame:
        nyc = _nyc_build_module()
        ev, prior, current, _theme, _sev, _raw = nyc.build_events()
        feats_m1 = prior + current

        anch = ev[ev["next_score"].notna() & (ev["inspection_date"] >= nyc.NYC_TRAIN_START)].copy()
        sp = temporal_split(
            anch, date_col="inspection_date", train_end=nyc.TRAIN_END, val_end=nyc.VAL_END
        )
        xgb1, c1, i1 = nyc.fit_xgb_platt(sp.train, sp.val, feats_m1)
        xgb2, c2, i2 = nyc.fit_xgb_platt(sp.train, sp.val, prior, regularized=True)

        test = sp.test.reset_index(drop=True)
        p_test = nyc.xgb_proba(xgb1, c1, i1, test[feats_m1])
        forecast = nyc.xgb_proba(xgb2, c2, i2, test[prior])
        tiers, _ = assign_risk_tiers(pd.Series(p_test, index=test.index), nyc.NYC_BASE_RATE)

        # Tenure: age at the anchor from the establishment's first-seen inspection.
        first_seen = ev.groupby("camis")["inspection_date"].min()
        age_days = (test["inspection_date"] - test["camis"].map(first_seen)).dt.days

        cuisine = _pull_cuisine()

        # Neighborhood = borough; drop the handful of rows with a non-borough code.
        boro = test["boro"].astype("string").str.title()
        boro = boro.where(
            boro.isin(["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]), pd.NA
        )

        out = pd.DataFrame(
            {
                "city": "nyc",
                "license_id": test["license_id"].astype("string"),
                "as_of_date": pd.to_datetime(test["inspection_date"]),
                "y_true": test["y_next_bc"].astype("int8"),
                "y_score": p_test.astype("float64"),
                "risk_tier": tiers.astype("string"),
                "lat": pd.to_numeric(test["lat"], errors="coerce").astype("float64"),
                "lon": pd.to_numeric(test["lon"], errors="coerce").astype("float64"),
                # NYC data is restaurants only — a single facility group (won't audit).
                "facility_type_norm": pd.Series("Restaurant", index=test.index, dtype="string"),
                "license_age_days": age_days.astype("float64"),
                "neighborhood": boro,
                "cuisine": test["license_id"].astype(str).map(cuisine).astype("string"),
                "forecast_score": forecast.astype("float64"),
            }
        )
        out = frame.add_tenure_bucket(out)
        frame.validate(out)
        return out
