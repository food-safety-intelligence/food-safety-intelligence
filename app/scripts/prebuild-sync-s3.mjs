#!/usr/bin/env node
/**
 * Prebuild step for `next build` with `output: "export"`.
 *
 * The static export pre-renders every page in parallel workers. Each worker
 * is a fresh Node process with its own module-level cache, so without this
 * step each worker would re-fetch the 18 MB scores.json from S3 — saturating
 * bandwidth, timing out, and failing the build.
 *
 * Solution: download the two large JSONs ONCE before the build, write them
 * to a shared /tmp directory, then `scores-server.ts` reads from there
 * during the build instead of going back to S3 per worker.
 */

import { GetObjectCommand, S3Client } from "@aws-sdk/client-s3";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";

const BUCKET = process.env.FSI_S3_BUCKET ?? "food-safety-intelligence-data";
// The data bucket is us-east-1. Pin it independently of AWS_REGION, which the
// deploy workflow sets to the website-infra region (us-west-2) — a client in the
// wrong region fails the read with a 301 region redirect.
const REGION = process.env.FSI_S3_REGION ?? "us-east-1";
const PREFIX = "web-app-data";
const CACHE_DIR = "/tmp/fsi-build-cache";
const KEYS = ["scores.json", "inspection_history.json"];

const s3 = new S3Client({ region: REGION });

async function fetchAndCache(key) {
  const t0 = Date.now();
  const out = path.join(CACHE_DIR, key);
  let text;
  try {
    const res = await s3.send(
      new GetObjectCommand({ Bucket: BUCKET, Key: `${PREFIX}/${key}` }),
    );
    if (!res.Body) throw new Error("empty body");
    text = await res.Body.transformToString();
  } catch (err) {
    // No creds / offline / object missing: fall back to the committed copy so
    // the build still works without AWS. (Slightly stale, but functional.)
    const committed = path.join("public", "data", key);
    text = await readFile(committed, "utf-8");
    console.warn(
      `  ${key.padEnd(28)} S3 failed (${err.message}); using committed ${committed}`,
    );
  }
  await writeFile(out, text, "utf-8");
  const mb = (text.length / 1024 / 1024).toFixed(1);
  console.log(`  ${key.padEnd(28)} ${mb} MB  ${Date.now() - t0} ms  → ${out}`);
}

// Comment shards (web-app-data/comments/<xx>.json) have NO committed fallback —
// they're gitignored (266 MB). The static export reads the full comment text at
// build time. We pull the 256 md5 shards and immediately RE-SHARD them to one
// file per license under comments-by-license/, mirroring shard-history.mjs: a
// detail page then reads only its own license's comments, so no build worker
// ever holds the whole 266 MB resident (that pattern OOMs the static export —
// the same reason inspection_history is sharded). Processing one shard at a
// time keeps prebuild itself to ~1 MB resident. Iterating the fixed shard names
// (00..ff) keeps the IAM ask to s3:GetObject only — no s3:ListBucket needed.
async function syncComments() {
  const t0 = Date.now();
  const outDir = path.join(CACHE_DIR, "comments-by-license");
  // Start clean so a stale shard from an older data version can't linger.
  await rm(outDir, { recursive: true, force: true });
  await mkdir(outDir, { recursive: true });
  const shards = Array.from({ length: 256 }, (_, n) =>
    n.toString(16).padStart(2, "0"),
  );

  let licenses = 0;
  let next = 0;
  async function worker() {
    while (next < shards.length) {
      const key = `comments/${shards[next++]}.json`;
      let map;
      try {
        const res = await s3.send(
          new GetObjectCommand({ Bucket: BUCKET, Key: `${PREFIX}/${key}` }),
        );
        if (!res.Body) continue;
        map = JSON.parse(await res.Body.transformToString());
      } catch {
        // Missing shard or no creds — skip. With no creds none arrive and the
        // timeline shows "No comments were recorded" (graceful, non-fatal).
        continue;
      }
      // Explode this shard into per-license files, then let it be GC'd so
      // prebuild never holds more than one shard at a time.
      const ids = Object.keys(map);
      for (let i = 0; i < ids.length; i += 128) {
        await Promise.all(
          ids.slice(i, i + 128).map((id) =>
            writeFile(
              path.join(outDir, `${id}.json`),
              JSON.stringify(map[id]),
              "utf-8",
            ),
          ),
        );
      }
      licenses += ids.length;
    }
  }
  // 4 shards in flight: bounded sockets, and at most 4×128 open file descriptors.
  await Promise.all(Array.from({ length: 4 }, worker));

  if (licenses === 0) {
    console.warn(
      "  comments-by-license/         none fetched (no S3 creds?) — timeline will show no comments",
    );
    return;
  }
  console.log(
    `  comments-by-license/ (${licenses} licenses)  ${Date.now() - t0} ms`,
  );
}

async function main() {
  console.log(`[prebuild] syncing s3://${BUCKET}/${PREFIX}/ → ${CACHE_DIR}`);
  await mkdir(CACHE_DIR, { recursive: true });
  await Promise.all(KEYS.map(fetchAndCache));
  await syncComments();
  console.log("[prebuild] done");
}

main().catch((err) => {
  // Only fails if BOTH S3 and the committed fallback are unavailable.
  console.error("[prebuild] FAILED:", err.message);
  process.exit(1);
});
