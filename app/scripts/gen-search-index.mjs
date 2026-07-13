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
 * Usage: node scripts/gen-search-index.mjs <source-scores.json> [dest.json] \
 *          [inspection_history.json] [comments-by-license-dir]
 *
 * The two optional inputs enable violation-category tagging (`vc` bitmask per
 * row, taxonomy in src/lib/violation-categories.json): deploy builds pass the
 * S3-synced comments dir (full violation text); dev builds pass history only,
 * so tagging falls back to the first-violation headline. No history path →
 * no vc fields at all (the UI then hides the violation filter).
 */

import { readFileSync } from "node:fs";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import {
  CATEGORY_SLUGS,
  latestScoredEvent,
  tagViolations,
} from "./lib/violation-tagging.mjs";

const src = process.argv[2] ?? "public/data/scores.json";
const dest = process.argv[3] ?? "public/data/search-index.json";
const historyPath = process.argv[4] ?? null;
const commentsDir = process.argv[5] ?? null;

async function main() {
  const payload = JSON.parse(await readFile(src, "utf-8"));
  const scores = payload.scores ?? [];

  const history = historyPath
    ? JSON.parse(await readFile(historyPath, "utf-8"))
    : null;

  // Full violation text for one license, when the deploy build synced it.
  // comments[i] is index-aligned with history[license][i] (both come from the
  // same sorted/capped slice in export_inspection_history.py).
  const commentsFor = (licenseId) => {
    if (!commentsDir) return null;
    try {
      return JSON.parse(
        readFileSync(path.join(commentsDir, `${licenseId}.json`), "utf-8"),
      );
    } catch {
      return null; // license has no synced comments — headline fallback
    }
  };

  let taggedFromComments = 0;
  const categoryCounts = CATEGORY_SLUGS.map(() => 0);

  // Violation categories at the latest scored inspection (spec 2026-07-13).
  const vcFor = (r) => {
    if (!history) return 0;
    const hit = latestScoredEvent(history[r.license_id], r.as_of_date ?? null);
    if (!hit) return 0;
    let text = hit.event.headline ?? "";
    const comments = commentsFor(r.license_id);
    if (comments && typeof comments[hit.index] === "string") {
      text = comments[hit.index]; // "" = clean inspection, use verbatim
      taggedFromComments += 1;
    }
    const vc = tagViolations(text);
    for (let i = 0; i < categoryCounts.length; i += 1) {
      if (vc & (1 << i)) categoryCounts[i] += 1;
    }
    return vc;
  };

  const rows = scores.map((r) => {
    const d = r.top_drivers?.[0];
    const vc = vcFor(r);
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
      // Anchor date of the latest scored inspection — the inspectors page
      // derives "last inspected N days ago" / overdue sorting from it.
      as_of_date: r.as_of_date ?? null,
      // top_drivers[0] reduced to the PinDriver the list/pin renders.
      top_driver: d ? { feature: d.feature, label: d.label, up: d.shap > 0 } : null,
      // Serialized only when true (~27% of rows) — absent means active.
      ...(r.is_out_of_business ? { is_out_of_business: true } : {}),
      // Violation-category bitmask at the latest scored inspection; omitted
      // when clean/unknown so the field costs nothing on most rows.
      ...(vc ? { vc } : {}),
    };
  });

  const out = {
    schema_version: "1",
    generated_at: payload.generated_at ?? null,
    as_of_date: payload.as_of_date ?? null,
    total: payload.totals?.establishments ?? rows.length,
    tier_counts: payload.totals?.tier_counts ?? {},
    rows,
  };

  await writeFile(dest, JSON.stringify(out), "utf-8");
  const mb = ((await readFile(dest)).length / 1024 / 1024).toFixed(1);
  console.log(`[search-index] ${rows.length} rows → ${dest} (${mb} MB) from ${src}`);

  if (history) {
    const mode =
      commentsDir && taggedFromComments > 0
        ? `full text (${taggedFromComments.toLocaleString()} licenses with comments)`
        : "headlines only (first violation per inspection; dev fallback)";
    console.log(`[search-index] violation tagging: ${mode}`);
    console.log(
      "[search-index] category counts: " +
        CATEGORY_SLUGS.map((s, i) => `${s}=${categoryCounts[i]}`).join(" "),
    );
  } else {
    console.log(
      "[search-index] violation tagging: skipped (no history path) — rows carry no vc",
    );
  }

  // Tiny sibling the header's "Data as of …" chip fetches on every page. The
  // search index is multi-MB, so it can't be pulled just to read the snapshot
  // date on the static pages — this projects the payload-level fields into a
  // ~100-byte file that loads instantly city-by-city.
  const metaDest = dest.replace(/[^/]*$/, "data-meta.json");
  const meta = {
    schema_version: "1",
    as_of_date: payload.as_of_date ?? null,
    generated_at: payload.generated_at ?? null,
    total: out.total,
  };
  await writeFile(metaDest, JSON.stringify(meta), "utf-8");
  console.log(`[search-index] meta → ${metaDest} (as_of ${meta.as_of_date ?? "n/a"})`);
}

main().catch((err) => {
  console.error("[search-index] FAILED:", err.message);
  process.exit(1);
});
