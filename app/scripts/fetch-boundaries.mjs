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
    // Original ewy2-6yfk id 404s/returns an empty stub; qqq8-j68g is the
    // live "Boundaries - City" dataset id as of 2026-07 (confirmed via the
    // Socrata catalog search API against data.cityofchicago.org).
    note: '"Boundaries - City" dataset, Chicago Data Portal',
    url: "https://data.cityofchicago.org/resource/qqq8-j68g.geojson",
    eps: 0.0006,
  },
  {
    id: "nyc",
    // Original tqmj-j8zm id 404s; gthc-hcne is the live "Borough Boundaries"
    // dataset id as of 2026-07 (confirmed via the Socrata catalog search API
    // against data.cityofnewyork.us).
    note: '"Borough Boundaries" dataset, NYC Open Data',
    url: "https://data.cityofnewyork.us/resource/gthc-hcne.geojson",
    eps: 0.0015,
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
