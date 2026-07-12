# Fairness / ethics audit (`foodsafety.audit`)

A reusable, city-agnostic framework for auditing the food-safety risk models for
disparate impact across neighborhoods, area demographics, cuisine, establishment
tenure, and facility type. Built for Chicago, New York City, and Los Angeles;
adding a city is one adapter, not a rewrite.

> **Status:** framework in progress on `bella/mle-fairness-census-audit`.
> Roadmap-scoped work (CLAUDE.md lists the production disparate-impact audit as
> Phase-2), so the results and the decision record are **pending Jun's sign-off**
> as scope guard. This README is the living design doc — per-city results get
> filled into the tables at the bottom as each city is run.

---

## The one rule that governs everything

**Census demographics are audit-only. They are never a model feature** (decisions
0004 / 0005). The join exists to *measure* whether the model's errors fall
unevenly on protected groups. Adding a tract's income or race as a *predictor*
would encode systemic bias directly into the score. No demographic column ever
enters `ALL_FEATURES`, `scores.parquet`, or the app. The package is structured so
this is obvious: the census join lives in its own module (`census.py`) and runs
*after* the adapter, never inside it.

---

## What the audit asks

For each model, across each grouping axis, do the model's decisions land evenly?
Three complementary lenses:

1. **Statistical parity** — is an establishment more likely to be *flagged*
   (High tier) just because of where it is or what it is? (Four-fifths rule.)
2. **Equalized odds** — among places that truly do / don't fail, are the
   **false-positive** and **false-negative** rates even across groups? This is
   the core question. A high FNR for a group means that group is
   *under-protected* (real risks missed); a high FPR means it is
   *over-scrutinized* (wasted inspection burden).
3. **Calibration** — does a risk score of 0.3 mean the same 30% chance of failure
   in every group, or is the model systematically over/under-confident for some?

A fourth, ranking-quality view (per-group PR-AUC / precision@k / recall@k) reuses
the existing `models.evaluate.group_performance_audit`.

---

## Which models

| Model | What it predicts | Audit depth |
|---|---|---|
| **Model 1 — risk** | 180-day fail-or-priority probability (the worklist + gauge) | **Full battery**: parity, FPR/FNR, calibration, ranking. |
| **Model 2 — forecast** | forward-looking trend slope (DR 0011) | **Calibration + coverage only.** Its ~30% coverage makes per-group confusion-matrix cells too sparse to trust; we still check whether it is equally well-calibrated across groups and whether its coverage itself is skewed. |

---

## Architecture (the seam)

```
per-city raw data ──▶ CityAdapter.build_audit_frame() ──▶ AuditFrame (test split, realised labels)
                          (chicago / nyc / la)                  │
                                                                ▼
                                            census.py: lat/lon ─▶ tract ─▶ ACS attrs  (audit-only)
                                                                │
                                                                ▼
                                              fairness.py: parity · FPR/FNR · calibration
                                                     (+ bootstrap CIs, noise floors)
                                                                │
                                                                ▼
                                       fairness_audit_<city>.json  +  docs/fairness_audit.md
```

- **`frame.py` — the `AuditFrame` contract.** One row per evaluated
  `(establishment, as_of_date)` in the **chronological test split** with a
  *realised* label. Not `scores.json` (forward-looking; labels unknown, so
  FPR/FNR/calibration are undefined there). The metrics engine reads only this
  contract, so it is identical for every city.
- **`CityAdapter` (Protocol in `frame.py`).** Each city owns its loading: the
  temporal split, the served model, and the joins for lat/lon, facility type,
  license age, neighborhood, and cuisine. Adapters never attach census columns.
- **`census.py`.** `lat/lon → census tract (GEOID) → ACS 5-year attributes`,
  cached and batch. Point-in-polygon via **geopandas + shapely** against
  TIGER/Line tract shapefiles (IL / NY / CA).
- **`fairness.py`.** The city-agnostic metrics engine: parity, equalized-odds
  gaps, calibration-by-group, bootstrap CIs, and the verdict logic in
  `config.py`.
- **`config.py`.** Single source of truth for the axes, the ACS variable
  registry, and the tolerance bands.

---

## Grouping axes

Primary axes (full battery) and, for the demographic ones, the census column they
key on:

