# Inspector tab: violation filter + map view — design

Date: 2026-07-13
Owner: Jun (app workstream)
Status: approved in brainstorming session; awaiting implementation plan

## Goal

Two additions to the "For inspectors" page (`/inspectors`, `InspectorWorklist.tsx`):

1. Filter the priority queue by **violation category** observed at each
   establishment's latest scored inspection.
2. A **List | Map toggle** on the queue panel that swaps the queue rows for a
   map pane reusing the Search tab's `MapView` (tiles, tier-colored pins,
   zoom-aware density, popups).

Both controls are URL-driven and work for all three cities (Chicago, NYC, LA).

## Decisions made (with Jun)

- **Filter basis:** human-readable violation categories (not model drivers,
  not raw per-city violation codes).
- **Time window:** only the latest scored inspection counts. "Who currently
  has a rodent problem", not "who ever had one".
- **Data plumbing:** app build-time tagging in `gen-search-index.mjs`. No
  Python pipeline change, no interface-contract (`scores.json`) change, no S3
  re-upload. Trade-off accepted: local dev indexes tag from committed
  first-violation headlines only (deploy builds tag from the full S3-synced
  violation text), so dev chip counts run lower than prod.

## Background / constraints discovered

- The worklist is built from the slim per-city `search-index.json`
  (`gen-search-index.mjs` projects it from `scores.json`). Rows already carry
  `lat`/`lon`, so the map needs **no new data**.
- Violation text is NOT in the search index. Sources at app-build time:
  - `inspection_history.json` (committed, all cities): per-event `headline`
    = first violation only, truncated to ~100 chars.
  - `comments-by-license/` (synced from S3 by `prebuild-sync-s3.mjs`, deploy
    builds only, no committed fallback): full violation text per license,
    index-aligned with the history events.
- The Chicago index is 7.1 MB and must stay under CloudFront's 10 MB
  automatic-compression ceiling.
- `MapView` expects its `pins` prop pre-sorted (it takes the first N pins per
  zoom level for density capping) and takes a `center` prop, already wired to
  `CITY_CONFIG` per city.

## 1. Violation categories in the search index

Fixed 6-category taxonomy, shared across cities. Category `id` = bit position;
`slug` is the stable URL token; keyword lists are matched case-insensitively
against violation text.

| id | slug | Label | Example keywords (tuned during implementation) |
|---|---|---|---|
| 0 | pests | Pests and rodents | rodent, mice, mouse, rat, roach, insect, pest, vermin, flies |
| 1 | temp | Temperature control | temperature, cold holding, hot holding, cooling, refrigerat, thermometer |
| 2 | contamination | Contamination and food source | contaminat, protected, approved source, adulterat |
| 3 | hygiene | Hygiene and handwashing | handwash, soap, paper towel, bare hand, hygien |
| 4 | sanitizing | Cleaning and sanitizing | saniti, clean |
| 5 | facility | Facility and equipment | floor, wall, ceiling, plumbing, repair, garbage, toilet, ventilation |

Final keyword lists are tuned against real violation text from all three
cities during implementation, with per-city match-count sanity checks logged
by the generator (a category that matches 0% or ~100% of establishments in a
city signals a bad keyword).

**Tagging rule.** An establishment gets category `c` when the violation text
of its latest scored inspection matches any of `c`'s keywords. "Latest scored
inspection" = the history event whose date equals the row's `as_of_date`,
falling back to the newest history event when no exact date match exists.
This is the same inspection the score, drivers, and "last inspected N days
ago" column already describe.

**Text source per build mode.**

- Deploy (`prebuild`): full violation text for that event from
  `comments-by-license/<license_id>.json` (event-index-aligned), falling back
  to the event headline when the license has no comments file.
- Dev (`predev`): event headline only (first violation). The generator logs
  which mode produced the index.

**Format.** Each `search-index.json` row gains an optional bitmask field
`vc` (bit `i` set = category `i` present), omitted when zero — roughly
+250 KB on the Chicago index, safely under the 10 MB ceiling. TypeScript:
`SearchIndexRow.vc?: number`. Rows without `vc` never match a selected
category.

**Code layout.**

- Taxonomy (ids, slugs, labels, keywords) in one shared JSON file so the
  generator and the app UI cannot drift (generator reads keywords; app reads
  slugs + labels).
- The keyword matcher is a small plain-JS module under `app/scripts/lib/`,
  imported by `gen-search-index.mjs` and unit-tested with vitest.
- `gen-search-index.mjs` gains optional history-path and comments-dir inputs;
  `predev` passes history only, `prebuild` passes both (per city).

## 2. Filter UI on the Inspector tab

- New chip row in the existing controls area, captioned **"Violations at
  last inspection"**: six pills with per-category counts computed over active
  establishments (like tier counts), `aria-pressed`, styled like the existing
  tier/sort pills.
- Multi-select. **OR across selected categories, AND with the tier filter.**
  Nothing selected = no violation filter (default).
- URL param `?viol=<slug,slug>` (e.g. `?viol=pests,temp`). Unknown slugs are
  ignored; empty/absent = no filter. Changing the filter resets the queue
  pagination to the first page, matching tier-toggle behavior.
- Unlike the tier filter (where all four tiers = no-op), selecting **all six
  categories is NOT a no-op**: it still excludes establishments whose latest
  scored inspection recorded no matching violations. The param stays in the
  URL in that state.
- Filter pipeline: `activeRows` (open venues) → tier filter → violation
  filter → sort. The queue header's establishment count reflects the result.
- **Graceful degradation:** if no row in the loaded index has `vc` (older
  index), the chip row is hidden entirely — no dead controls.
- **New empty state** in the queue when zero rows match: "No establishments
  match these filters." (Today the panel renders nothing.)
- Stat cards, "Rising fast", and "Today's route" stay population-level
  (unchanged behavior).

## 3. Map view toggle

- **"List | Map" segmented toggle** in the queue panel header, same visual
  pattern as the Search tab's mobile Map/List toggle. URL param `?view=map`
  (absent = list).
- Map mode replaces the queue rows (inside the same panel/grid slot) with a
  map pane, roughly 70vh tall (exact height tuned during visual
  verification), min 480px. The sidebar stays.
- Reuses `MapView` unmodified: same tiles, tier-colored pins, zoom-aware
  density, popup (tier, score, name, address, top driver, "Open full record"
  link). Center/zoom from the active city's `CITY_CONFIG`.
- Pins = exactly the filtered rows (tier AND violation) that have
  coordinates, **ordered by the active sort**, so the density cap surfaces
  the same establishments as the top of the list (e.g. "Worsening fastest"
  puts trending pins on first).
- Mobile: same toggle; the map pane is full-width like the queue.
- **Non-goal (v1):** no "Add to route" from the map popup; route-building
  stays in the list view.

## 4. Testing and verification

- Vitest units: keyword matcher against real sample strings from all three
  cities; `?viol=` parse/serialize round-trip; filter composition (tier AND
  violation OR-set); `vc` bitmask encode/decode; latest-scored-event
  selection (exact `as_of_date` match + newest-event fallback).
- Per repo CLAUDE.md, `/verify` with real screenshots before merge: chip row
  and map view at desktop and ~390px mobile, combined filters, zero-result
  empty state, old-index degradation (chip row hidden), popup interaction,
  keyboard nav, WCAG AA contrast + non-color cues. All screenshots go in the
  PR description.

## 5. Explicitly unchanged

- No Python pipeline, `scores.json` contract, or S3 data changes.
- No new npm dependencies.
- `MapExplorer` (Search tab) untouched; `MapView` reused, not modified.
- Chat agent, detail page, and other routes untouched.
