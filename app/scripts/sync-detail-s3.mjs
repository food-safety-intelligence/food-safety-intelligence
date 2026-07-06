#!/usr/bin/env node
/**
 * Content-aware upload of the per-license detail bundles to the website bucket.
 *
 * Why: `aws s3 sync` decides what to transfer by size + mtime, and `next build`
 * rebuilds out/ fresh on every deploy — so every one of the ~23.6k detail
 * bundles gets a new mtime and re-uploads even when its bytes are identical to
 * what is already live. The bundles are a pure function of the data, which only
 * changes on a republish, so a code-only deploy was re-uploading ~23.6k
 * unchanged objects (and their PUT cost) for nothing.
 *
 * This uploads only the bundles whose md5 differs from the live object's ETag
 * (for a single-part PUT the S3 ETag IS the content md5) and deletes objects
 * whose license no longer exists locally. Safe degradation: if remote ETags are
 * not plain md5 (e.g. an SSE-KMS bucket, or a multipart upload), nothing matches
 * and it uploads everything — exactly today's behaviour. It can never SKIP a
 * needed upload, because a changed bundle's md5 won't equal the old ETag.
 *
 * The rest of out/ (the app shell — small, changes every code deploy) stays on
 * the plain `aws s3 sync --delete --exclude "data/detail/*"`.
 *
 * Usage: node scripts/sync-detail-s3.mjs <localDetailDir> <bucket> <keyPrefix>
 */

import {
  DeleteObjectsCommand,
  ListObjectsV2Command,
  PutObjectCommand,
  S3Client,
} from "@aws-sdk/client-s3";
import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Pure diff: given the local md5-by-key map and the remote etag-by-key map,
 * decide which keys to upload (new or changed) and which to delete (gone).
 */
export function computeDiff(localMd5, remoteEtag) {
  const toUpload = [];
  for (const [key, md5] of localMd5) {
    if (remoteEtag.get(key) !== md5) toUpload.push(key);
  }
  const toDelete = [];
  for (const key of remoteEtag.keys()) {
    if (!localMd5.has(key)) toDelete.push(key);
  }
  return { toUpload, toDelete };
}

/** All objects under the prefix → Map(key → unquoted ETag). Paginated. */
async function listRemote(s3, bucket, prefix) {
  const map = new Map();
  let token;
  do {
    const res = await s3.send(
      new ListObjectsV2Command({
        Bucket: bucket,
        Prefix: prefix,
        ContinuationToken: token,
      }),
    );
    for (const o of res.Contents ?? []) {
      map.set(o.Key, (o.ETag ?? "").replaceAll('"', ""));
    }
    token = res.IsTruncated ? res.NextContinuationToken : undefined;
  } while (token);
  return map;
}

async function main() {
  const [localDir, bucket, prefix] = process.argv.slice(2);
  if (!localDir || !bucket || !prefix) {
    console.error(
      "usage: sync-detail-s3.mjs <localDetailDir> <bucket> <keyPrefix>",
    );
    process.exit(1);
  }
  // Region comes from the environment (AWS_REGION, set by the deploy's
  // configure-aws-credentials) — the website bucket lives in that region, unlike
  // the data bucket which prebuild-sync-s3 pins to us-east-1.
  const s3 = new S3Client({});

  // md5 every local bundle keyed by its S3 key (prefix + filename). Read in
  // bounded batches so we never open 23.6k descriptors at once; keep only the
  // hashes resident (not the file bodies — changed files are re-read on upload).
  const files = (await readdir(localDir)).filter((f) => f.endsWith(".json"));
  const localMd5 = new Map();
  const BATCH = 256;
  for (let i = 0; i < files.length; i += BATCH) {
    await Promise.all(
      files.slice(i, i + BATCH).map(async (f) => {
        const body = await readFile(path.join(localDir, f));
        localMd5.set(prefix + f, createHash("md5").update(body).digest("hex"));
      }),
    );
  }

  const remoteEtag = await listRemote(s3, bucket, prefix);
  const { toUpload, toDelete } = computeDiff(localMd5, remoteEtag);
  console.log(
    `[sync-detail] ${files.length} local, ${remoteEtag.size} remote → ` +
      `upload ${toUpload.length}, delete ${toDelete.length}`,
  );

  // Upload new/changed bundles (re-read the body now — only the changed subset).
  for (let i = 0; i < toUpload.length; i += BATCH) {
    await Promise.all(
      toUpload.slice(i, i + BATCH).map(async (key) => {
        const body = await readFile(path.join(localDir, key.slice(prefix.length)));
        await s3.send(
          new PutObjectCommand({
            Bucket: bucket,
            Key: key,
            Body: body,
            ContentType: "application/json",
            // Revalidate against the ETag on every load (mirrors the data JSON in
            // deploy-web.yml): a detail bundle shares a stable url, so without this
            // a browser keeps serving a cached bundle after a republish and the
            // detail page's risk tier lags the map. Unchanged → 304; changed →
            // fresh, no hard refresh.
            CacheControl: "no-cache",
          }),
        );
      }),
    );
  }

  // Delete dropped licenses (DeleteObjects takes up to 1000 keys per call).
  for (let i = 0; i < toDelete.length; i += 1000) {
    await s3.send(
      new DeleteObjectsCommand({
        Bucket: bucket,
        Delete: { Objects: toDelete.slice(i, i + 1000).map((Key) => ({ Key })) },
      }),
    );
  }
  console.log("[sync-detail] done");
}

// Only run when invoked directly, so computeDiff can be imported and tested.
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch((err) => {
    console.error("[sync-detail] FAILED:", err.message);
    process.exit(1);
  });
}
