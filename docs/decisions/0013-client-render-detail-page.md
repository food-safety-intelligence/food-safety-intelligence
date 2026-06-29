# 0013. Client-render the detail page from per-license JSON

## Status
Accepted (2026-06-29). Implemented in #119; bundle build wired in the same PR.

## Context
The restaurant detail page was a statically-exported dynamic route
(`/restaurant/[id]`) whose `generateStaticParams` was **capped at the top-500
establishments by risk** to keep the build tractable. But the home page's
search / sort / filter spans the **whole** population, so the **Low** tab, the
**A–Z** tab, most **map pins**, and any **search hit** for a lower-risk
establishment linked to a page that was never generated → **404**. Generating a
page for all ~23,621 establishments removed the 404s but took **~21 min**
(~10.5 min of page generation alone) — too slow for CI and every deploy, and
near the static-export memory ceiling.

## Decision
Make the detail page a **single client-rendered shell** at
**`/restaurant/?id=<id>`** (a query param — `output: "export"` has no runtime
fallback for a dynamic `[id]` segment, so a single static page keyed by query is
the only way to serve arbitrary ids from one build artifact). It reads the id
client-side and fetches that establishment's data from **same-origin static
JSON**:
- `data/detail/<license_id>.json` = `{ restaurant, history, comments }` (one per license)
- `data/detail-globals.json` = `{ is_mock, calibration, populationStats }` (shared)

both written by `app/scripts/build-detail-data.mjs` (with `percentile_rank`
precomputed). This is the same same-origin static-JSON pattern the home page
already uses for `search-index.json` — **no S3 at request time, no new infra**.

## Consequences
- Build is **O(1)** in establishment count: page generation ~10.5 min → ~2.7 s;
  **every** establishment is reachable (404s gone).
- Detail URLs change to `/restaurant/?id=<id>`; old `/restaurant/<id>` deep
  links no longer resolve (static export cannot redirect). Accepted.
- The detail page loses per-page SSR/SEO and gains a brief client-side load
  (skeleton + not-found states). Acceptable — the app is not SEO-driven.
- Preserves the permanent **batch-score-to-JSON** contract: the app still never
  calls the model at request time; only *where* the JSON is sliced changed.

## Alternatives considered
- **Generate all ~23.6k pages (SSG)** — correct but ~21-min builds; too slow for
  CI and every deploy.
- **Keep top-N + a runtime fallback** — `output: "export"` has no fallback, so
  serving the rest still requires a query-param client route; i.e. this decision.
