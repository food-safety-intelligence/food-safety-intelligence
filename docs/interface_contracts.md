# Interface Contracts

The three parquet files below are the **only cross-team artifacts**. Treat
their schemas as contracts — schema changes need a PR tagging every owner
(Arun, Bella, Deepak, Aurelia, Jun) before any downstream code is touched.

This doc is source of truth. CLAUDE.md has a one-line summary table; this is
the full schema.

---

## Data cleaning & the train/val/test split

The cleaning and split are implemented across the loader, `labels.py`,
`build.py`, and `utils/time.py`; this is the single place that describes them.

### Split — chronological, never shuffled
`src/foodsafety/utils/time.py::temporal_split` (cutoffs are recorded in each
model's `metadata.json`):
- **train**: `inspection_date < 2024-07-01`
- **val** (calibration / early stopping): `2024-07-01 ≤ date < 2025-07-01`
- **test** (time-held-out): `date ≥ 2025-07-01`

Boundaries are right-exclusive. **Never** `train_test_split(shuffle=True)` — a
shuffle would leak the future into the past. Cross-validation uses
`expanding_year_folds` (full-year expanding windows + a 180-day embargo); see
decision 0002.

### Cleaning (where each step lives)
- **Dedup** — at fetch (`io/soda.py`, on `inspection_id`); the raw snapshot has
  0 duplicate ids.
- **`license_id`** — `license_` → `license_id`, `fillna("")`→str; placeholder
  tokens `""` / `"0"` get a NULL label and are dropped in `build.py`.
- **Results filter** — only `{Pass, Pass w/ Conditions, Fail}` are modelable; the
  4 operational non-outcomes (Out of Business, No Entry, Not Ready, Business Not
  Located) are dropped during feature build.
- **Burn-in** — inspections before 2019-01-01 are kept to seed `prior_*` history
  but get a NULL label and are excluded from train/test.
- **Right-truncation** — anchors whose 180-day forward window runs past the
  snapshot's max date are flagged (`right_truncated`) and dropped from honest
  train/test (their labels are under-counted).
- **Dates** — coerced to datetime (`errors="coerce"` where the source is dirty).
- **ZIP** — strip trailing `.0`, require exactly 5 digits else `""` (short codes
  are not zero-padded — `00606` isn't a real ZIP). `static_zip` is dropped from
  the model but still cleaned for the fairness audit.
- **Geo** — lat/lon coerced to numeric; 311 rows without geo are dropped before
  the spatial join. Inspection coords outside the Chicago bbox are flagged and
  **nulled** (the row is kept, not dropped — it's routed into the existing
  missing-geo path: the map skips the pin, the 311 join counts 0). lat/lon are
  **not** model features (they drive only the map and the 311 join); the current
  snapshot is 100% in-bbox, so this is defensive for future ingestion.

### Nulls
`prior_*` / recency / `license_*` NaNs are **structural** ("no prior history
yet" — e.g. `days_since_last_fail` is NaN for ~29% that never failed,
`license_age_days` ~20% not in the license-history table), not dirty data:
XGBoost reads NaN natively; the LogReg pipeline median-imputes numerics. The
**label has 0 nulls** in the modeling set (burn-in/invalid already dropped). Raw
`violations` is ~28% null — those are clean Pass inspections with nothing cited.

### Known cleanup TODO
`facility_type` has ~250 distinct raw values (a casing/typo/variant tail). It is
**not** a model feature (`static_facility_type` was dropped for fairness), but
normalizing it to canonical buckets would sharpen the group-performance fairness
audit and the UI display.

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

**Required `prior_*` features** (part of the canonical **36-feature** contract —
single source of truth is `src/foodsafety/models/baseline.py::ALL_FEATURES`. The
feature-refresh added the recency/trend rows below and **dropped
`static_facility_type` + `static_zip` from the model feature set** on fairness +
accuracy grounds — see decision record 0004. Those two columns remain in the
parquet but are no longer consumed by the model. The current-inspection outcome
block below took the contract 33→36):

| Column | dtype | Description |
|---|---|---|
| `prior_inspections` | `int` | Number of inspections at this license strictly before `as_of_date`. |
| `prior_fails` | `int` | Number of `Fail` results strictly before `as_of_date`. |
| `prior_priority_violations` | `int` | Number of priority (code 1–29) violations strictly before `as_of_date`. |
| `prior_core_violations` | `int` | Number of core (code 30+) violations strictly before `as_of_date`. |
| `prior_fail_or_priority_events` | `int` | Combined count of failed inspections OR inspections with any priority violation, strictly before `as_of_date`. |
| `prior_pass_w_conditions` | `int` | Count of prior "Pass w/ Conditions" results (near-miss signal), strictly before `as_of_date`. |
| `prior_reinspections` | `int` | Count of prior Re-Inspection visits, strictly before `as_of_date`. |
| `prior_complaint_inspections` | `int` | Count of prior Complaint-triggered visits, strictly before `as_of_date`. |
| `days_since_last_inspection` | `float` | Days from most recent prior inspection to `as_of_date`. NaN if none. |
| `days_since_last_fail` | `float` | Days from most recent prior `Fail` to `as_of_date`. NaN if none. |
| `last_was_fail` | `float` | 1/0 — was the immediately previous inspection a `Fail`. NaN if first. |
| `prev_priority_violations` | `float` | Priority-violation count at the previous inspection. NaN if first. |
| `priority_violation_trend` | `float` | Previous minus prev-prev priority count (worsening if > 0). |
| `prior_fails_365d` | `float` | `Fail` count in the trailing 365 days (leak-free, exclusive). |
| `prior_priority_violations_365d` | `float` | Priority-violation count in the trailing 365 days (leak-free). |

Note: `prior_fail_rate` / `prior_fail_rate_2y` ratio features were dropped
in Phase 5 — tree models can reconstruct ratios from numerator + denominator
and the ratios added noise without orthogonal signal.

**Required current-inspection outcome features** (the anchor inspection's OWN
result + violation-code counts — *not* `prior_*`. Leak-free because the 180-day
label window is strictly **after** `as_of_date`, so the anchor's own outcome
cannot leak its own forward label):

| Column | dtype | Description |
|---|---|---|
| `was_fail` | `int` | Was THIS inspection a `Fail` (1/0). |
| `n_priority_this_inspection` | `int` | Priority (code 1–29) violation count on THIS inspection. |
| `n_core_this_inspection` | `int` | Core (code 30+) violation count on THIS inspection. |

Note: with these added, the model's flagged top decile becomes ~91%
recently-failed restaurants (a Fail triggers a mandated re-inspection that often
lands in the window). That is legitimate forward risk but must be surfaced as
"recently failed" in the UI — see decision record 0005 (principle 6) for the
ethics review and the re-inspection feedback-loop disclosure.

**Required `static_*` features**:

| Column | dtype | Description |
|---|---|---|
| `static_risk_tier` | `category` | Chicago's "Risk 1 (High)" / 2 / 3. **Model feature.** |
| `static_inspection_type` | `category` | Canvass / Complaint / Re-Inspection / License — the visit trigger, known before the outcome (leak-safe). **Model feature.** |
| `static_facility_type` | `category` | e.g. "Restaurant", "Grocery Store". In the parquet but **dropped from the model** (DR 0004). |
| `static_zip` | `category` | 5-digit ZIP. In the parquet but **dropped from the model** (DR 0004). |

Note: `static_zip3` was dropped — strict subset of `static_zip` with no
orthogonal information. `static_facility_type` and `static_zip` were dropped
from the **model feature set** in the feature-refresh (decision record 0004) —
geographic/business-type proxies that added ~no accuracy (`static_zip` actually
overfit the chronological split); the columns remain in the parquet but the
model no longer consumes them. `static_risk_tier` (and `static_inspection_type`)
remain.

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
after stripping the numbered codes. Source of truth for the list is
`src/foodsafety/features/keyword_flags.py`. There are **12** flags:
`flag_kw_temperature`, `flag_kw_cooling`, `flag_kw_raw_food`,
`flag_kw_cross_contamination`, `flag_kw_expired`, `flag_kw_rodent`,
`flag_kw_pest`, `flag_kw_no_soap`, `flag_kw_no_paper_towels`,
`flag_kw_handwash_sink`, `flag_kw_sewage`, `flag_kw_certified_manager`.

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

### Feature contract changelog

This tracks **contract version bumps** only. The full experiment history — including
the experiments that came up flat and were reverted — is in
[`docs/experiments.md`](experiments.md). Impact below is on the **served** basis
(baseline LogReg + sigmoid, review-time-filtered) unless noted; exact run metrics live
in `reports/metrics/`.

| Version | PR | Added | Removed | Impact | Decision |
|---|---|---|---|---|---|
| 26 | #7 | baseline contract | — | reference | — |
| 30 | #8 | `prior_pass_w_conditions`, `prior_reinspections`, `prior_complaint_inspections`, `static_inspection_type` (visit-trigger + near-miss priors) | — | incremental over 26 (served settled at PR-AUC ≈0.3147; exact 26→30 delta blurred by a concurrent data refresh) | — |
| 33 | #10 | `last_was_fail`, `prev_priority_violations`, `priority_violation_trend`, `prior_fails_365d`, `prior_priority_violations_365d` (recency/trend) | `static_zip`, `static_facility_type` (fairness proxies) | served PR-AUC 0.3147→0.3246, precision@10% 0.352→0.364; XGB 0.2681→0.2882; + fairness win | 0004 |
| 36 | #15 | `was_fail`, `n_priority_this_inspection`, `n_core_this_inspection` (current-inspection own outcome) | — | honest test (n=13,812), controlled A/B: LogReg PR-AUC 0.291→0.344, P@10 0.326→0.369; XGB 0.280→0.344, P@10 0.306→0.367. Both metrics, both models. Ethics-reviewed (re-inspection feedback-loop disclosure) | 0002 gate; 0005 (principle 6) |

Tried and kept **out** (came up flat — risk is largely already captured by
`prior_*` inspection history): operator / license-status priors, per-code 1–29
prior counts, comment-severity text, the 311 geotemporal counts above, and the
Layer-C TF-IDF→SVD(50) violation-text embedding.

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