| Axis | Source | Notes |
|---|---|---|
| Neighborhood | city boundary set | Chicago community area; NYC neighborhood tabulation area / borough; LA neighborhood. Also backs a future UI neighborhood filter. |
| Area median household income | census join | within-city quartiles |
| Area % non-white | census join | within-city quartiles |
| Area dominant group | census join | majority White / Black / Hispanic / Asian / none |
| Area % below poverty | census join | within-city quartiles |
| Area % foreign-born | census join | within-city quartiles |
| Area % limited-English households | census join | immigrant-community / language-access lens |
| Cuisine | establishment | NYC native `CUISINE DESCRIPTION`; Chicago/LA OSM-derived, low-confidence |
| New vs established | `license_age_days` | new `<1yr` / established `1-3yr` / mature `3yr+`; the `<1yr` bucket is the cold-start slice |
| Facility type | `static_facility_type` | keeps the vulnerable-pop view (daycare / school / long-term care) |

**"Customer demographics" is a proxy.** We never observe patrons. The census join
describes the *residential population of the tract the establishment sits in* — a
neighborhood proxy, reported and labeled as such.

---

## Census / ACS variables

**Primary** (drive the grouping axes above): median household income, % non-white
+ dominant group, % below poverty, % foreign-born, % limited-English households.

**Secondary** (reported as tract-level *correlations* with flag rate and
miscalibration — not separate confusion-matrix cuts, to avoid multiple-comparison
inflation): educational attainment, % renter-occupied + median rent / home value,
unemployment rate, % on SNAP, population density (also carried as a confound),
and age structure (% under 5, % 65+).

Exact ACS 5-year variable codes are resolved and **validated against the Census
data dictionary in `census.py`** — the registry in `config.py` carries the
concept + table family, which is stable across vintages.

---

## Evaluation discipline

- **Basis:** the chronological test split (Chicago: `inspection_date >= VAL_END`),
  right-truncation filtered = served basis. Realised labels only.
- **Operating point:** "flagged" = deployed **High** tier (parity + FPR/FNR).
  Elevated+High is a secondary cut; top-10% is a threshold-free cross-check.
- **Noise floors:** audit only groups with `n >= 50` **and** `>= 50` positives.
  PR-AUC and small cells swing on base rate, not bias — a gap is only a *finding*
  when its bootstrap CI clears the tolerance band.
- **Confounds:** read every disparity alongside group prevalence and population
  density before concluding "bias".

## Tolerance bands (`config.py`)

| Lens | Band |
|---|---|
| Statistical parity | four-fifths rule (flag-rate ratio `>= 0.80`) |
| FPR / FNR gap | `<= 0.10` absolute (max - min across groups), CI-confirmed |
| Calibration (ECE) gap | `<= 0.05` absolute across groups |

---

## Mitigation (analysis only)

The audit **measures**; it does not change the model this pass. Where a real,
CI-confirmed gap appears we report *what closing it would cost*:

- **Per-group threshold analysis** (primary, cheap): to equalize FNR across, say,
  income groups, what tier-cutoff shift would each group need, and what does that
  cost in FPR / precision at a fixed inspection budget? Operating-point math; the
  model is untouched.
- **Training-time reweighting** (heavier, optional): flagged as a *simulated*
  what-if only if the threshold analysis shows a gap worth it. This edges toward
  the out-of-scope "reweighting" line — Jun's call before we build it.

---

## Running the audit

_To be filled in as the per-city adapters and the notebook land._ The intended
entry points: a parametrized notebook (`notebooks/NN_fairness_census_audit.ipynb`)
run per city in place, plus a `fairness_audit_<city>.json` artifact written via
the batch-to-JSON pattern.

## Dependencies and setup

- **geopandas + shapely + pyogrio** — offline, reproducible point-in-polygon
  tract join, and the same primitive that can later assign user-facing
  neighborhood polygons. **Build-time / audit-only**: it lives in the `audit`
  optional extra (`uv sync --extra audit`), outputs are cached, and the app never
  imports it. Justified in the PR as audit tooling.
- **`CENSUS_API_KEY`** — the Census data API requires a key (free, instant:
  <https://api.census.gov/data/key_signup.html>). Set it in the environment or
  `.env`. Only the audit needs it — not the model pipeline, the app, or CI.
- Data pulls (TIGER tract shapefiles, ACS tables) are cached under
  `<RAW_DIR>/census/`, so a re-run is offline after the first fetch.

## Future: user-facing neighborhood filter

The spatial-join infra makes a "filter by neighborhood after selecting a city"
feature cheap later — precompute each establishment's neighborhood at build time,
add a `neighborhood` field to the served JSON, and the app filters on it (same
batch-to-JSON contract; the app stays dumb). That is a **schema change needing
owner sign-off — a follow-up, not this audit.** No stub is written for it now.

---

## Per-city results

Filled in as each city is audited. Each city gets: the three lenses per primary
axis, the secondary-variable correlations, the mitigation cost analysis, and a
plain-English verdict.

### Chicago

_Pending._

### New York City

_Pending._

### Los Angeles

_Pending._
