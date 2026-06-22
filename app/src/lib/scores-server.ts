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
import { GetObjectCommand, S3Client } from "@aws-sdk/client-s3";
import type {
  HomeListRow,
  HomeSort,
  HomeView,
  InspectionEvent,
  PinSummary,
  PopulationStats,
  RestaurantScore,
  RiskTier,
  ScoresPayload,
} from "@/lib/scores";
import { isAllTiers, matchesQuery, toPinDriver } from "@/lib/scores";

// S3 source of truth for the precomputed JSONs. Credentials resolve via the
// AWS SDK's default chain: env vars → ~/.aws/credentials → the SSR runtime's
// attached IAM role on Amplify. No keys live in this repo.
const S3_BUCKET = process.env.FSI_S3_BUCKET ?? "food-safety-intelligence-data";
const S3_REGION = process.env.AWS_REGION ?? "us-east-1";
const S3_PREFIX = "web-app-data";

const s3 = new S3Client({ region: S3_REGION });

async function fetchS3Text(key: string): Promise<string> {
  const res = await s3.send(
    new GetObjectCommand({ Bucket: S3_BUCKET, Key: `${S3_PREFIX}/${key}` }),
  );
  if (!res.Body) {
    throw new Error(`S3 returned empty body for ${S3_PREFIX}/${key}`);
  }
  return res.Body.transformToString();
}

// Cached in module scope to avoid re-fetching on every render. A production
// build of Next.js calls server modules per request; this cache holds for
// the lifetime of the worker process.
let cached: ScoresPayload | null = null;
let cachedStats: PopulationStats | null = null;

/**
 * Fetch the precomputed scores JSON from S3 (s3://<bucket>/web-app-data/
 * scores.json). On failure, fall back to the synthetic mock fixture so a
 * fresh clone with no AWS creds still renders. The mock carries
 * `is_mock=true` and the app renders the yellow demo banner based on that
 * flag — visible signal that something below isn't right.
 */
export async function loadScores(): Promise<ScoresPayload> {
  if (cached) return cached;

  let raw: string;
  try {
    raw = await fetchS3Text("scores.json");
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.warn(
      `[scores-server] S3 fetch failed for scores.json, falling back to mock: ${msg}`,
    );
    const mockPath = path.join(
      process.cwd(),
      "public",
      "data",
      "scores_mock.json",
    );
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

  augmentWithPercentiles(payload);

  cached = payload;
  return cached;
}

/**
 * Compute each restaurant's percentile rank in the full distribution, plus
 * population aggregate stats (median, mean). Mutates `payload.scores` in
 * place by setting `percentile_rank` on each row, and stashes the stats in
 * module-level `cachedStats`.
 *
 * O(N log N) sort + O(N log N) binary searches. Runs once per cold start.
 */
function augmentWithPercentiles(payload: ScoresPayload): void {
  const sorted = payload.scores
    .map((r) => r.risk_score)
    .slice()
    .sort((a, b) => a - b);
  const n = sorted.length;
  if (n === 0) return;

  const rankBelow = (v: number): number => {
    let lo = 0;
    let hi = n;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if (sorted[mid] < v) lo = mid + 1;
      else hi = mid;
    }
    return lo;
  };

  let sum = 0;
  for (const r of payload.scores) {
    r.percentile_rank = (rankBelow(r.risk_score) / n) * 100;
    sum += r.risk_score;
  }
  cachedStats = {
    total: n,
    median: sorted[Math.floor(n / 2)],
    mean: sum / n,
  };
}

export async function getPopulationStats(): Promise<PopulationStats> {
  if (!cachedStats) {
    await loadScores();
  }
  if (!cachedStats) {
    // Empty dataset fallback. The web app degrades to a sensible default.
    return { total: 0, median: 0, mean: 0 };
  }
  return cachedStats;
}

async function loadInspectionHistory(): Promise<
  Record<string, InspectionEvent[]>
