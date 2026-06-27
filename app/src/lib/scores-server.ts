/**
 * Server-only data loaders. NEVER import this file from a "use client"
 * component — it uses `node:fs` and will break the client bundle.
 *
 * The pure types and pure helpers live in `scores.ts`, which is safe in both
 * contexts.
 */

import "server-only";
import crypto from "node:crypto";
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
// Shared with scripts/prebuild-sync-s3.mjs. During `next build --webpack`
// the prebuild step downloads scores.json + inspection_history.json once
// into this directory, then the parallel SSR workers read from here instead
// of hitting S3 N times.
const BUILD_CACHE_DIR = "/tmp/fsi-build-cache";
// Per-license inspection-history shards (scripts/shard-history.mjs), so a
// detail page reads only its own slice instead of the whole 45 MB map.
const HISTORY_SHARD_DIR = path.join(BUILD_CACHE_DIR, "history");

const s3 = new S3Client({ region: S3_REGION });

async function fetchS3Text(key: string): Promise<string> {
  // Build-time cache first; avoids 10 workers each downloading 18 MB.
  const cachePath = path.join(BUILD_CACHE_DIR, key);
  try {
    return await fs.readFile(cachePath, "utf-8");
  } catch {
    // No cache file — fall through to a live S3 fetch (dev workflow).
  }
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
    // Local fallbacks for a build without AWS creds: the committed
    // scores.json first (real data), then the synthetic mock (demo banner).
    try {
      raw = await fs.readFile(
        path.join(process.cwd(), "public", "data", "scores.json"),
        "utf-8",
      );
      console.warn(
        `[scores-server] S3 fetch failed for scores.json, using local committed copy: ${msg}`,
      );
    } catch {
      console.warn(
        `[scores-server] S3 + local scores.json failed, falling back to mock: ${msg}`,
      );
      raw = await fs.readFile(
        path.join(process.cwd(), "public", "data", "scores_mock.json"),
        "utf-8",
      );
    }
  }
  const payload = JSON.parse(raw) as ScoresPayload;

  // NB: we deliberately do NOT merge the ~45 MB inspection_history map into the
  // cached payload. The static export pre-renders ~500 detail pages in parallel
  // workers; holding the whole map resident in each worker exhausts memory and
  // crashes `next build`. Instead `getInspectionHistory` reads a per-license
  // shard (scripts/shard-history.mjs), so each page loads only its own slice.

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

// Whether the per-license shard directory exists (checked once). When the
// prebuild/predev shard step ran, we read slices from it; otherwise we fall
// back to loading the whole map once.
let shardDirChecked = false;
let shardDirExists = false;
let fullHistoryFallback: Record<string, InspectionEvent[]> | null = null;

async function hasHistoryShards(): Promise<boolean> {
  if (!shardDirChecked) {
    shardDirChecked = true;
    try {
      shardDirExists = (await fs.stat(HISTORY_SHARD_DIR)).isDirectory();
    } catch {
      shardDirExists = false;
    }
  }
  return shardDirExists;
}

// Fallback only: load the whole history map once if the shard step didn't run
// (e.g. `next build` invoked without the prebuild). Accepts the memory cost so
// the page still works; the normal path is per-license shards.
async function loadFullHistoryMap(): Promise<
  Record<string, InspectionEvent[]>
> {
  try {
    const raw = await fetchS3Text("inspection_history.json");
    return JSON.parse(raw) as Record<string, InspectionEvent[]>;
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    // Local fallback so a build without AWS creds renders real history (the
    // committed copy). Only a fresh clone missing both degrades to "0
    // inspections" — functional but empty.
    try {
      const raw = await fs.readFile(
        path.join(process.cwd(), "public", "data", "inspection_history.json"),
        "utf-8",
      );
      return JSON.parse(raw) as Record<string, InspectionEvent[]>;
    } catch {
      console.warn(
        `[scores-server] S3 + local inspection_history.json failed: ${msg}`,
      );
      return {};
    }
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
  if (await hasHistoryShards()) {
    try {
      const raw = await fs.readFile(
        path.join(HISTORY_SHARD_DIR, `${licenseId}.json`),
        "utf-8",
      );
      return JSON.parse(raw) as InspectionEvent[];
    } catch {
      // No shard for this license → no inspections on record.
      return [];
    }
  }
  // No shard directory: load the whole map once (degraded fallback).
  if (!fullHistoryFallback) fullHistoryFallback = await loadFullHistoryMap();
  return fullHistoryFallback[licenseId] ?? [];
}

// Full violation-comment text lives in sharded sidecars
// (web-app-data/comments/<xx>.json), keyed by license_id, each value an array
// index-aligned to that license's inspection_history events. The text is too
// large (~277MB) for one file, so each shard holds ~1/256th and we load only
// the shards the static build's pages touch. Shards are cached per process.
const commentShards = new Map<string, Record<string, string[]>>();

// Must match `_shard_of` in scripts/export_inspection_history.py: first two
// md5 hex chars of the license_id → one of 256 even buckets.
function commentShardOf(licenseId: string): string {
  return crypto.createHash("md5").update(licenseId).digest("hex").slice(0, 2);
}

async function loadCommentShard(
  shard: string,
): Promise<Record<string, string[]>> {
  const cached = commentShards.get(shard);
  if (cached) return cached;

  let parsed: Record<string, string[]> = {};
  try {
    parsed = JSON.parse(
      await fetchS3Text(`comments/${shard}.json`),
    ) as Record<string, string[]>;
  } catch (s3Err) {
    // Local fallback: a fresh clone / local build with no AWS creds reads the
    // shards the exporter wrote under public/data/comments/ (gitignored).
    try {
      const localPath = path.join(
        process.cwd(),
        "public",
        "data",
        "comments",
        `${shard}.json`,
      );
      parsed = JSON.parse(
        await fs.readFile(localPath, "utf-8"),
      ) as Record<string, string[]>;
    } catch {
      const msg = s3Err instanceof Error ? s3Err.message : String(s3Err);
      console.warn(
        `[scores-server] comment shard ${shard} unavailable (S3 + local miss): ${msg}`,
      );
    }
  }
  commentShards.set(shard, parsed);
  return parsed;
}

/**
 * Full comment text per inspection for one license, index-aligned to
 * getInspectionHistory(licenseId). Empty array if the shard is missing; an
 * empty string at index i means that inspection recorded no comments.
 */
export async function getInspectionComments(
  licenseId: string,
): Promise<string[]> {
  const shard = await loadCommentShard(commentShardOf(licenseId));
  return shard[licenseId] ?? [];
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
