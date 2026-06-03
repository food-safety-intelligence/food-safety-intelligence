/**
 * Server-only data loaders. NEVER import this file from a "use client"
 * component — it uses `node:fs` and will break the client bundle.
 *
 * The pure types and pure helpers live in `scores.ts`, which is safe in both
 * contexts.
 */

import "server-only";
import { promises as fs } from "node:fs";
import path from "node:path";
import type {
  InspectionEvent,
  PinSummary,
  RestaurantScore,
  ScoresPayload,
} from "@/lib/scores";

// Cached in module scope to avoid re-reading the file on every render. A
// production build of Next.js calls server modules per request; this cache
// holds for the lifetime of the worker process.
let cached: ScoresPayload | null = null;

/**
 * Prefer the real scores.json (written by the Python pipeline's notebook 06)
 * when it exists; fall back to the synthetic mock fixture otherwise. The
 * mock carries `is_mock=true` and the app renders the yellow demo banner
 * based on that flag — so promoting from mock to real is just dropping a
 * file in `public/data/`.
 */
export async function loadScores(): Promise<ScoresPayload> {
  if (cached) return cached;

  const realPath = path.join(process.cwd(), "public", "data", "scores.json");
  const mockPath = path.join(process.cwd(), "public", "data", "scores_mock.json");

  let raw: string;
  try {
    raw = await fs.readFile(realPath, "utf-8");
  } catch {
    raw = await fs.readFile(mockPath, "utf-8");
  }
  const payload = JSON.parse(raw) as ScoresPayload;

  // scores.json from the Python pipeline doesn't include an
  // `inspection_history` map (would balloon the payload from 18MB to ~60MB
  // in one file). The history lives in a sidecar file written by
  // `scripts/export_inspection_history.py`. Load it once on first scores
  // fetch and merge it in.
  if (!payload.inspection_history) {
    payload.inspection_history = await loadInspectionHistory();
  }

  cached = payload;
  return cached;
}

async function loadInspectionHistory(): Promise<
  Record<string, InspectionEvent[]>
> {
  const historyPath = path.join(
    process.cwd(),
    "public",
    "data",
    "inspection_history.json",
  );
  try {
    const raw = await fs.readFile(historyPath, "utf-8");
    return JSON.parse(raw) as Record<string, InspectionEvent[]>;
  } catch {
    // Missing file is expected on a fresh clone before the Python pipeline
    // runs. The UI falls back to "0 inspections" — degraded but functional.
    return {};
  }
}

export async function getRestaurant(
  licenseId: string,
): Promise<RestaurantScore | null> {
  const payload = await loadScores();
  return payload.scores.find((s) => s.license_id === licenseId) ?? null;
}

export async function getInspectionHistory(
  licenseId: string,
): Promise<InspectionEvent[]> {
  const payload = await loadScores();
  return payload.inspection_history[licenseId] ?? [];
}

let cachedPins: PinSummary[] | null = null;

/**
 * Minimal pin set for the home map — every restaurant with valid lat/lon.
 * Derived from the full scores payload server-side so the RSC sends only
 * what the map needs. Sorted by risk_score descending so the client can
 * use array position as a prominence rank when filtering by zoom level.
 */
export async function getMapPins(): Promise<PinSummary[]> {
  if (cachedPins) return cachedPins;
  const payload = await loadScores();
  cachedPins = payload.scores
    .filter(
      (r) =>
        r.lat != null &&
        r.lon != null &&
        !Number.isNaN(r.lat) &&
        !Number.isNaN(r.lon),
    )
    .map<PinSummary>((r) => ({
      license_id: r.license_id,
      dba_name: r.dba_name,
      address: r.address,
      lat: r.lat,
      lon: r.lon,
      risk_score: r.risk_score,
      risk_tier: r.risk_tier,
    }))
    .sort((a, b) => b.risk_score - a.risk_score);
  return cachedPins;
}
