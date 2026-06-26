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
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const BUCKET = process.env.FSI_S3_BUCKET ?? "food-safety-intelligence-data";
const REGION = process.env.AWS_REGION ?? "us-east-1";
const PREFIX = "web-app-data";
const CACHE_DIR = "/tmp/fsi-build-cache";
const KEYS = ["scores.json", "inspection_history.json"];

const s3 = new S3Client({ region: REGION });

async function fetchAndCache(key) {
  const t0 = Date.now();
  const res = await s3.send(
    new GetObjectCommand({ Bucket: BUCKET, Key: `${PREFIX}/${key}` }),
  );
  if (!res.Body) throw new Error(`empty body for ${key}`);
  const text = await res.Body.transformToString();
  const out = path.join(CACHE_DIR, key);
  await writeFile(out, text, "utf-8");
  const mb = (text.length / 1024 / 1024).toFixed(1);
  const ms = Date.now() - t0;
  console.log(`  ${key.padEnd(28)} ${mb} MB  ${ms} ms  → ${out}`);
}

async function main() {
  console.log(`[prebuild] syncing s3://${BUCKET}/${PREFIX}/ → ${CACHE_DIR}`);
  await mkdir(CACHE_DIR, { recursive: true });
  await Promise.all(KEYS.map(fetchAndCache));
  console.log("[prebuild] done");
}

main().catch((err) => {
  console.error("[prebuild] FAILED:", err.message);
  process.exit(1);
});
