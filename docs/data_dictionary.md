# Data dictionary

Every dataset the pipeline pulls, where it comes from, and the columns that
matter. The core Chicago sources are on the public **Chicago Open Data portal**
(Socrata / SODA API, `https://data.cityofchicago.org/resource/<id>.json`); the
four-by-four IDs live in `DATASETS` in `src/foodsafety/config.py`, and the
loaders are in `src/foodsafety/io/soda.py`. The second city (New York City, see
below) is also on a Socrata portal but is pulled by its own self-contained
producer script, not through `config.py` / `io/soda.py`.

> Adding a dataset? Add its ID to `config.py`, document it here, and — if it
> reaches the model — update `docs/interface_contracts.md` too.

## Datasets used

### Food Inspections — `4ijn-s7e5`
The core dataset; one row per inspection. Drives the label and most features.
- **Key columns:** `license_` (license id), `dba_name` / `aka_name`,
  `facility_type`, `risk` (Chicago Risk 1/2/3), `address` / `zip` /
  `latitude` / `longitude`, `inspection_date`, `inspection_type` (Canvass /
  Complaint / License / Re-Inspection), `results` (Pass / Pass w/ Conditions /
  Fail / Out of Business / No Entry / …), `violations` (free text with codes
  1–63).
- **Used for:** the label `y_fail_or_critical_next_180d`, all `prior_*` history,
  the current-inspection outcome features, and the keyword flags. Training is
  from **2019-01-01** onward (the July 2018 procedure change makes pre/post
  labels non-comparable); pre-2019 inspections are burn-in only.
- **Note:** no inspector identity is published in this feed (only
  `inspection_id` / `inspection_type` / `inspection_date`).
- **Agent records link:** the chat agent's `find_inspection_records` tool builds a
  user-facing deep link to this dataset's Socrata query grid (filtered by
  `license_`, `zip`, or a lat/lon radius) so a user can verify the records behind a
  score. It only builds the URL — nothing is fetched.

### 311 Service Requests — `v6vf-nfxy`
Resident-reported issues. Only the food/sanitation-relevant `sr_type`s are
pulled (`RELEVANT_SR_TYPES` in `config.py`) — the full feed is ~14 M rows across
110 types, mostly unrelated (potholes, noise, …).
- **Key columns:** `sr_type`, `created_date`, `street_address`, `latitude`,
  `longitude`.
- **Used for:** 311 spatial-count features (BallTree, 300 m radius). **Tested
  and flat at every spatial scale, so unwired** — redundant with `prior_*` and
  the rodent/pest/sewage keyword flags (see `model-experiments.md`). Code retained.

### Business Licenses — current `uupf-x98q`, historical `vgg9-bn8p`
- **Key columns:** `license_id`, `account_number` (operator, links a chain's
  locations), `license_status`, license start / expiry dates.
- **Used for:** license age + history features. (`license_status` is uniformly
  "AAI" on the current snapshot, so the planned revocation/condition counts were
  impossible; the cross-license operator-prior came back flat — `model-experiments.md`.)

### Building Permits — `ydr8-5enu`, Building Violations — `22u3-xenr`
Physical-plant condition (permits issued, building-code violations), joined to
food establishments by **block-face** — lat/lon proximity at ~30 m, because
exact street-number matching is too brittle (building records file under
adjacent numbers).
- **Permits key columns:** `id`, `permit_type`, `work_description`, `issue_date`,
  `reported_cost`, `latitude` / `longitude`, `street_number` / `_direction` /
  `_name`.
- **Violations key columns:** `id`, `violation_code`, `violation_date`,
  `violation_status`, `inspection_category`, `latitude` / `longitude`, `address`,
  `inspector_id`.
- **Used for:** the block-face building-features experiment. **Ran NULL —
  unwired** (a single-split bump that expanding-window CV killed; see
  `model-experiments.md`). `src/foodsafety/features/building_features.py` + the dataset
  IDs are kept for resumability if a parcel-level (building-footprint) join ever
  becomes available.

### NYC DOHMH Restaurant Inspections — `43nn-pn8j` (second city)
New York City's food inspections, from the **NYC Open Data portal**
(`https://data.cityofnewyork.us/resource/43nn-pn8j.json`). Pulled and cached by
its own self-contained producer, `scripts/build_nyc_scores.py` — **not** through
`config.py` / `io/soda.py`. One row per inspection-violation; the producer
collapses to one row per `(camis, inspection_date)`.
- **Key columns:** `camis` (establishment id, used as `license_id` in the served
  JSON), `dba`, `boro`, `zipcode`, `latitude` / `longitude`, `cuisine_description`,
  `inspection_date`, `action`, `violation_code` / `violation_description`,
  `critical_flag`, `score` (numeric points — **higher is worse**), `grade`
  (A / B / C; derived from `score` when the grade cell is blank).
- **Label:** `y_next_bc` — 1 if the establishment's **next** inspection is graded
  **B or C (score ≥ 14)**, else 0. This is a different target from Chicago's
  `y_fail_or_critical_next_180d`; the two cities predict different things.
