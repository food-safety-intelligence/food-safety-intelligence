# Interface Contracts

The three parquet files below are the **only cross-team artifacts**. Treat
their schemas as contracts — schema changes need a PR tagging every owner
(Arun, Bella, Deepak, Aurelia, Jun) before any downstream code is touched.

This doc is source of truth. CLAUDE.md has a one-line summary table; this is
the full schema.

---

## 1. `data/processed/inspections_labeled.parquet`

**Grain**: one row per inspection.
**Key**: `(license_id, inspection_date)`.
**Producer**: `src/foodsafety/data/labels.py` (Arun).
**Consumers**: feature builders, EDA notebooks.

| Column | dtype | Nullable | Description |
|---|---|---|---|
| `inspection_id` | `Int64` | no | Chicago's inspection identifier. |
| `license_id` | `string` | no | The restaurant's license number. Joins to Business Licenses on `license_number`. Drop rows where this is `"0"` or empty before joining. |
| `inspection_date` | `datetime64[ns]` | no | Date the inspection occurred. |
| `dba_name` | `string` | yes | "Doing business as" name, for display. |
| `aka_name` | `string` | yes | Alternate name. |
| `facility_type` | `string` | yes | Restaurant / Grocery Store / Bakery / etc. |
| `risk` | `string` | yes | Chicago's pre-assigned risk tier ("Risk 1 (High)" / 2 / 3). |
| `address` | `string` | yes | Street address. |
| `zip` | `string` | yes | 5-digit ZIP. |
| `latitude` | `float64` | yes | WGS84 lat. |
| `longitude` | `float64` | yes | WGS84 lon. |
| `inspection_type` | `string` | yes | Canvass / Complaint / License / Re-Inspection / etc. |
| `results` | `string` | no | Pass / Pass w/ Conditions / Fail / Out of Business / No Entry / Not Ready / Business Not Located. |
| `violations` | `string` | yes | `\|`-separated free-text. Each chunk prefixed with a numbered code (1–29 = priority/critical, 30+ = core). |
| `is_burnin` | `bool` | no | `True` for inspections before `TRAIN_START_DATE` (2019-01-01). Used to compute `prior_*` features but NEVER for training. |
| `y_fail_or_critical_next_180d` | `Int8` | no on non-burnin rows | The label. `1` if any inspection within `(inspection_date, inspection_date + 180d]` has `results == "Fail"` OR contains a priority violation. `0` otherwise. **`NULL` on burn-in rows** because we don't compute labels for them. |

**Notes**:
- Only `results in {"Pass", "Pass w/ Conditions", "Fail"}` are modelable.
  Operational non-outcomes (Out of Business, No Entry, etc.) appear in the
  table but are dropped during feature construction.
- The label's 180-day window is right-exclusive of the anchor inspection
  itself — we predict what happens *after* this visit, not on it.

---

## 2. `data/processed/features.parquet`

**Grain**: one row per `(license_id, as_of_date)`.
**Key**: `(license_id, as_of_date)`.
**Producer**: `src/foodsafety/features/build.py` (Bella + Deepak).
**Consumers**: model training, batch scoring.

`as_of_date` is one row per inspection in the MVP — `as_of_date =
inspection_date` is set as a synonym in `features/build.py`. The Phase-4
design called for per-restaurant-per-day rolling (`as_of_date =
inspection_date + 1d`); that's the target but is **not** what currently
ships. `scores.parquet` uses the latest inspection per license as its
anchor; the modeling parquet keeps all inspections so chronological eval
splits remain honest. Switching to daily rolling is a build-step change,
not a contract change.

| Column | dtype | Nullable | Description |
|---|---|---|---|
| `license_id` | `string` | no | Same as inspections_labeled. |
| `as_of_date` | `datetime64[ns]` | no | The "predict-as-of" date. All features must be computable using only data with `event_date < as_of_date`. |
| `prior_*` features | various | varies | **MUST use `.shift()` or `event_date < as_of_date` guards.** Examples below. |
| `static_*` features | various | varies | Facility-level constants that don't change over time (facility_type, risk tier, zip). |

**Required `prior_*` features** (canonical 26-feature contract — single
source of truth is `src/foodsafety/models/baseline.py::ALL_FEATURES`):

| Column | dtype | Description |
|---|---|---|
| `prior_inspections` | `int` | Number of inspections at this license strictly before `as_of_date`. |
| `prior_fails` | `int` | Number of `Fail` results strictly before `as_of_date`. |
| `prior_priority_violations` | `int` | Number of priority (code 1–29) violations strictly before `as_of_date`. |
| `prior_core_violations` | `int` | Number of core (code 30+) violations strictly before `as_of_date`. |
| `prior_fail_or_priority_events` | `int` | Combined count of failed inspections OR inspections with any priority violation, strictly before `as_of_date`. |
| `days_since_last_inspection` | `float` | Days from most recent prior inspection to `as_of_date`. NaN if none. |
| `days_since_last_fail` | `float` | Days from most recent prior `Fail` to `as_of_date`. NaN if none. |

Note: `prior_fail_rate` / `prior_fail_rate_2y` ratio features were dropped
in Phase 5 — tree models can reconstruct ratios from numerator + denominator
and the ratios added noise without orthogonal signal.

**Required `static_*` features**:

| Column | dtype | Description |
|---|---|---|
| `static_facility_type` | `category` | e.g. "Restaurant", "Grocery Store". |
| `static_risk_tier` | `category` | Chicago's "Risk 1 (High)" / 2 / 3. |
| `static_zip` | `category` | 5-digit ZIP. |

