# Data dictionary

Every dataset the pipeline pulls, where it comes from, and the columns that
matter. All sources are the public **Chicago Open Data portal** (Socrata / SODA
API, `https://data.cityofchicago.org/resource/<id>.json`); the four-by-four IDs
live in `DATASETS` in `src/foodsafety/config.py`, and the loaders are in
`src/foodsafety/io/soda.py`.

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

### 311 Service Requests — `v6vf-nfxy`
Resident-reported issues. Only the food/sanitation-relevant `sr_type`s are
pulled (`RELEVANT_SR_TYPES` in `config.py`) — the full feed is ~14 M rows across
110 types, mostly unrelated (potholes, noise, …).
- **Key columns:** `sr_type`, `created_date`, `street_address`, `latitude`,
  `longitude`.
- **Used for:** 311 spatial-count features (BallTree, 300 m radius). **Tested
  and flat at every spatial scale, so unwired** — redundant with `prior_*` and
  the rodent/pest/sewage keyword flags (see `experiments.md`). Code retained.

### Business Licenses — current `uupf-x98q`, historical `vgg9-bn8p`
- **Key columns:** `license_id`, `account_number` (operator, links a chain's
  locations), `license_status`, license start / expiry dates.
- **Used for:** license age + history features. (`license_status` is uniformly
  "AAI" on the current snapshot, so the planned revocation/condition counts were
  impossible; the cross-license operator-prior came back flat — `experiments.md`.)

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
  `experiments.md`). `src/foodsafety/features/building_features.py` + the dataset
  IDs are kept for resumability if a parcel-level (building-footprint) join ever
  becomes available.

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

### Census (tract demographics)
**Audit-only.** Reserved for the Phase-2 disparate-impact fairness audit
(`docs/fairness_audit.md`) — never a model feature (it's a direct
geographic/demographic proxy).

### Cuisine / menu type
Not pursued: predictive but ≈ ethnicity (a fairness trap). Related:
`facility_type` *was* dropped from the model (decision record 0004) — it partly
proxies immigrant/ethnic business types and its risk signal is largely redundant
with Chicago's Risk 1/2/3 tier.
