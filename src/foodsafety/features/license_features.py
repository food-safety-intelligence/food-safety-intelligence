"""Static categorical features describing the facility itself.

These features don't change between an anchor's inspections — they're the
facility's "identity" as captured by Chicago's licensing data. Cheap to add,
no leak risk (the values come from columns set at license-issuance time).

For Phase 4 we use the values present in the inspections row itself; in
Phase 5 we'll prefer the values from the joined Business Licenses table
(authoritative), and add ``license_age_days`` and ``license_status``.
"""

from __future__ import annotations

import pandas as pd


def add_license_features(df: pd.DataFrame) -> pd.DataFrame:
    """Append static categorical features.

    Features added:
        static_facility_type   — Restaurant / Grocery Store / Bakery / etc.
        static_risk_tier       — Chicago's pre-assigned tier ("Risk 1 (High)" / 2 / 3)
        static_zip             — 5-digit ZIP
        static_zip3            — first 3 digits of ZIP. Less sparse than full
                                 ZIP; useful as a fallback when ZIP has few rows.
        static_inspection_type — scheduled inspection trigger (Canvass /
                                 Complaint / Re-Inspection / License). Known at
                                 scheduling time, before the outcome.

    All four are cast to pandas' nullable ``category`` dtype — XGBoost reads
    these natively, and scikit-learn pipelines can one-hot via
    ``OrdinalEncoder`` / ``OneHotEncoder``.
    """
    out = df.copy()

    out["static_facility_type"] = out["facility_type"].astype("string").astype("category")
    out["static_risk_tier"] = out["risk"].astype("string").astype("category")

    # The scheduled inspection trigger (Canvass / Complaint / Re-Inspection /
    # License). It's known when the visit is dispatched — before the outcome —
    # so it's leak-safe as an anchor categorical, same status as facility_type.
    # Absent in minimal test inputs → fall back to "Unknown".
    if "inspection_type" in out.columns:
        out["static_inspection_type"] = (
            out["inspection_type"].astype("string").fillna("Unknown").astype("category")
        )
    else:
        out["static_inspection_type"] = pd.Series("Unknown", index=out.index, dtype="category")

    # ZIP cleaning: cast to string, strip trailing decimals (some upstream
    # parquet round-trips can yield "60614.0"), then require an exact 5-digit
    # match. Short codes ("606") and missing values both become "" — we do NOT
    # zero-pad short codes, because "00606" isn't a real Chicago ZIP and the
    # padding would silently invent a value that doesn't exist.
    zip_clean = out["zip"].astype("string").fillna("").str.replace(r"\.0$", "", regex=True)
    zip_clean = zip_clean.where(zip_clean.str.match(r"^\d{5}$"), "")
    out["static_zip"] = zip_clean.astype("category")
    out["static_zip3"] = zip_clean.str.slice(0, 3).astype("category")

    return out