Note: `static_zip3` was dropped — strict subset of `static_zip` with no
orthogonal information.

**Required temporal features**:

| Column | dtype | Description |
|---|---|---|
| `temporal_month` | `int` | Month 1–12 of `inspection_date`. |
| `temporal_quarter` | `int` | Quarter 1–4 of `inspection_date`. |

Note: `temporal_year` is excluded — it's time-anchored and doesn't
generalise across the chronological train/test split. `temporal_dow` and
`temporal_season` were dropped per Phase 5 ablation.

**Required license-history features**:

| Column | dtype | Description |
|---|---|---|
| `license_age_days` | `int` | Days between this license's first issuance and `as_of_date`. |
| `license_n_history_rows` | `int` | Count of rows in licenses_historical for this license, strictly before `as_of_date`. |

**Required keyword-flag features (Phase 4, hybrid NLP layer B)**:

`flag_kw_*` boolean columns from regex matching the residual `violations` text,
after stripping the numbered codes. The exact keyword list lives in
`src/foodsafety/features/keyword_flags.py`. Expected ~20 flags, e.g.:
`flag_kw_temperature`, `flag_kw_rodent`, `flag_kw_raw_chicken`,
`flag_kw_no_soap`, `flag_kw_expired`, `flag_kw_cross_contamination`.

**311 spatial complaint features**: dropped from the production contract.
The Phase-5 ablation showed `n_311_*` features sat at the bottom of XGBoost
gain — violation-text keyword flags (`flag_kw_rodent`, `flag_kw_pest`,
`flag_kw_sewage`) capture the same signal directly, with cleaner SHAP
attribution. The CMU 2019 hindsight critique of Chicago's heat-map
features reached the same conclusion. The BallTree code in
`features/complaint_features.py` remains; it's just not wired into the
build by default.

**Optional (Phase 6, NLP layer C)**:

`tfidf_svd_*` — 50 columns of TruncatedSVD-reduced TF-IDF features on residual
violation text. Only added if Phase 6 has slack.

---

## 3. `data/predictions/scores.parquet`

**Grain**: one row per `(license_id, as_of_date)`. The app reads the latest
`as_of_date` per license for the current view, and earlier dates for the
trend chart.
**Key**: `(license_id, as_of_date)`.
**Producer**: `src/foodsafety/serve/predict_batch.py` (Bella).
**Consumer**: the Next.js web app, via the exported `app/public/data/scores.json`.

This is the Python pipeline artifact; it is exported to
`app/public/data/scores.json`, which the Next.js web app reads. **No live
model inference happens in the app** — predictions are precomputed and written here.

| Column | dtype | Nullable | Description |
|---|---|---|---|
| `license_id` | `string` | no | The restaurant's license number. |
| `dba_name` | `string` | no | For display + search. |
| `address` | `string` | yes | For display. |
| `lat` | `float64` | yes | For the map. Null if no geocode. |
| `lon` | `float64` | yes | For the map. Null if no geocode. |
| `as_of_date` | `datetime64[ns]` | no | Date the prediction is anchored to. |
| `risk_score` | `float64` | no | Model output in `[0, 1]`. The sentinel value `-1.0` means "stub / mock" — the app MUST detect this and show the yellow demo-data banner. |
| `risk_tier` | `string` | no | `Low` / `Moderate` / `Elevated` / `High`. Discretized from `risk_score` via thresholds in `src/foodsafety/serve/predict_batch.py`. |
| `top_drivers` | `list[struct]` | no | 3–5 top SHAP-style drivers. Each struct: `{feature: string, value: string, shap: float, label: string}` where `label` is the plain-English UI string. |
| `trend_slope_90d` | `float64` | yes | OLS slope of `risk_score` over the last 90 days at this license. Positive = worsening. Null if <2 prior dates. |

**Risk-tier thresholds** (recalibrated in Phase 6 against the actual score distribution):

| Score range | Tier | Approx population share |
|---|---|---|
| `[0.00, 0.04)` | Low | ~25% |
| `[0.04, 0.13)` | Moderate | ~62% |
| `[0.13, 0.30)` | Elevated | ~11% |
| `[0.30, 1.00]` | High | ~1% |

Note: the mock fixture (`tests/fixtures/scores_mock.parquet`) still uses
the original (0.20 / 0.40 / 0.65) thresholds — those were appropriate for
uniformly-distributed synthetic scores. Real calibrated probabilities from
the model are much more concentrated near zero (median ~0.06, p95 ~0.18),
so the production thresholds were recalibrated to produce a useful UI
distribution. Single source of truth: ``RISK_TIER_THRESHOLDS`` in
``src/foodsafety/serve/predict_batch.py``.

**Mock fixture**: `tests/fixtures/scores_mock.parquet` conforms to this schema
and is used by the UI team in Phase 1 (walking skeleton) before the real
model lands. It contains `risk_score` values in `[0, 1]` but each row also
has a `_is_mock = True` flag the app can use to render the banner. The real
production `scores.parquet` will NOT include this column.

---

## Schema enforcement

`tests/test_contracts.py` (Phase 6) will validate each parquet against the
schema above on every CI run. Until that test lands, schema breakage is
caught by the consumers crashing — which is fast, just not friendly.

To add a column: open a PR with the schema change in this doc PLUS the
producer code PLUS at least one consumer update. Reviewers check the
contract diff in this file as the first thing.

To remove or rename a column: open a PR, tag every owner, do not merge
without explicit ack from each affected consumer.
