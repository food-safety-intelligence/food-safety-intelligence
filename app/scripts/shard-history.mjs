#!/usr/bin/env node
/**
 * Shard inspection_history.json into one small file per license.
 *
 * Why: the detail page only needs ONE license's history, but the full map is
 * ~45 MB. The static export pre-renders ~500 detail pages across parallel
 * workers; if every worker parses and holds the whole map (~1 GB of JS objects
 * each), `next build` runs out of memory. Sharding lets each page read just its
 * own slice, so nothing holds the whole map resident.
 *
 * Output: <out-dir>/<license_id>.json, each an array of that license's events.
 * `getInspectionHistory` in scores-server.ts reads these at build/dev time.
 *
 * Usage: node scripts/shard-history.mjs <inspection_history.json> <out-dir>
 */

import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";

const src = process.argv[2];
const outDir = process.argv[3];
if (!src || !outDir) {
  console.error("usage: shard-history.mjs <inspection_history.json> <out-dir>");
  process.exit(1);
}

async function main() {
  const t0 = Date.now();
  const map = JSON.parse(await readFile(src, "utf-8"));
  // Start clean so a stale shard from an older data version can't linger.
  await rm(outDir, { recursive: true, force: true });
  await mkdir(outDir, { recursive: true });

  const ids = Object.keys(map);
  // Write in bounded-concurrency batches — 48k tiny files at once would
  // exhaust file descriptors.
  const BATCH = 512;
  for (let i = 0; i < ids.length; i += BATCH) {
    const batch = ids.slice(i, i + BATCH);
    await Promise.all(
      batch.map((id) =>
        writeFile(
          path.join(outDir, `${id}.json`),
          JSON.stringify(map[id]),
          "utf-8",
        ),
      ),
    );
  }
  console.log(
    `[shard-history] ${ids.length} licenses → ${outDir} (${Date.now() - t0} ms) from ${src}`,
  );
}

main().catch((err) => {
  console.error("[shard-history] FAILED:", err.message);
  process.exit(1);
});
