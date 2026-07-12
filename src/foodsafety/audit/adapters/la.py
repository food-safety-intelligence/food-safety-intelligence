"""LA adapter — reproduce the LA County test-split predictions into the AuditFrame.

Like NYC, LA has its own bespoke pipeline in ``scripts/build_la_scores.py``
(event-anchored "next inspection graded below 90" label, 2023+ window, violations
joined on serial number). This adapter imports that script's functions
(``build_raw`` / ``build_events`` / ``fit_xgb_platt`` / ``xgb_proba`` /
``load_facility_coords``) and replicates only the split → fit → predict glue.

LA specifics: the feed carries no coordinates, so lat/lon come from the committed
geocode cache (``reference/la_facility_coords.csv``, with a zip-centroid fallback
that makes some points coarse); neighborhood = ZIP; facility type is constant
(program element is not carried into the feature frame); LA has no cuisine field,
so that axis is null here (OSM-derived cuisine is a documented later refinement).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd

from foodsafety.audit import frame
from foodsafety.serve.predict_batch import assign_risk_tiers
from foodsafety.utils.time import temporal_split

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _la_build_module():
    """Import ``scripts/build_la_scores.py`` as a module (lazy, path-based)."""
    path = _REPO_ROOT / "scripts" / "build_la_scores.py"
    spec = importlib.util.spec_from_file_location("build_la_scores", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class LaAdapter:
    """Builds the LA ``AuditFrame`` by reproducing build_la_scores' test split."""

    city = "la"

    def build_audit_frame(self) -> pd.DataFrame:
        la = _la_build_module()
        raw = la.build_raw()
        ev, prior, current, _theme, _sev = la.build_events(raw)
        feats_m1 = prior + current

        anch = ev[ev["next_score"].notna() & (ev["inspection_date"] >= la.LA_TRAIN_START)].copy()
        sp = temporal_split(
            anch, date_col="inspection_date", train_end=la.TRAIN_END, val_end=la.VAL_END
        )
        xgb1, c1, i1 = la.fit_xgb_platt(sp.train, sp.val, feats_m1)
        xgb2, c2, i2 = la.fit_xgb_platt(sp.train, sp.val, prior, regularized=True)

        test = sp.test.reset_index(drop=True)
        p_test = la.xgb_proba(xgb1, c1, i1, test[feats_m1])
        forecast = la.xgb_proba(xgb2, c2, i2, test[prior])
        tiers, _ = assign_risk_tiers(pd.Series(p_test, index=test.index), la.LA_BASE_RATE)

        # Coordinates from the committed geocode cache (zip-centroid fallback).
        fac = test[["facility_id", "address", "city", "zip"]].drop_duplicates("facility_id").copy()
        fac["state"] = "CA"
        coords = la.load_facility_coords(fac)[["facility_id", "lat", "lon"]].copy()
        coords["facility_id"] = coords["facility_id"].astype(str)
        coords = coords.drop_duplicates("facility_id").set_index("facility_id")
        fid = test["facility_id"].astype(str)
        lat = fid.map(coords["lat"])
        lon = fid.map(coords["lon"])

        # Tenure: age at the anchor from the facility's first-seen inspection.
        first_seen = ev.groupby("facility_id")["inspection_date"].min()
        age_days = (test["inspection_date"] - test["facility_id"].map(first_seen)).dt.days

        out = pd.DataFrame(
            {
                "city": "la",
                "license_id": test["license_id"].astype("string"),
                "as_of_date": pd.to_datetime(test["inspection_date"]),
                "y_true": test["y_next_bad"].astype("int8"),
                "y_score": p_test.astype("float64"),
                "risk_tier": tiers.astype("string"),
                "lat": pd.to_numeric(lat, errors="coerce").astype("float64"),
                "lon": pd.to_numeric(lon, errors="coerce").astype("float64"),
                # Program element is not carried into the feature frame — single group.
                "facility_type_norm": pd.Series(
                    "Restaurant/Market", index=test.index, dtype="string"
                ),
                "license_age_days": age_days.astype("float64"),
                "neighborhood": test["zip"].astype("string"),
                "cuisine": pd.Series(pd.NA, index=test.index, dtype="string"),
                "forecast_score": forecast.astype("float64"),
            }
        )
        out = frame.add_tenure_bucket(out)
        frame.validate(out)
        return out
