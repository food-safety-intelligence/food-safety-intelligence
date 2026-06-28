#!/usr/bin/env node
/**
 * Emit the slim client search index from a full scores.json.
 *
 * The home page is statically exported, so search/sort/filter run in the
 * browser. To do that the client needs every establishment — but the full
 * scores.json is ~21 MB, which is over CloudFront's 10 MB automatic-compression
 * ceiling, so it would ship uncompressed. This projection keeps only the fields
 * the home list / map / search use (dropping the extra drivers, calibration
 * triple, trend CIs, as_of_date), bringing it under 10 MB so the CDN gzip/brotli
 * compresses it to ~1 MB on the wire.
 *
 * Run it from the SAME scores.json the pages are built from, so the client list
 * and the prerendered detail pages always agree:
 *   - build: from the S3 pull cached by prebuild-sync-s3.mjs (/tmp/fsi-build-cache)
 *   - dev:   from the committed public/data/scores.json (no S3 creds needed)
 *
 * Usage: node scripts/gen-search-index.mjs <source-scores.json> [dest.json]
 */

import { readFile, writeFile } from "node:fs/promises";

const src = process.argv[2] ?? "public/data/scores.json";
const dest = process.argv[3] ?? "public/data/search-index.json";

async function main() {
  const payload = JSON.parse(await readFile(src, "utf-8"));
  const scores = payload.scores ?? [];

  const rows = scores.map((r) => {
    const d = r.top_drivers?.[0];
    return {
      license_id: r.license_id,
      dba_name: r.dba_name,
      address: r.address,
      lat: r.lat,
      lon: r.lon,
      // Round to the 2-decimal precision the UI actually shows — trims bytes
      // without changing any displayed score.
      risk_score: Math.round(r.risk_score * 1000) / 1000,
      risk_tier: r.risk_tier,
      trend_slope: r.trend_slope,
      // top_drivers[0] reduced to the PinDriver the list/pin renders.
      top_driver: d ? { feature: d.feature, label: d.label, up: d.shap > 0 } : null,
    };
  });

  const out = {
    schema_version: "1",
    generated_at: payload.generated_at ?? null,
    total: payload.totals?.establishments ?? rows.length,
    tier_counts: payload.totals?.tier_counts ?? {},
    rows,
  };

  await writeFile(dest, JSON.stringify(out), "utf-8");
  const mb = ((await readFile(dest)).length / 1024 / 1024).toFixed(1);
  console.log(`[search-index] ${rows.length} rows → ${dest} (${mb} MB) from ${src}`);
}

main().catch((err) => {
  console.error("[search-index] FAILED:", err.message);
  process.exit(1);
});