- **Agent records link:** the chat agent's `find_inspection_records` tool deep-links
  to this dataset's Socrata query grid too, filtered by `camis` / `zipcode` / radius.
  (Los Angeles left Socrata for a bulk CSV with no queryable API, so for LA the tool
  links to LA County Public Health's inspections page instead of a filtered grid.)
- **Training window:** **2022-07-01 onward.** NYC halted inspections in March 2020
  (COVID) and grades/scores only normalise from 2022 — the analog of Chicago's
  2019 cutoff for the July-2018 procedure change.
- **Served model:** XGBoost with Platt-on-margin calibration (`nyc_xgb_sigmoid`),
  reusing Chicago's SHAP / calibration / risk-tier machinery. Output is written to
  `app/public/data/nyc/{scores,inspection_history,methodology}.json` in the same
  schema Chicago uses (decision record 0016). LA is the same shape
  (`la_xgb_sigmoid`). Both served a calibrated logistic regression until
  2026-07-06 (PR #165), when XGBoost cleared the gate on a deploy-realistic split.
- **Violation vocabulary:** NYC's codes are mapped to the shared theme + severity
  crosswalk in `reference/violation_crosswalk.csv` so the product describes
  violations consistently across cities.

### LA County Restaurant + Market Inspections and Violations (third city)
Los Angeles County Environmental Health, published as **ArcGIS Hub bulk CSVs**,
not Socrata: inspections item `19b6607a…` + violations item `5eaea9f8…`, covering
**2023-04-01 → 2026-03-31**. LA County left Socrata (its SODA endpoint redirects
to a dead page) and the surviving City-of-LA Socrata feed `29fd-3paw` is frozen at
2018-07-31. Pulled by its own producer, `scripts/build_la_scores.py`, which joins
violations to inspection headers on `serial_number`.
- **Key columns (inspections):** `serial_number`, `facility_id`, `facility_name`,
  `facility_address`, `facility_city`, `facility_zip`, `activity_date`,
  `service_description` (routine vs owner-initiated), `score`, `grade`,
  `pe_description` (program element).
- **Key columns (violations):** `serial_number`, `violation_code`,
  `violation_description`, `points`.
- **Scope:** restaurants **and** retail food markets — ~75% / ~25% by facility
  (32,208 / 10,831 of 43,053), a near-mirror of Chicago's 69/31. Unlike Chicago
  there are effectively no institutional kitchens: only 14 facilities fall outside
  those two categories, so LA has no school / daycare / hospital coverage.
- **Grade direction is FLIPPED:** 0–100 where **higher is cleaner** (A = 90–100,
  B = 80–89, C = 70–79), the opposite of Chicago and NYC. Label `y_next_bad` = the
  next inspection scores **below 90**. Same-day collapse takes the **minimum**
  (worst) score, where NYC takes the max.
- **No coordinates in the feed.** Facilities are geocoded once via the free US
  Census batch geocoder (95.7% matched, ZIP-centroid fallback) and cached in
  `reference/la_facility_coords.csv` so rebuilds are offline. Coordinates are
  therefore approximate — see the neighborhood false-positive finding in
  `fairness_audit.md`.
- **No burn-in cutoff needed:** the feed starts post-COVID (2023-04) and mean score
  is flat ~94.5 across 2023–2026.
- **`pe_description` is in the raw feed but NOT carried into the feature frame**
  (`src/foodsafety/audit/adapters/la.py`). It encodes venue type, **seat count**,
  and **LA County's own risk grade** in one string (e.g.
  `RESTAURANT (0-30) SEATS HIGH RISK`) — 30 distinct values. The county risk grade
  is the direct analog of Chicago's `static_risk_tier`, which **is** a kept model
  feature, and unlike facility type it is not an ethnicity proxy. Untested lever in
  the city that is furthest from its ceiling; see `model-experiments.md`.

## Data sources considered but NOT used

### Yelp — dead end for Chicago
Investigated as a source of foot-traffic / review signal. **Not usable for this
project**, via either avenue:
- **Yelp Open Dataset** (the downloadable academic dataset) covers only a fixed,
  limited set of metro areas and **does not include Chicago** — there are simply
  no rows to join to Chicago food establishments.
- **Yelp Fusion API** *does* cover Chicago, but its **Terms of Service prohibit
  using the data to train machine-learning models** (and prohibit bulk storage).
  So even though the data exists, it can't legally feed this model.
- The same reasoning rules out **Google reviews / Places** (API terms forbid ML
  training).
- **Verdict: dead end — not pursued.** Listed as out-of-scope in `CLAUDE.md`;
  this is the *why*.

### NOAA weather
Cut from the MVP. A plausible *orthogonal* future lever (heat waves stress
refrigeration and drive pest activity), but `temporal_month` / `temporal_quarter`
already capture coarse seasonality, so it would need to show *incremental* signal
over those. Untried.

### Census / ACS (tract demographics) — audit-only
**Audit-only, never a model feature** (it's a direct geographic/demographic
proxy — decisions 0004 / 0005). Now implemented for the disparate-impact fairness
audit (`src/foodsafety/audit/census.py`, decision record 0018): each
establishment's `lat/lon` is point-in-polygon joined to its **census tract**
(TIGER/Line shapefiles) and then to **ACS 5-year** tract attributes (median income,
race/ethnicity, poverty, foreign-born, limited-English, and secondary context).
Used only to *measure* disparate impact — no column reaches `ALL_FEATURES`, the
served parquet, the app, or CI. Needs a free `CENSUS_API_KEY` (the data API now
requires one) and the `audit` optional dependency extra (geopandas). Results:
`docs/fairness_audit.md`, `reports/fairness/fairness_audit_<city>.json`.

### Cuisine / menu type
Not pursued: predictive but ≈ ethnicity (a fairness trap). Related:
`facility_type` *was* dropped from the model (decision record 0004) — it partly
proxies immigrant/ethnic business types and its risk signal is largely redundant
with Chicago's Risk 1/2/3 tier.
