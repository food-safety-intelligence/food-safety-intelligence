# Map City Boundaries (Clamp + Gray-Out Mask) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lock every map to the active city (maplibre `maxBounds` + per-city `minZoom`) and gray out everything outside the city's official boundary, so users are never confused why areas beyond Chicago/NYC/LA show no establishments.

**Architecture:** Committed, simplified official-boundary GeoJSONs (`app/public/data/boundaries/<city>.json`, produced once by a prep script) are fetched per city by `MapView`, inverted into a world-with-hole mask polygon by a pure helper, and rendered as maplibre fill + line layers. The pan/zoom clamp comes from new `CITY_CONFIG` constants, so it works even when the boundary fetch fails. Both maps (Search tab `MapExplorer`, Inspector `InspectorWorklist`) get the behavior by passing three new optional `MapView` props.

**Tech Stack:** Next.js 16 + React 19 + TypeScript strict, react-map-gl 8.1.1 (`react-map-gl/maplibre`: `Source`/`Layer` components, reactive `maxBounds`/`minZoom` Map props), maplibre-gl, vitest, plain-Node `.mjs` scripts. `@types/geojson` is already in the tree (transitively via maplibre-gl) — import GeoJSON types from `"geojson"`.

**Spec:** `docs/superpowers/specs/2026-07-17-map-city-boundaries-design.md` (approved). Branch: `jun/app-map-city-bounds`. All work in `app/` (plus this plan's docs).

## Global Constraints

- TypeScript `strict: true`, no `any` (type assertions at fetch boundaries are fine; validate via the mask helper).
- No new npm dependencies (maplibre `maxBounds` + GeoJSON layers are built in; simplification is plain JS).
- The repo uses **npm, not pnpm**: `npm test -- <file>`, `npm run lint`, `npx tsc --noEmit`, all from `app/`.
- No em dashes / emoji in user-facing copy (this feature adds none).
- Do NOT change pins, filters, search, data pipelines, or any schema. `MapExplorer`/`InspectorWorklist` change only to pass the three new props.
- LA's boundary is the **Los Angeles County** boundary (the data spans the county, including Catalina Island); Chicago and NYC are city limits.
- Each committed boundary file stays well under ~100 KB.
- Builds never touch the network: `fetch-boundaries.mjs` is run manually, its outputs committed.
- Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: `maskFromBoundary` pure helper

**Files:**
- Create: `app/src/lib/geo.ts`
- Test: `app/src/lib/geo.test.ts`

**Interfaces:**
- Consumes: nothing (leaf task). GeoJSON types from `"geojson"`.
- Produces: `maskFromBoundary(boundary: unknown): Feature<Polygon> | null` — world-sized outer ring with every exterior ring of the input as a hole; `null` for non-polygonal/garbage input. Task 4 renders its return value directly as a maplibre `Source` `data`.

- [ ] **Step 1: Write the failing tests**

Create `app/src/lib/geo.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { maskFromBoundary } from "./geo";

const ring = [
  [-88, 41.6],
  [-87.5, 41.6],
  [-87.5, 42.1],
  [-88, 42.1],
  [-88, 41.6],
];

describe("maskFromBoundary", () => {
  it("wraps a Polygon feature: world outer ring + boundary as hole", () => {
    const mask = maskFromBoundary({
      type: "Feature",
      properties: {},
      geometry: { type: "Polygon", coordinates: [ring] },
    });
    expect(mask).not.toBeNull();
    expect(mask?.geometry.coordinates).toHaveLength(2);
    expect(mask?.geometry.coordinates[0][0]).toEqual([-180, -85]);
    expect(mask?.geometry.coordinates[1]).toEqual(ring);
  });

  it("collects every exterior ring of a MultiPolygon FeatureCollection (LA islands)", () => {
    const island = [
      [-118.6, 33.3],
      [-118.3, 33.3],
      [-118.3, 33.5],
      [-118.6, 33.5],
      [-118.6, 33.3],
    ];
    const interiorHole = [
      [-87.9, 41.7],
      [-87.8, 41.7],
      [-87.8, 41.8],
      [-87.9, 41.8],
      [-87.9, 41.7],
    ];
    const mask = maskFromBoundary({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {},
          geometry: {
            type: "MultiPolygon",
            coordinates: [[ring, interiorHole], [island]],
          },
        },
      ],
    });
    // world ring + 2 exterior rings; the polygon's own interior ring is ignored
    expect(mask?.geometry.coordinates).toHaveLength(3);
    expect(mask?.geometry.coordinates[1]).toEqual(ring);
    expect(mask?.geometry.coordinates[2]).toEqual(island);
  });

  it("returns null for non-polygonal or garbage input", () => {
    expect(maskFromBoundary(null)).toBeNull();
    expect(maskFromBoundary("nope")).toBeNull();
    expect(maskFromBoundary({})).toBeNull();
    expect(
      maskFromBoundary({
        type: "Feature",
        properties: {},
        geometry: { type: "Point", coordinates: [0, 0] },
      }),
    ).toBeNull();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- src/lib/geo.test.ts`
Expected: FAIL — cannot resolve `./geo`.

- [ ] **Step 3: Write the implementation**

Create `app/src/lib/geo.ts`:

```ts
/**
 * Boundary-mask geometry for the city maps.
 *
 * The gray-out layer is an INVERTED polygon: a world-sized outer ring with the
 * city's exterior rings punched out as holes, so a translucent fill dims
 * everything OUTSIDE the boundary. Pure data-in/data-out so it is unit
 * testable without a map. GeoJSON types come from @types/geojson (already in
 * the tree via maplibre-gl).
 */

import type { Feature, FeatureCollection, Geometry, Polygon, Position } from "geojson";

// ±85 (not ±90) keeps the ring inside web-mercator's renderable range.
const WORLD_RING: Position[] = [
  [-180, -85],
  [180, -85],
  [180, 85],
  [-180, 85],
  [-180, -85],
];

function collectExteriorRings(geom: Geometry, out: Position[][]): void {
  if (geom.type === "Polygon") {
    if (geom.coordinates.length > 0) out.push(geom.coordinates[0]);
  } else if (geom.type === "MultiPolygon") {
    for (const poly of geom.coordinates) if (poly.length > 0) out.push(poly[0]);
  } else if (geom.type === "GeometryCollection") {
    for (const g of geom.geometries) collectExteriorRings(g, out);
  }
  // Points/lines can't bound an area — ignored.
}

/**
 * Build the inverted mask polygon from a boundary GeoJSON (Feature,
 * FeatureCollection, or bare Geometry). Interior rings (holes inside the
 * city itself) are ignored — none of the three cities has an enclave worth
 * re-dimming. Returns null when the input carries no polygonal geometry, so
 * a failed or garbled boundary fetch degrades to "no mask" upstream.
 */
export function maskFromBoundary(boundary: unknown): Feature<Polygon> | null {
  const b = boundary as { type?: unknown } | null;
  if (!b || typeof b !== "object" || typeof b.type !== "string") return null;

  const rings: Position[][] = [];
  if (b.type === "FeatureCollection") {
    for (const f of (b as FeatureCollection).features ?? []) {
      if (f?.geometry) collectExteriorRings(f.geometry, rings);
    }
  } else if (b.type === "Feature") {
    const f = b as Feature;
    if (f.geometry) collectExteriorRings(f.geometry, rings);
  } else {
    collectExteriorRings(b as Geometry, rings);
  }
  if (rings.length === 0) return null;
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "Polygon", coordinates: [WORLD_RING, ...rings] },
  };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- src/lib/geo.test.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint + typecheck + commit**

Run: `npm run lint && npx tsc --noEmit`
Expected: clean.

```bash
git add src/lib/geo.ts src/lib/geo.test.ts
git commit -m "feat(app): inverted-polygon boundary mask helper

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Per-city clamp constants + boundary URL helper

**Files:**
- Modify: `app/src/lib/city.ts` (the `CityConfig` interface, each of the three city blocks, and a new helper next to `dataUrl`)
- Test: `app/src/lib/city-bounds.test.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (used verbatim by Tasks 4-5): `CityConfig.maxBounds: [[number, number], [number, number]]`, `CityConfig.minZoom: number`, and `boundaryUrl(city: City): string` returning `/data/boundaries/<city>.json` (basePath-aware).

- [ ] **Step 1: Write the failing tests**

Create `app/src/lib/city-bounds.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { boundaryUrl, CITIES, CITY_CONFIG } from "./city";

describe("per-city map clamp config", () => {
  it.each(CITIES)("%s has well-formed bounds containing its center", (city) => {
    const cfg = CITY_CONFIG[city];
    const [[west, south], [east, north]] = cfg.maxBounds;
    expect(west).toBeLessThan(east);
    expect(south).toBeLessThan(north);
    expect(cfg.center.lon).toBeGreaterThan(west);
    expect(cfg.center.lon).toBeLessThan(east);
    expect(cfg.center.lat).toBeGreaterThan(south);
    expect(cfg.center.lat).toBeLessThan(north);
    // The default framing must be reachable under the floor.
    expect(cfg.minZoom).toBeLessThanOrEqual(cfg.zoom);
  });

  it("boundary urls are city-scoped committed assets (no data prefix)", () => {
    expect(boundaryUrl("chicago")).toBe("/data/boundaries/chicago.json");
    expect(boundaryUrl("nyc")).toBe("/data/boundaries/nyc.json");
    expect(boundaryUrl("la")).toBe("/data/boundaries/la.json");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- src/lib/city-bounds.test.ts`
Expected: FAIL — `boundaryUrl` not exported / `maxBounds` undefined.

- [ ] **Step 3: Extend the CityConfig interface**

In `app/src/lib/city.ts`, directly after the `zoom: number;` member of `interface CityConfig`, add:

```ts
  /** Hard camera clamp [[west, south], [east, north]] — padded ~15-25 km past
   * the boundary so the whole city fits AND a visible band of grayed-out
   * surroundings shows the mask edge. Constants (not derived from the
   * boundary fetch) so the clamp works even when the mask doesn't load. */
  maxBounds: [[number, number], [number, number]];
  /** Zoom-out floor. LA County is far larger than the two cities, so its
   * floor is lower. Must stay <= zoom (the default framing). */
  minZoom: number;
```

- [ ] **Step 4: Add the per-city values**

In each city block, directly after its `zoom:` line, add (values derived from the verified data extents in the spec, padded):

Chicago (`zoom: 10`):

```ts
    maxBounds: [
      [-88.15, 41.49],
      [-87.3, 42.17],
    ],
    minZoom: 8.5,
```

NYC (`zoom: 10`):

```ts
    maxBounds: [
      [-74.46, 40.35],
      [-73.5, 41.06],
    ],
    minZoom: 8.5,
```

LA (`zoom: 9`):

```ts
    maxBounds: [
      [-119.2, 33.1],
      [-117.4, 35.0],
    ],
    minZoom: 7.5,
```

- [ ] **Step 5: Add the boundaryUrl helper**

Directly after the existing `dataUrl` function in `app/src/lib/city.ts`, add:

```ts
/**
 * Committed city-boundary GeoJSON (an app asset shipped with the export, not
 * per-city S3 data — so it deliberately does NOT go through dataPrefix).
 */
export function boundaryUrl(city: City): string {
  const base = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
  return `${base}/data/boundaries/${city}.json`;
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `npm test -- src/lib/city-bounds.test.ts`
Expected: PASS. Then `npm test` (full suite) — no other test may break.

- [ ] **Step 7: Lint + typecheck + commit**

Run: `npm run lint && npx tsc --noEmit`
Expected: clean.

```bash
git add src/lib/city.ts src/lib/city-bounds.test.ts
git commit -m "feat(app): per-city map clamp constants + boundary asset urls

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Boundary prep script + the three committed GeoJSONs

**Files:**
- Create: `app/scripts/lib/simplify-geojson.mjs`
- Test: `app/scripts/lib/simplify-geojson.test.mjs`
- Create: `app/scripts/fetch-boundaries.mjs`
- Create (by running the script): `app/public/data/boundaries/{chicago,nyc,la}.json` — these ARE committed (verified not gitignored).

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: the three boundary files Task 4 fetches at runtime; `simplifyFeatureCollection(gj, eps, stamp)` used only inside this task.

- [ ] **Step 1: Write the failing simplifier tests**

Create `app/scripts/lib/simplify-geojson.test.mjs`:

```js
import { describe, expect, it } from "vitest";
import { simplifyFeatureCollection, thinRing } from "./simplify-geojson.mjs";

describe("thinRing", () => {
  it("drops sub-epsilon jitter but keeps the ring closed", () => {
    const ring = [
      [0, 0],
      [0.00001, 0.00001], // sub-eps jitter — dropped
      [1, 0],
      [1, 1],
      [0, 1],
      [0, 0],
    ];
    const out = thinRing(ring, 0.001);
    expect(out[0]).toEqual([0, 0]);
    expect(out[out.length - 1]).toEqual([0, 0]); // closed
    expect(out).toHaveLength(5); // 4 corners + closing point
  });

  it("rounds to 5 decimal places", () => {
    const out = thinRing(
      [
        [0.123456789, 0],
        [1, 1],
        [0.123456789, 0],
      ],
      0.0001,
    );
    expect(out[0]).toEqual([0.12346, 0]);
  });
});

describe("simplifyFeatureCollection", () => {
  const square = [
    [0, 0],
    [1, 0],
    [1, 1],
    [0, 1],
    [0, 0],
  ];

  it("keeps MultiPolygon islands and stamps provenance", () => {
    const island = [
      [5, 5],
      [6, 5],
      [6, 6],
      [5, 6],
      [5, 5],
    ];
    const out = simplifyFeatureCollection(
      {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            properties: { junk: 1 },
            geometry: { type: "MultiPolygon", coordinates: [[square], [island]] },
          },
        ],
      },
      0.001,
      { source: "http://example.com", fetched: "2026-07-17" },
    );
    expect(out.features).toHaveLength(1);
    expect(out.features[0].geometry.coordinates).toHaveLength(2); // both polys kept
    expect(out.features[0].properties).toEqual({
      source: "http://example.com",
      fetched: "2026-07-17",
    });
  });

  it("drops rings that collapse into slivers", () => {
    const sliver = [
      [0, 0],
      [0.0001, 0],
      [0.0001, 0.0001],
      [0, 0],
    ];
    const out = simplifyFeatureCollection(
      {
        type: "FeatureCollection",
        features: [
          { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [sliver] } },
        ],
      },
      0.01,
      {},
    );
    expect(out.features).toHaveLength(0); // geometry vanished -> feature dropped
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- scripts/lib/simplify-geojson.test.mjs`
Expected: FAIL — cannot resolve `./simplify-geojson.mjs`.

- [ ] **Step 3: Write the simplifier**

Create `app/scripts/lib/simplify-geojson.mjs`:

```js
/**
 * Plain-JS GeoJSON shrinker for the committed city-boundary files: round
 * coordinates to 5 decimals (~1 m) and thin ring vertices by radial distance.
 * No npm deps — this runs once from scripts/fetch-boundaries.mjs, never at
 * build or request time, so clarity beats cleverness.
 */

const PRECISION = 1e5; // 5 decimal places

function round(v) {
  return Math.round(v * PRECISION) / PRECISION;
}

/**
 * Keep a vertex only when it moved >= eps degrees (Chebyshev distance) from
 * the last kept vertex; the first point is always kept and re-appended so the
 * ring stays closed.
 */
export function thinRing(ring, eps) {
  if (!Array.isArray(ring) || ring.length === 0) return [];
  const out = [[round(ring[0][0]), round(ring[0][1])]];
  for (let i = 1; i < ring.length - 1; i += 1) {
    const [x, y] = ring[i];
    const [px, py] = out[out.length - 1];
    if (Math.max(Math.abs(x - px), Math.abs(y - py)) >= eps) {
      out.push([round(x), round(y)]);
    }
  }
  out.push([...out[0]]);
  return out;
}

// A ring needs 4 distinct points + closure to bound area; below this it is a
// degenerate sliver left over from thinning — drop it. (Catalina survives
// easily: it is tens of km across.)
const MIN_RING_POINTS = 5;

function simplifyRings(rings, eps) {
  return rings.map((r) => thinRing(r, eps)).filter((r) => r.length >= MIN_RING_POINTS);
}

function simplifyGeometry(geom, eps) {
  if (!geom) return null;
  if (geom.type === "Polygon") {
    const coordinates = simplifyRings(geom.coordinates, eps);
    return coordinates.length ? { type: "Polygon", coordinates } : null;
  }
  if (geom.type === "MultiPolygon") {
    const coordinates = geom.coordinates
      .map((rings) => simplifyRings(rings, eps))
      .filter((rings) => rings.length > 0);
    return coordinates.length ? { type: "MultiPolygon", coordinates } : null;
  }
  return null; // boundary sources are polygonal; anything else is dropped
}

/**
 * Simplify every feature, replace its properties with the provenance stamp
 * (source portal URL + fetch date), and drop features whose geometry
 * vanished. Accepts a bare Feature/geometry input by wrapping it.
 */
export function simplifyFeatureCollection(gj, eps, stamp) {
  const rawFeatures = gj.type === "FeatureCollection" ? (gj.features ?? []) : [gj];
  const features = rawFeatures
    .map((f) => (f.type === "Feature" ? f : { type: "Feature", properties: {}, geometry: f }))
    .map((f) => ({
      type: "Feature",
      properties: { ...stamp },
      geometry: simplifyGeometry(f.geometry, eps),
    }))
    .filter((f) => f.geometry !== null);
  return { type: "FeatureCollection", features };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- scripts/lib/simplify-geojson.test.mjs`
Expected: PASS (4 tests).

- [ ] **Step 5: Write the fetch script**

Create `app/scripts/fetch-boundaries.mjs`:

```js
#!/usr/bin/env node
/**
 * One-off prep: download each city's official boundary, simplify it to well
 * under ~100 KB, stamp provenance into feature properties, and write the
 * committed GeoJSONs the maps fetch at runtime
 * (public/data/boundaries/<city>.json).
 *
 * Run MANUALLY (never from the build): node scripts/fetch-boundaries.mjs
 * If a portal URL has rotted, find the dataset by the name in `note` on that
 * portal, update SOURCES, re-run, and commit the refreshed files.
 */

import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { simplifyFeatureCollection } from "./lib/simplify-geojson.mjs";

const OUT_DIR = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "public",
  "data",
  "boundaries",
);

// eps values chosen to land comfortably under the 100 KB budget; if a file
// prints larger, raise that city's eps slightly and re-run.
const SOURCES = [
  {
    id: "chicago",
    note: '"Boundaries - City" dataset, Chicago Data Portal',
    url: "https://data.cityofchicago.org/api/geospatial/ewy2-6yfk?method=export&format=GeoJSON",
    eps: 0.0006,
  },
  {
    id: "nyc",
    note: '"Borough Boundaries" dataset, NYC Open Data',
    url: "https://data.cityofnewyork.us/api/geospatial/tqmj-j8zm?method=export&format=GeoJSON",
    eps: 0.0006,
  },
  {
    id: "la",
    note: '"County Boundary", LA County eGIS hub (egis-lacounty.hub.arcgis.com)',
    url: "https://services.arcgis.com/RmCCgQtiZLDCtblq/arcgis/rest/services/LA_County_Boundary/FeatureServer/0/query?where=1%3D1&outFields=OBJECTID&f=geojson",
    eps: 0.0015,
  },
];

const KB_BUDGET = 100;

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  for (const { id, note, url, eps } of SOURCES) {
    const res = await fetch(url);
    if (!res.ok) {
      throw new Error(`${id}: HTTP ${res.status} from ${url} — ${note}`);
    }
    const raw = await res.json();
    const slim = simplifyFeatureCollection(raw, eps, {
      source: url,
      fetched: new Date().toISOString().slice(0, 10),
    });
    if (slim.features.length === 0) {
      throw new Error(`${id}: simplification left no polygons — check the source shape`);
    }
    const dest = path.join(OUT_DIR, `${id}.json`);
    const text = JSON.stringify(slim);
    await writeFile(dest, text, "utf-8");
    const kb = (text.length / 1024).toFixed(1);
    const flag = text.length / 1024 > KB_BUDGET ? "  <-- OVER BUDGET, raise eps" : "";
    console.log(`[boundaries] ${id}: ${slim.features.length} feature(s), ${kb} KB${flag}`);
  }
}

main().catch((err) => {
  console.error("[boundaries] FAILED:", err.message);
  process.exit(1);
});
```

- [ ] **Step 6: Run the script and sanity-check the outputs**

Run: `node scripts/fetch-boundaries.mjs`
Expected: three `[boundaries] <city>: ... KB` lines, all under 100 KB, no OVER BUDGET flag.

If a URL 404s (portals do reshuffle): open the named portal, search the dataset name in `note`, replace the `url` constant, and re-run. The LA entry is an ArcGIS FeatureServer query; any LA County boundary layer on the eGIS hub with `f=geojson` works. Record in your report which URLs (if any) you had to update.

Then verify shape + coverage:

```bash
node -e "
const fs = require('fs');
for (const c of ['chicago','nyc','la']) {
  const gj = JSON.parse(fs.readFileSync(\`public/data/boundaries/\${c}.json\`));
  let rings = 0, pts = 0;
  for (const f of gj.features) {
    const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
    for (const p of polys) { rings += p.length; for (const r of p) pts += r.length; }
  }
  console.log(c, gj.features.length, 'features', rings, 'rings', pts, 'points');
}"
```

Expected: every city >= 1 feature; LA has multiple rings (mainland + Catalina + San Clemente islands). If LA shows exactly 1 ring, the islands were lost — lower LA's eps and re-run.

- [ ] **Step 7: Full test run, lint, commit (script + data together)**

Run: `npm test && npm run lint`
Expected: clean.

```bash
git add scripts/lib/simplify-geojson.mjs scripts/lib/simplify-geojson.test.mjs scripts/fetch-boundaries.mjs public/data/boundaries
git commit -m "feat(app): committed city-boundary GeoJSONs + one-off fetch/simplify script

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: MapView clamp + mask layers

**Files:**
- Modify: `app/src/components/MapView.tsx`

**Interfaces:**
- Consumes: `maskFromBoundary` (Task 1).
- Produces: three new optional `MapView` props for Task 5: `maxBounds?: [[number, number], [number, number]]`, `minZoom?: number`, `boundaryUrl?: string`.

No new unit tests: the pure geometry is covered by Task 1, and this repo verifies rendering via `/verify` (Task 6). Steps are edit → static checks → dev smoke → commit.

- [ ] **Step 1: Imports and module-level cache**

In `app/src/components/MapView.tsx`, extend the react-map-gl import to include `Source` and `Layer`:

```tsx
import {
  Layer,
  Map,
  type MapRef,
  Marker,
  Popup,
  NavigationControl,
  Source,
  useMap,
} from "react-map-gl/maplibre";
```

Add after the existing lib imports:

```tsx
import { maskFromBoundary } from "@/lib/geo";
```

Add near the other module-level constants (e.g. right above `pinCapForZoom`):

```tsx
// City-boundary GeoJSON, cached per URL for the session (same pattern as the
// worklist's detail cache) — switching back to a city never refetches.
const boundaryCache = new Map<string, GeoJSON.GeoJSON>();
```

(`GeoJSON` is the ambient namespace from `@types/geojson`, already in the tree.)

- [ ] **Step 2: Extend the props**

Change the `MapView` signature to:

```tsx
export function MapView({
  pins,
  className = "",
  center = CHICAGO_CENTER,
  maxBounds,
  minZoom,
  boundaryUrl,
}: {
  pins: PinSummary[];
  className?: string;
  center?: { lat: number; lon: number; zoom: number };
  /** Hard camera clamp [[west, south], [east, north]] (CITY_CONFIG.maxBounds). */
  maxBounds?: [[number, number], [number, number]];
  /** Zoom-out floor (CITY_CONFIG.minZoom). */
  minZoom?: number;
  /** Committed city-boundary GeoJSON to gray out everything outside of. */
  boundaryUrl?: string;
}) {
```

- [ ] **Step 3: Boundary fetch + mask derivation**

Inside the component, after the existing `handleLoad` callback, add:

```tsx
  // The mask is decorative: on any failure the map still works and the clamp
  // (config constants) still applies — so errors skip silently, no retry UI.
  const [boundary, setBoundary] = useState<GeoJSON.GeoJSON | null>(
    boundaryUrl ? (boundaryCache.get(boundaryUrl) ?? null) : null,
  );
  useEffect(() => {
    if (!boundaryUrl) {
      setBoundary(null);
      return;
    }
    const cached = boundaryCache.get(boundaryUrl);
    // Reset immediately on a city switch so the OLD city's mask never sits on
    // the NEW city's map while the fetch is in flight.
    setBoundary(cached ?? null);
    if (cached) return;
    let alive = true;
    fetch(boundaryUrl)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((gj: GeoJSON.GeoJSON) => {
        boundaryCache.set(boundaryUrl, gj);
        if (alive) setBoundary(gj);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [boundaryUrl]);

  const mask = useMemo(() => maskFromBoundary(boundary), [boundary]);
```

- [ ] **Step 4: Wire the Map props and layers**

On the `<Map>` element, after `mapStyle={VOYAGER_STYLE as never}`, add:

```tsx
        maxBounds={maxBounds}
        minZoom={minZoom}
```

Inside the `<Map>` children, directly BEFORE `<NavigationControl ...>`, add:

```tsx
        {mask && (
          <Source id="city-mask" type="geojson" data={mask}>
            {/* Warm tint wash: outside stays faintly legible (roads leading
                in) but reads unmistakably as out of scope. Colour is not the
                only cue — the boundary line and the pan clamp carry it too. */}
            <Layer
              id="city-mask-fill"
              type="fill"
              paint={{ "fill-color": "#EDE6D8", "fill-opacity": 0.55 }}
            />
          </Source>
        )}
        {boundary && mask && (
          <Source id="city-boundary" type="geojson" data={boundary}>
            <Layer
              id="city-boundary-line"
              type="line"
              paint={{ "line-color": "#6B7280", "line-width": 1.5, "line-opacity": 0.5 }}
            />
          </Source>
        )}
```

(Markers/popups are DOM overlays and always render above canvas layers; the
mask sits over the raster tiles automatically since it is added after them.)

- [ ] **Step 5: Static checks + dev smoke**

Run: `npm run lint && npx tsc --noEmit && npm test`
Expected: clean (no MapView tests exist; the suite guards the libs).

Smoke (`npx next dev --port 3789`, NOT `npm run dev` — the predev hook is slow; data artifacts must already exist in the workspace): with no props passed yet by callers, http://localhost:3789/ must look exactly as before (props are optional). Stop the server.

- [ ] **Step 6: Commit**

```bash
git add src/components/MapView.tsx
git commit -m "feat(app): MapView camera clamp + city-boundary gray-out layers

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Wire both maps

**Files:**
- Modify: `app/src/components/MapExplorer.tsx` (the `<MapView ...>` call + the `@/lib/city` import)
- Modify: `app/src/components/InspectorWorklist.tsx` (the `<MapView ...>` call in the `view === "map"` branch + the `@/lib/city` import)

**Interfaces:**
- Consumes: `CITY_CONFIG[city].maxBounds` / `.minZoom` (Task 2), `boundaryUrl(city)` (Task 2), MapView props (Task 4).
- Produces: the user-visible feature.

- [ ] **Step 1: MapExplorer**

Extend the existing import from `"@/lib/city"` to include `boundaryUrl`:

```tsx
import { boundaryUrl, CITY_CONFIG, dataUrl } from "@/lib/city";
```

Change the `<MapView>` call to:

```tsx
          <MapView
            pins={pins}
            className="absolute inset-0"
            center={{
              lat: CITY_CONFIG[city].center.lat,
              lon: CITY_CONFIG[city].center.lon,
              zoom: CITY_CONFIG[city].zoom,
            }}
            maxBounds={CITY_CONFIG[city].maxBounds}
            minZoom={CITY_CONFIG[city].minZoom}
            boundaryUrl={boundaryUrl(city)}
          />
```

- [ ] **Step 2: InspectorWorklist**

Extend its `"@/lib/city"` import the same way (it currently imports `CITY_CONFIG, type City, dataUrl` — add `boundaryUrl`). In the `view === "map"` branch, change the `<MapView>` call to:

```tsx
              <MapView
                pins={mapPins}
                className="absolute inset-0"
                center={{
                  lat: CITY_CONFIG[city].center.lat,
                  lon: CITY_CONFIG[city].center.lon,
                  zoom: CITY_CONFIG[city].zoom,
                }}
                maxBounds={CITY_CONFIG[city].maxBounds}
                minZoom={CITY_CONFIG[city].minZoom}
                boundaryUrl={boundaryUrl(city)}
              />
```

- [ ] **Step 3: Static checks + dev smoke**

Run: `npm run lint && npx tsc --noEmit && npm test`
Expected: clean.

Smoke with `npx next dev --port 3789` (headless-browser recipe from prior task reports if needed):
- Home map: gray wash outside Chicago's boundary with a thin boundary line; dragging far away stops at the clamp; zooming out stops at the floor.
- Switch city to NYC, then LA (header toggle): map recenters, mask swaps (no Chicago mask flash over NYC), LA mask shows the county with Catalina un-dimmed.
- `/inspectors?view=map`: same behavior.
- Kill the dev server afterwards.

- [ ] **Step 4: Commit**

```bash
git add src/components/MapExplorer.tsx src/components/InspectorWorklist.tsx
git commit -m "feat(app): clamp + boundary mask on the search and inspector maps

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Verification + PR

**Files:** none expected (fixes only if verification finds problems).

- [ ] **Step 1: CI-equivalent checks**

From `app/`: `npm run lint && npx tsc --noEmit && npm test` — all clean.
From the repo root: `git diff --stat main...HEAD -- '*.py'` — expected empty (no Python on this branch).

- [ ] **Step 2: /verify screenshot pass**

Invoke the `verify` skill (auto-discovers `verifier-app`). Capture real PNGs at desktop (1440px) AND mobile (390px):

1. Home map, Chicago: mask + boundary line visible, pins render inside.
2. Chicago after attempting to drag to Milwaukee: camera clamped (screenshot of where it stops).
3. Chicago at maximum zoom-out: floor respected, city still fills the frame.
4. NYC: mask follows the five boroughs.
5. LA: county mask; Catalina Island visible and un-dimmed (zoom to it — inside bounds).
6. `/inspectors?view=map` with a violation filter active: mask + filtered pins coexist.
7. City switch sequence Chicago → LA: no stale-mask flash (capture right after switch).
8. Boundary-fetch failure degrade: temporarily rename `public/data/boundaries/chicago.json`, reload — map renders WITHOUT mask, clamp still active (try dragging); restore the file and confirm the mask returns. Report the commands used.

Report per-item honestly which were observed. Save screenshots under the session scratchpad `verify-map-bounds/` and list absolute paths.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin jun/app-map-city-bounds
gh pr create --base main --title "feat(app): clamp maps to city bounds + gray out beyond the boundary" --body "$(cat <<'EOF'
## Summary
- Maps now lock panning/zooming to the active city (maplibre maxBounds + per-city minZoom from CITY_CONFIG) so users can't wander to unscored areas.
- Everything outside the city's official boundary is dimmed by an inverted-polygon mask with a thin boundary line; LA masks at the Los Angeles County line (the data spans the county, Catalina included), Chicago/NYC at city limits.
- Boundary polygons are committed simplified GeoJSONs from official portals (Chicago Data Portal, NYC Open Data, LA County eGIS), produced by a one-off committed script; builds never fetch them.
- Mask is decorative-and-degradable: if its fetch fails the map renders as before while the clamp (config constants) still applies.
- Both maps get it: the Search tab and the Inspector worklist map view share MapView.
- Spec: docs/superpowers/specs/2026-07-17-map-city-boundaries-design.md

## Verification
- vitest: mask inversion (Polygon/MultiPolygon/garbage), simplifier (thinning, closure, sliver-drop, provenance stamp), per-city bounds sanity (center inside bounds, minZoom <= zoom)
- /verify screenshots: [drag the captured screenshots in here]

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Then ask Jun to drag the screenshots into the PR description (private repo; attachment store required for inline rendering). Default reviewer: Arun (web-app backup owner). Merging deploys production.

---

## Self-review (done at plan-writing time)

- **Spec coverage:** boundary data + prep script + provenance (Task 3), config clamp constants (Task 2), MapView props/mask/line/failure-degrade/cache/city-switch reset (Task 4), both callers (Task 5), mask helper + multipolygon (Task 1), tests + /verify items incl. Catalina and fetch-failure degrade (Tasks 1-3, 6). LA-county decision encoded in Task 3 sources + Task 6 checklist.
- **Placeholder scan:** the portal URLs carry an explicit rot-fallback procedure (find dataset by name, update constant, report) — deliberate, not a TBD. No other placeholders; all code steps carry full code.
- **Type consistency:** `maskFromBoundary(boundary: unknown): Feature<Polygon> | null` (Task 1) matches Task 4's usage; `maxBounds`/`minZoom`/`boundaryUrl` names identical across Tasks 2, 4, 5; `simplifyFeatureCollection(gj, eps, stamp)` matches between Task 3's lib, tests, and fetch script.
