# 0014 — NOAA weather: citywide O'Hare station, opt-in feature family

- **Status**: **Proposed** (scope change — needs Jun's sign-off as scope guard;
  CLAUDE.md text updated provisionally, flag for ack)
- **Date**: 2026-06-30
- **Owner**: Arun (DE)

## Context

NOAA weather was named in the original project plan, then explicitly cut from
the MVP and listed in CLAUDE.md as both an OUT-of-scope item and a Phase-2
Roadmap item — "untried" per `docs/data_dictionary.md`. No source, station, or
join key had ever been chosen. This record documents the choices made to
implement it now, scoped narrowly: **loader + feature code + an opt-in A/B
harness**, not a promotion to the served model.

## Decision

1. **Source: NOAA GHCN-Daily, `by_station` plain-CSV endpoint.** No API token
   required (unlike NOAA's CDO web-service API), one GET per station, published
   at `https://www.ncei.noaa.gov/pub/data/ghcn/daily/by_station/<id>.csv.gz`.
   Long format (`station, date, element, value, ...`); `fetch_noaa_ghcnd`
   (`src/foodsafety/io/noaa.py`) pivots to one row per date.
2. **Station: Chicago O'Hare International Airport, GHCND ID `USW00094846`.**
   A single citywide proxy — the inspections data has no per-restaurant
   weather station, and O'Hare is NOAA's most complete, longest-running
   Chicago-area station (the obvious "Chicago weather" answer; Midway is the
   alternative and would be a reasonable substitute, not evaluated here).
3. **Cleaning**: rows where NOAA's own `Q-FLAG` is non-blank are dropped — that
   flag is NOAA's own quality-control verdict that a reading is suspect, not a
   transient fetch error. `TMAX`/`TMIN` (tenths of °C) and `PRCP` (tenths of
   mm) are converted to standard units; `SNOW` (already mm) is passed through.
4. **Join key: `date`, not `(license_id, date)`.** Weather is citywide, so
   every restaurant inspected on the same day gets the same weather features —
   no per-license join. This is the one structural way this module differs
   from every other `prior_*` feature module (see `weather_features.py`'s
   docstring).
5. **Leak guard: `.shift(1)` on the daily series, not the per-license
   exclusive-cumsum pattern** `inspection_features.py` uses — there's no
   license grouping to be leak-free *within*, just a single daily series that
   must not look at the anchor day's own weather.
6. **Features** (5, mirroring the `prior_*` naming convention):
   `prior_tmax_3d_avg`, `prior_tmin_3d_avg` (3-day rolling mean high/low temp),
   `prior_precip_7d_sum` (7-day rolling precipitation total),
   `prior_heat_days_30d` / `prior_freeze_days_30d` (30-day trailing counts of
   days over 90°F / under 32°F — the heat/cold-stress mechanism named in
   `docs/data_dictionary.md`: refrigeration stress and pest activity).
7. **Wired as opt-in, not promoted.** `WEATHER_FEATURES` in `baseline.py`,
   `--with-weather` in `build_features.py`, and
   `scripts/experiment_weather_features.py` mirror the existing
   `BUILDING_FEATURES` precedent exactly: feature code lands, but it only
   enters `ALL_FEATURES` / the served model if an A/B on the temporal split
   clears the both-metrics gate (PR-AUC AND precision@10%, per
   `docs/model-experiments.md`'s standing protocol).

## Why this needs Jun's sign-off, not just a docs update

CLAUDE.md's OUT-of-scope list says explicitly: "If a teammate proposes any of
the above, the answer is 'Phase 2, after demo.' ... Just don't write the seam."
This change writes the seam. It was authorized ad hoc (Arun, DE owner and PM
tiebreaker) rather than through the normal Friday-check-in / PM-scope-guard
process CLAUDE.md describes, because there was no time pressure forcing an
immediate decision either way. Flagging here so Jun can ratify, amend, or
revert the CLAUDE.md scope-note edit in this PR.

## What this decision does NOT do

- Does not add weather to `ALL_FEATURES` or the served `scores.json` — no
  `docs/interface_contracts.md` schema change.
- Does not run the A/B. `scripts/experiment_weather_features.py` requires a
  bootstrapped local/S3 data pipeline (raw inspections + licenses + the
  features parquet) and live network access to NOAA; neither was available in
  the environment this was authored in (confirmed: the existing Socrata SODA
  loaders fail with the same SSL/network error here, so this is an environment
  limitation, not a defect in the new loader). A teammate with the data
  pipeline running needs to execute the A/B before this can be promoted.
- Does not pick Midway over O'Hare, multi-station blending, or a different
  variable set (wind, humidity) — narrowest defensible v1.

## Follow-up (not this PR)

- Run `scripts/experiment_weather_features.py`; record the result (kept or
  reverted) as a row in `docs/model-experiments.md`, same as every other
  feature experiment.
- If kept: promote `WEATHER_FEATURES` into `ALL_FEATURES`, re-ship the served
  model + `scores.json`, update `docs/interface_contracts.md`'s feature table
  + changelog version (tag all five owners per the schema-change rule).
- If reverted: leave the feature code in place (cheap, self-contained, already
  has driver labels) and log the negative result.