> {
  try {
    const raw = await fetchS3Text("inspection_history.json");
    return JSON.parse(raw) as Record<string, InspectionEvent[]>;
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    console.warn(
      `[scores-server] S3 fetch failed for inspection_history.json: ${msg}`,
    );
    // Missing file is expected on a fresh clone before AWS creds are set
    // up. The UI falls back to "0 inspections" — degraded but functional.
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

// Lean pin record for the home map — every matching establishment with valid
// lat/lon. Sorted by risk_score descending so the map's zoom-aware density
// surfaces the most prominent first.
function pinFromScore(r: RestaurantScore): PinSummary {
  // #1 driver in compact form so the map popup can answer "what's driving this".
  const d = r.top_drivers[0];
  return {
    license_id: r.license_id,
    dba_name: r.dba_name,
    address: r.address,
    lat: r.lat,
    lon: r.lon,
    risk_score: r.risk_score,
    risk_tier: r.risk_tier,
    top_driver: d ? toPinDriver(d) : undefined,
  };
}

function hasCoords(r: RestaurantScore): boolean {
  return (
    r.lat != null &&
    r.lon != null &&
    !Number.isNaN(r.lat) &&
    !Number.isNaN(r.lon)
  );
}

/**
 * Apply the home page's URL state (search query, tier filter, sort) to the
 * full scored population, server-side. Returns the capped side-list AND the
 * filtered map pins so the client shell is purely presentational — all
 * filtering happens here, not in the browser. This is what makes search reach
 * every establishment (incl. the ~0.5% with no coordinates, which never make
 * it into the map-pin set) instead of only the top-N shipped to the client.
 *
 * Still reads the precomputed scores.json only — no live data, no model call.
 */
export async function getHomeView(opts: {
  q: string;
  tiers: RiskTier[];
  sort: HomeSort;
  listLimit?: number;
}): Promise<HomeView> {
  const { q, tiers, sort } = opts;
  const listLimit = opts.listLimit ?? 200;
  const payload = await loadScores();

  const query = q.trim().toLowerCase();
  const tierSet = new Set(tiers);
  const tierActive = !isAllTiers(tiers);

  // One pass over the full population: keep rows matching tier + query.
  const matched = payload.scores.filter(
    (r) =>
      (!tierActive || tierSet.has(r.risk_tier)) && matchesQuery(r, query),
  );

  // List: sort by the chosen key, then cap. Name surfaces all tiers
  // alphabetically; "low" surfaces the lowest-risk end; default is highest-risk.
  const sorted = matched.slice().sort((a, b) => {
    if (sort === "name") return a.dba_name.localeCompare(b.dba_name);
    if (sort === "low") return a.risk_score - b.risk_score;
    return b.risk_score - a.risk_score;
  });
  const listRows: HomeListRow[] = sorted.slice(0, listLimit).map((r) => {
    // Carry the #1 driver (compact) so list rows can show "what's driving this".
    const d = r.top_drivers[0];
    return {
      license_id: r.license_id,
      dba_name: r.dba_name,
      address: r.address,
      risk_score: r.risk_score,
      risk_tier: r.risk_tier,
      trend_slope_90d: r.trend_slope_90d,
      top_driver: d ? toPinDriver(d) : undefined,
    };
  });

  // Map pins: the matches that have coordinates. MapView surfaces the first N
  // by array order at low zoom, so order them to match the list — lowest-risk
  // first in "low" mode (the map goes green), highest-risk first otherwise —
  // so the map and the side list never contradict each other.
  const pins: PinSummary[] = matched
    .filter(hasCoords)
    .sort((a, b) =>
      sort === "low" ? a.risk_score - b.risk_score : b.risk_score - a.risk_score,
    )
    .map(pinFromScore);

  return {
    listRows,
    pins,
    matchCount: matched.length,
    total: payload.totals.establishments,
    tierCounts: payload.totals.tier_counts,
    listLimit,
  };
}
