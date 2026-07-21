# Map city boundaries: pan/zoom clamp + gray-out mask — design

Date: 2026-07-17
Owner: Jun (app workstream)
Status: approved in brainstorming session; awaiting implementation plan
Branch: `jun/app-map-city-bounds`

## Goal

The app serves exactly three cities, but the maps let users pan to Milwaukee or
San Diego and see an unexplained empty map. Two changes, applied to every map
in the app (the Search tab and the Inspector worklist's map view share
`MapView`, so both get it automatically):

1. **Clamp** panning/zooming to the active city: maplibre `maxBounds` plus a
   per-city `minZoom` floor.
2. **Gray out** everything outside the city's administrative boundary, so the
   coverage area is visually explicit.

## Decisions made (with Jun)

- **Real administrative boundaries**, not rectangles: the mask follows official
  boundary polygons (e.g. Evanston dims, Rogers Park does not).
- **LA uses the Los Angeles County boundary.** Verified in the data: the LA
  index spans the whole county (Avalon/Catalina 263 rows, Long Beach 200,
  Lancaster 37, Pasadena 11). Chicago and NYC use true city limits (NYC = the
  five boroughs).
- Committed static GeoJSON fetched per city at runtime (not bundled, not
  computed from data hulls).

## Data verified during exploration

- Chicago index extent: lat 41.645..42.021, lon −87.907..−87.525 (matches city
  limits).
- NYC index contains junk (0,0) coordinates on a small share of rows; the
  bounds clamp makes them permanently invisible (a side benefit, not a goal —
  the data bug stays as-is).
- LA index extent: lat 33.335..34.818, lon −118.911..−117.694 (county-wide,
  including Catalina Island — the boundary GeoJSON must be multipolygon-aware).

## 1. Boundary data

- New committed files: `app/public/data/boundaries/{chicago,nyc,la}.json`,
  GeoJSON, simplified to well under ~100 KB each.
- Sources (official portals): Chicago Data Portal "Boundaries - City"; NYC
  Open Data "Borough Boundaries"; LA County GIS county boundary.
- A committed one-off prep script `app/scripts/fetch-boundaries.mjs` downloads,
  simplifies (coordinate-precision reduction + point thinning; no new npm
  deps), stamps `properties.source` (URL) and `properties.fetched` (date) into
  each file, and writes the three outputs. It is run manually during
  implementation and whenever a boundary needs refreshing; builds never touch
  the network.
- Files ship with the static export like the rest of `public/data/` (same-origin
  fetch in dev and behind CloudFront in prod).

## 2. Config: per-city clamp constants (`app/src/lib/city.ts`)

`CityConfig` gains:

- `maxBounds: [[west, south], [east, north]]` — a box padded roughly 15-25 km
  beyond the boundary, so the whole city fits at the default zoom AND a visible
  band of grayed-out surroundings proves the mask exists.
- `minZoom: number` — per city; LA County is far larger, so its floor is lower
  (order of 7.5) than Chicago/NYC (order of 9). Exact values tuned during
  visual verification.

These are plain constants: the clamp works even if the boundary fetch fails.

## 3. MapView changes (`app/src/components/MapView.tsx`)

New optional props, passed by callers from `CITY_CONFIG` so `MapView` itself
stays city-agnostic:

- `maxBounds?: [[number, number], [number, number]]` and `minZoom?: number` —
  forwarded to the maplibre `Map` (react-map-gl supports both reactively);
  they update on city switch alongside the existing `flyTo` recenter (the new
  city's center is always inside its own bounds, so the animation cannot fight
  the clamp).
- `boundaryUrl?: string` — e.g. `/data/boundaries/chicago.json`. MapView
  fetches it on first use (cached per URL, module-level, like the detail-bundle
  cache pattern), passes it through a pure helper `maskFromBoundary(geojson)`,
  and renders the result via react-map-gl `Source` + two `Layer`s:
  - **Mask fill**: an inverted polygon — world-sized outer ring with the
    boundary's exterior rings as holes (multipolygon-aware for LA's islands) —
    warm gray from the existing palette at ~55-60% opacity: outside areas stay
    faintly legible (roads leading in) but read unmistakably as out of scope.
  - **Boundary line**: thin muted outline of the boundary itself so the edge
    reads even where the tile background is busy.
- Failure behavior: boundary fetch error → no mask, map otherwise normal (the
  clamp still applies since it comes from config). No retry UI; a console-level
  silent skip matches how secondary data is treated elsewhere.

`maskFromBoundary` lives in `app/src/lib/` as a pure exported function (unit
testable without a map).

## 4. Callers

- `MapExplorer` (Search tab) and `InspectorWorklist` (map view) pass
  `maxBounds`, `minZoom`, and `boundaryUrl` from the active city's config.
  No other behavioral changes to either component.

## 5. Testing and verification

- Vitest: `maskFromBoundary` with Polygon and MultiPolygon fixtures (outer
  ring + holes structure, all exterior rings become holes); a config test that
  each city's `center` lies inside its `maxBounds` and `minZoom <= zoom`.
- Per repo rules, `/verify` with real screenshots before merge: for each of
  the three cities — mask visible with the boundary edge on screen, pan clamp
  (attempt to drag away, map stops), zoom floor, both maps (Search + Inspector
  `?view=map`), desktop and ~390px mobile. Screenshots go in the PR
  description.

## 6. Explicitly unchanged

- No new npm dependencies (maplibre `maxBounds` + GeoJSON fill layers are
  built-in; simplification is done by the prep script with plain JS).
- No pin, filter, search, or data-pipeline changes; no `scores.json` /
  search-index schema changes.
- No dark-mode variant (the app is single-theme).
- The NYC (0,0) data bug is hidden by the clamp but not fixed here.
