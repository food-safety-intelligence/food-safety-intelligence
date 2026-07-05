#!/usr/bin/env node
/**
 * Build the per-license detail data the client-rendered detail page fetches.
 *
 * Why: the detail page is a single statically-exported shell (`/restaurant/?id=`)
 * that fetches one establishment's data in the browser, instead of pre-rendering
 * a page per establishment. That keeps the build O(1) in establishment count —
 * pre-rendering all ~23.6k pages took 20+ minutes. The trade is that every
 * establishment is now reachable (the old build capped at the top-500 by risk,
 * so the Low / A–Z tabs and most map pins 404'd).
 *
 * Output (under <out-dir>, default public/data — copied into out/ by `next build`
 * and served same-origin, exactly like search-index.json):
 *   detail/<license_id>.json   { restaurant, history, comments }
 *   detail-globals.json        { is_mock, calibration, populationStats }
 *
 * `restaurant.percentile_rank` and `populationStats` are precomputed here (the
 * server used to compute them at request time over the full distribution); the
 * client has only one license, so they must be baked in.
 *
 * Usage: node scripts/build-detail-data.mjs <scores.json> <inspection_history.json> [comments-by-license-dir] [out-dir]
 */

import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";

const scoresPath = process.argv[2];
const historyPath = process.argv[3];
const commentsDir = process.argv[4] || null;
const outDir = process.argv[5] || "public/data";
if (!scoresPath || !historyPath) {
  console.error(
    "usage: build-detail-data.mjs <scores.json> <inspection_history.json> [comments-by-license-dir] [out-dir]",
  );
  process.exit(1);
}

// Verify fast-path: FSI_DETAIL_ONLY=<id,id,...> generates ONLY those establishments'
// bundles (plus detail-globals). Generating one bundle per establishment is the
// slowest step of a build — tens of thousands of tiny file writes — and a UI
// (JS-only) change needs just a handful of test venues to observe. This flag turns
// a ~13-minute regen into seconds for verification. It is NOT for deploys, which
// must build every establishment's bundle so every venue is reachable; leave it
// unset there. percentile_rank + populationStats are still computed over the FULL
// population so the sampled bundles carry correct ranks.
const onlyIds = (process.env.FSI_DETAIL_ONLY ?? "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
const onlySet = onlyIds.length ? new Set(onlyIds) : null;

/** Percentile rank of each score in the full population + aggregate stats. */
function computePercentiles(scores) {
  const sorted = scores.map((r) => r.risk_score).sort((a, b) => a - b);
  const n = sorted.length;
  const stats = { total: n, median: 0, mean: 0 };
  if (n === 0) return stats;

  // First index whose value is >= v (binary search over the sorted scores).
  const rankBelow = (v) => {
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
  for (const r of scores) {
    r.percentile_rank = (rankBelow(r.risk_score) / n) * 100;
    sum += r.risk_score;
  }
  stats.median = sorted[Math.floor(n / 2)];
  stats.mean = sum / n;
  return stats;
}

async function readComments(licenseId) {
  if (!commentsDir) return [];
  try {
    return JSON.parse(
      await readFile(path.join(commentsDir, `${licenseId}.json`), "utf-8"),
    );
  } catch {
    // No comment file for this license → no comments on record.
    return [];
  }
}

async function main() {
  const t0 = Date.now();
  const payload = JSON.parse(await readFile(scoresPath, "utf-8"));
  const history = JSON.parse(await readFile(historyPath, "utf-8"));
  const scores = payload.scores ?? [];

  // Percentiles/populationStats are computed over the FULL population even in
  // --only mode, so a sampled bundle's rank is still correct.
  const populationStats = computePercentiles(scores);
  const toWrite = onlySet ? scores.filter((r) => onlySet.has(r.license_id)) : scores;

  const detailDir = path.join(outDir, "detail");
  // Full runs start clean so a stale bundle from an older data version can't
  // linger. --only runs write alongside whatever is already there (they're a
  // verify sample, not the authoritative full set), so they must NOT wipe.
  if (!onlySet) await rm(detailDir, { recursive: true, force: true });
  await mkdir(detailDir, { recursive: true });

  // Bounded-concurrency batches — 23.6k tiny files at once would exhaust file
  // descriptors. Comments are read per-license inside the batch (small slices),
  // so the 266 MB comment corpus is never held resident.
  const BATCH = 256;
  for (let i = 0; i < toWrite.length; i += BATCH) {
    const batch = toWrite.slice(i, i + BATCH);
    await Promise.all(
      batch.map(async (restaurant) => {
        const id = restaurant.license_id;
        const bundle = {
          restaurant,
          history: history[id] ?? [],
          comments: await readComments(id),
        };
        await writeFile(
          path.join(detailDir, `${id}.json`),
          JSON.stringify(bundle),
          "utf-8",
        );
      }),
    );
  }

  await writeFile(
    path.join(outDir, "detail-globals.json"),
    JSON.stringify({
      is_mock: payload.is_mock ?? false,
      calibration: payload.calibration ?? null,
      populationStats,
    }),
    "utf-8",
  );

  console.log(
    `[build-detail-data] ${toWrite.length} bundles → ${detailDir}` +
      `${onlySet ? ` (--only ${toWrite.length}/${scores.length})` : ""}` +
      `${commentsDir ? " (with comments)" : " (no comments dir)"} ` +
      `(${Date.now() - t0} ms) from ${scoresPath}`,
  );
}

main().catch((err) => {
  console.error("[build-detail-data] FAILED:", err.message);
  process.exit(1);
});
