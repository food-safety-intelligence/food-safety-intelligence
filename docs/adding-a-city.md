# Handoff: adding another city (worked example — Los Angeles)

A runbook for replicating the Chicago → NYC multi-city work (PR #140, decision
record 0014) for a third city. Written for an agent or engineer picking this up
cold. LA is the worked example, but the steps are general — the city-specific
judgement calls are called out.

> **Status: LA has been built (2026-07-04, decision record 0016).** Two runbook
> assumptions turned out to be stale for LA and are worth flagging for the *next*
> city:
> 1. **LA County left Socrata.** The `data.lacounty.gov` SODA endpoint named in
>    step 0.1 is dead (migrated to ArcGIS Hub); the only live Socrata LA feed
>    (City of LA `29fd-3paw`) is frozen at 2018. The fresh data is an **ArcGIS Hub
>    bulk CSV** (inspections `19b6607a…` + violations `5eaea9f8…`, 2023–2026), so
>    `build_la_scores.py` uses a CSV download, not the SODA pull — **verify the
>    feed is still Socrata before assuming `load_nyc_raw` ports directly.**
> 2. **The LA feed has no coordinates.** Chicago/NYC ship lat/lon inline; LA has
>    only an address. The producer geocodes once via the free US Census batch
>    geocoder and commits `reference/la_facility_coords.csv` (ZIP-centroid
>    fallback). A new city may need the same coordinate step.
>
> Everything else ported cleanly: the flipped A/B/C direction (step 0.2), the
> shared crosswalk, the calibrated-LogReg served model, `city.ts` `CITY_CONFIG`,
> `CityGate`/`HowItWorksLa`, and the city-aware agent code (incl. city-aware
> `find_restaurants`). LA `chatSupported` is **true**; it goes live when the agent
> redeploys on merge (cross-account, Deepak's) — revert the flag if a post-merge
> lookup returns "no record".

The guiding principle from NYC: **the web app is one static build with a runtime
city switch; every per-city difference lives in `app/src/lib/city.ts`; the model
is retrained per city and batch-scored to JSON in the exact current schema.** The
agent chat is a separate, cross-account deploy (Deepak) — you prepare the code,
he ships it.

---

## 0. Before you touch code — feasibility (½ day)

Do this first; it decides whether the city is worth adding and what the label is.

1. **Find the open-data feed.** LA County restaurant inspections are on the LA
   County / data.lacounty.gov portal (Socrata, like Chicago `4ijn-s7e5` and NYC
   `43nn-pn8j`), so the same SODA pull pattern in `scripts/build_nyc_scores.py`
   (`load_nyc_raw`) ports directly. Confirm the four-by-four dataset id, columns,
   row grain (one row per inspection vs per violation), and update cadence.
2. **Grade system + DIRECTION (LA's big gotcha).** LA grades **A/B/C on a 0–100
   scale where _higher is better_** (A = 90–100, B = 80–89, C = 70–79) — the
   **opposite** of Chicago (Fail/priority) and NYC (score ≥ 14 = worse). So the
   label and every "lower = cleaner" assumption flips. Decide the label
   explicitly, e.g. `y = next inspection graded B or C (score < 90)`, and make
   sure the producer's comparisons use the right direction.
3. **Policy / data discontinuities.** Chicago cut pre-2019 (2018 procedure
   change); NYC cut pre-2022 (2020 COVID inspection halt). Pull a per-year
   inspection histogram (`date_extract_y`) and set the training-cutoff to the
   post-disruption steady state. LA also paused inspections in 2020 — check.
4. **Base rate + rough signal.** Compute the forward-label base rate and, cheaply,
   an XGBoost ROC-AUC on a temporal split (mirror the NYC feasibility scratch).
   If it's much weaker than Chicago, ship it as a **coverage feature** and say so
   in the UI (as NYC does) — don't over-promise accuracy.
5. **Write it down.** Add a short decision record (copy `0014`'s shape) with the
   measured numbers, the label definition, and the honest framing. Multi-city is
   Roadmap scope — get the go-ahead before building.

---

## 1. Crosswalk — extend `reference/violation_crosswalk.csv`

Add the new city's violation codes to the shared vocabulary so the UI/agent can
describe violations consistently across cities.

- Pull each distinct `violation_code` + a representative description from the
  feed (see `nyc_crosswalk` in the throwaway crosswalk builder / DR 0014 method).
- Assign `theme` via the **ordered keyword rule-list on the description text**
  (works across cities' different code schemes) and `severity_tier` from the
  city's own critical flag / grade weighting.
- Append rows `city,native_code,native_desc,theme,severity_tier` to the CSV.
  Keep the 12-theme set; genuinely non-food-safety codes go to
  `other_administrative`.

---

## 2. Producer — a new `scripts/build_<city>_scores.py`

Copy `scripts/build_nyc_scores.py` and adapt. Keep it self-contained (pulls SODA
→ caches under `data/raw/`, reads the committed crosswalk, writes
`app/public/data/<city>/{scores,inspection_history,methodology}.json`).

Change per city:
- **Data pull** columns + dataset id (`NYC_SODA`, `NYC_COLS`).
- **Label** (`BC_THRESHOLD` / the `y_*` definition) — mind LA's flipped direction.
- **Training cutoff** (`NYC_TRAIN_START`, `TRAIN_END`, `VAL_END`).
- **Feature build** — the `prior_*` history + current-outcome + crosswalk
  theme/severity counts port; adjust the grade/score parsing.
- **Driver labels** (`nyc_labels`) → city-appropriate plain-English strings.
- **Tier thresholds** — recalibrate to the city's own `risk_score` distribution
  (they're printed at runtime; don't reuse another city's cutoffs).
- **Served model stays a calibrated LogReg** (reuses the SHAP-waterfall +
  calibration-triple machinery); XGBoost is only the eval comparator.

**Schema (critical):** match `main`'s *current* scores schema, not a snapshot.
Today that is **0.5.0** — column `trend_slope` (not `trend_slope_90d`), totals
`worsening`/`improving`. It's emitted by `foodsafety.serve.predict_batch.write_scores_json`,
so run the producer against the **worktree's** merged `src/foodsafety`
(`PYTHONPATH=src <main-venv>/python scripts/build_<city>_scores.py`). If `main`
advances the schema again, re-check and regenerate — this exact drift bit NYC
after a mid-flight merge.

**inspection_history** must carry a per-event forecast `score` (drives the
detail-page trend chart, DR 0011) and the `result` string the app expects
(`InspectionEvent`: `{date, type, result, headline, score?, comments?}`).

---

## 3. Data artifacts + build wiring

- **Commit** `app/public/data/<city>/{scores,inspection_history,methodology}.json`
  with `git add -f` — `app/public/data/*` is gitignored; the Chicago/NYC source
  JSONs are force-added. The build-time `search-index.json` + `detail/` bundles
  stay ignored.
- **Build scripts** (`app/package.json`): the NYC pattern added a `gen-nyc:dev`
  script and appended NYC to `predev` / `prebuild` (gen-search-index) and
  `postbuild` (build-detail-data into `out/data/<city>` + drop the large source
  JSONs). Generalising to an N-city loop is a welcome cleanup; otherwise copy the
  NYC lines for `<city>`.
- **Deploy** (`.github/workflows/deploy-web.yml`): exclude `data/<city>/detail/*`
  from the plain `aws s3 sync` and add a per-city `sync-detail-s3.mjs` pass. The
  added city's data comes from the **committed `public/data/<city>/*.json`**
  (`prebuild-sync-s3.mjs` only pulls *Chicago's* root data from the `web-app-data`
  data bucket, with a committed fallback). The standard web deploy still
  `aws s3 sync`s the built `out/` — including the city's data — into the **website
  S3 bucket** (behind CloudFront) on every merge, so the data *is* served from S3;
  what's not needed is a **separate manual publish** to the data bucket (that path
  is only for Chicago's fresh batch output). The **agent** is the exception — it
  reads its own copy from the data bucket, a separate cross-account push (Deepak).

---

## 4. Frontend — `app/src/lib/city.ts` first, then the checklist

Add the city to `City`, `CITIES`, and `CITY_CONFIG` with **every** field filled
(the type enforces this): `label`, `dataPrefix` (`"<city>/"`), `center`, `zoom`,
`centerLabel`, `nounPlural`, `sourceBlurb`, `cityState`, `healthDept`, `riskLabel`,
`typicalNoun`, `comparedNoun`, `outcomeSentence`, `footerBlurb`, `sources`,
`historyResults` (the Pass/Fail-vs-grade badges + colours), `outcomeNoun`,
`isBadOutcome`, `trendStableBand`, `chatSupported`.

Because everything reads `CITY_CONFIG[city]`, most components then "just work."
Verify these city-aware surfaces (all already parameterised for NYC):
- **MapExplorer / MapView** — fetches `dataUrl(city, "search-index.json")`, map
  center from config. (Map recenter is handled by MapView's `onLoad` jumpTo — see
  Gotchas.)
- **RestaurantDetail / ScoreCard** — address suffix, risk label, typical/compared
  nouns, outcome sentence, "N `<outcomeNoun>`" headline (`isBadOutcome`).
- **InspectionTimeline / ResultTally** — dot colours + tally buckets from
  `historyResults`.
- **CityIntro** (home below-fold) — blurb + totals.
- **SiteFooter** — sources + blurb.
- **ChatInterface** — `FIND_QUERIES_BY_CITY` (add the city's neighborhoods),
  disclaimer, and it passes `city` to `queryAgent`.
- **how-it-works** — the page is wrapped in `<CityGate nyc={<HowItWorksNyc/>}>`.
  Add a `<HowItWorks<City>/>` component driven by the city's `methodology.json`
  (mirror `HowItWorksNyc`: hero stats, jump-nav, TierPill bands, worked waterfall,
  glossary), OR generalise CityGate to pick by city. Match Chicago's depth.
- **CityPicker** — the entry popup lists all `CITIES` automatically.
- Entry-popup background / caregivers hero images are shared (not per-city).

---

## 5. Agent (chat) — code here, deploy is Deepak's (cross-account)

The agent runs on AgentCore in a **different AWS account**; you can't deploy or
guardrail-reprovision it. Make the code city-aware and unit-test it; hand the
deploy to Deepak.

- **`agents/entrypoint.py`** — add the city's S3 keys to `_warm_data_files`
  `optional` (best-effort so other cities never break), add its `/tmp` env paths,
  and it already routes the active city (parsed from the `[[city:…]]` query
  marker / `city` field) to the tools via `_ACTIVE_CITY` + the ACTIVE CITY
  system-prompt prefix.
- **`agents/tools/get_safety_score/handler.py`** and
  **`…/explain_restaurant/handler.py`** — extend `_scores_path` / `_history_path`
  with the new city; the loaders are `lru_cache`-keyed by city. Make
  `explain_restaurant`'s `_classify_result` + `model_note` city-aware (NYC maps
  A/B/C → pass/pass-w-conditions/fail and emits a next-inspection note).
- **`agents/tools/find_restaurants/handler.py`** — the discovery tool is city-aware
  via `CITY_GEO`. Add a **`<city>_neighborhoods.py`** (mirror `chicago_neighborhoods.py`:
  a `BBOX` name→`{south,west,north,east}` dict, the `CENTROIDS` midpoint comprehension,
  and whole-city `<CITY>_BBOX` / `<CITY>_CENTROID`), then register it in `CITY_GEO`.
  Cover the neighborhoods your `ChatInterface` `FIND_QUERIES_BY_CITY` names, plus a few
  coarse whole-region fallbacks (boroughs / big districts) so a broad query like "pizza
  in Brooklyn" resolves instead of being declined. **Without this the tool falls back to
  Chicago and rejects the new city's neighborhoods** (the "Astoria not in scope" bug).
  `entrypoint.py` already passes `_ACTIVE_CITY` in. **Two** suites test `_resolve_geometry`
  — `agents/tools/find_restaurants/test_handler.py` AND `tests/test_agent_tools.py`
  (the Python job's main suite) — update both.
- **`agents/create_guardrail.py`** — **no per-city change needed.** The guardrail
  is city-agnostic: it denies only *personalised medical* + *legal* advice. The old
  `OffTopicNonFoodSafety` catch-all (which listed cities) was removed on purpose — a
  negative catch-all over-matched and blocked ~100% of queries (see the file's
  docstring + the DR 0012 update note). Off-topic + uncovered-city requests are
  declined by the *system prompt*, not the guardrail. So adding a city does **not**
  require reprovisioning the guardrail.
- **Flip `chatSupported: true`** in `city.ts` only after the steps below land.

### Deploying the agent for a new city

The runtime lives in AWS account `991500268971` (Deepak's), us-west-2. The agent
**code** auto-deploys on merge to `main` (`deploy-agent.yml`, OIDC role). What still
needs doing per city:

1. **Push the city's data to S3.** The agent reads `web-app-data/<city>/scores.json`
   + `inspection_history.json` from `food-safety-intelligence-data` (us-east-1) at
   cold start (`_warm_data_files` optional). `publish.py` only pushes Chicago, so
   copy the committed JSONs manually (Bella's creds — the bucket is her account):
   `aws s3 cp app/public/data/<city>/{scores,inspection_history}.json s3://food-safety-intelligence-data/web-app-data/<city>/`.
   Ensure the runtime role has `s3:GetObject` on those keys (Issue #79 class).
   *(As of 2026-07-04 both `nyc/` and `la/` were empty — NYC lookups returned
   "no record" despite `chatSupported: true`. Don't assume prior cities were pushed.)*
2. **Merge** — the agent redeploys with the new city's code.
3. **Verify** (see `la-chat-deploy-cloudshell.md` for the exact commands):
   `apply-guardrail` on a food-safety query for the new city → `NONE` (the
   deploy-agent guardrail gate now checks one per covered city); and
   `run_local.py "[[city:<city>]] …"` returns that city's results.
4. **Flip `chatSupported: true`** in `city.ts` once 1–3 pass.

The wired guardrail id/version is tracked only in
`agentcore-deploy/agentcore/agentcore.json` (`FSI_BEDROCK_GUARDRAIL_VERSION`) — the
single source of truth the deploy reads.
- Run the handler unit tests (`agents/tools/*/test_handler.py`) — they default to
  Chicago, so they keep passing; add a city case if you want coverage.

---

## 6. Verify (don't skip — the running app, not just tsc)

- `npx tsc --noEmit`, `npx vitest run` (app), `pytest agents/tools/*/test_handler.py`,
  `ruff check` on the producer + agent.
- Run the app and `/verify` **every state × both viewports** + Chicago regression:
  entry popup, home map + list (confirm the map **centers on the new city with
  pins** on a direct `?city=<city>` load), search, tier filter, detail
  (High/Low/no-trend — trend chart plots, grade dots coloured), how-it-works,
  chat, caregivers, mobile.
- Put the screenshots in the PR (see PR #140's `design/<city>-pr-screenshots/`).

---

## 7. Gotchas (learned the hard way on NYC)

- **Map recenter:** use MapView's `onLoad` → `jumpTo` for the initial city, and
  `flyTo` on center change for toggles. Do **not** remount via `key={city}` (races
  maplibre's container init) and don't rely on `flyTo` alone (fires before tiles
  load on a direct visit → data over the wrong city's map, no pins).
- **Schema drift:** always regenerate against `main`'s *current*
  `predict_batch.write_scores_json`. A mid-flight merge moved the contract
  `0.4.0 → 0.5.0` (`trend_slope`, `worsening/improving`) and silently nulled NYC
  trends until regenerated.
- **Asymmetric data paths:** Chicago is the historical root (`dataPrefix: ""`);
  every added city is a prefix (`"<city>/"`). Keeps Chicago's prod paths untouched.
- **Force-add data JSONs** (`git add -f`) — they're gitignored.
- **Chat is cross-account** (acct 991500268971 = Deepak, not bella's). Code only;
  he deploys + reprovisions the guardrail.
- **Dev/verify hygiene** (SageMaker): unique dev port per session (not the default),
  the worktree's own build dir; the browser preview needs the jupyter proxy
  (`…/proxy/absolute/<port>/`) with `DEV_BASE_PATH`/`NEXT_PUBLIC_BASE_PATH` set
  (both no-ops in prod). Never `pkill -f "next dev -p <port>"` from a shell whose
  own command line contains that string — it kills its own shell.

---

Reference: PR #140 (Chicago → NYC), decision record 0014, and this repo's
`docs/interface_contracts.md` (the scores/JSON schema is the cross-team contract).
