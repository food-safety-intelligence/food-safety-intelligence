#!/usr/bin/env node
/**
 * Headless smoke test of the static export (`app/out`).
 *
 * Why: the `app` CI job runs only static / logic checks — eslint, tsc, vitest
 * (jsdom logic, no pixels), and `next build`. None of them RENDER a page, so
 * layout, overflow, and render-time/route-behaviour regressions pass CI green
 * (e.g. a floating panel leaking onto a route because a `usePathname()` guard
 * missed the trailing slash). This job loads the built site in a real browser
 * and asserts the things those checks can't see.
 *
 * Assertion-based, NOT pixel snapshots: font hinting / antialiasing differ
 * between CI and local, so screenshot baselines churn. For each key route, at
 * desktop and mobile widths, we assert:
 *   - no same-origin resource (the page, a JS chunk, a data JSON) returned >=400,
 *   - no uncaught page errors and no app-level console errors,
 *   - the page's <main> landmark rendered (not a blank / error shell),
 *   - no horizontal overflow (scrollWidth <= innerWidth).
 *
 * Usage: node e2e/smoke.mjs
 *   SMOKE_BASE_URL  base URL of the served export   (default http://localhost:3000)
 *   SMOKE_OUT_DIR   path to the built `out/` dir     (default out)
 */

import { readdirSync } from "node:fs";
import { chromium } from "playwright";

const BASE_URL = process.env.SMOKE_BASE_URL ?? "http://localhost:3000";
const OUT_DIR = process.env.SMOKE_OUT_DIR ?? "out";

const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 1600 },
  { name: "mobile", width: 390, height: 1800 },
];

// Console-error noise that is NOT an app regression: external map tiles and
// fonts are fetched at view time from third-party hosts, and a flaky tile fetch
// in CI must not fail the build. Keep this list narrow and specific.
const IGNORED_CONSOLE = [
  /tile\.openstreetmap/i,
  /maplibre/i,
  /Failed to load resource/i,
  /net::ERR_/i,
  /favicon/i,
  /AbortError/i,
];

// Pick a real pre-rendered restaurant id from the build output rather than
// hardcode one — generateStaticParams decides which detail pages exist, so a
// hardcoded id could 404 after a data refresh.
function firstRestaurantId() {
  const dir = `${OUT_DIR}/restaurant`;
  const ids = readdirSync(dir, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
  if (ids.length === 0) {
    throw new Error(`no pre-rendered restaurant pages under ${dir}`);
  }
  return ids[0];
}

// Trailing slashes match next.config `trailingSlash: true` so the static host
// resolves each path to its index.html without a redirect.
function routesToCheck(restaurantId) {
  return [
    "/",
    `/restaurant/${restaurantId}/`,
    "/how-it-works/",
    "/chat/",
    "/sources/",
    "/caregivers/",
  ];
}

async function checkRoute(browser, route, viewport) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
  });
  const page = await context.newPage();
  const failures = [];

  page.on("pageerror", (err) => failures.push(`uncaught: ${err.message}`));
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (IGNORED_CONSOLE.some((re) => re.test(text))) return;
    failures.push(`console.error: ${text}`);
  });
  // Any same-origin resource that returns >=400 — the page itself, a JS chunk,
  // a data JSON — is a real regression, but it otherwise surfaces only as a
  // "Failed to load resource" console line we filter as tile noise. Check the
  // response status directly. Aborted requests (cancelled <Link> prefetches,
  // cross-origin map tiles) produce no response, so they never trip this.
  page.on("response", (res) => {
    if (res.url().startsWith(BASE_URL) && res.status() >= 400) {
      failures.push(`HTTP ${res.status()} ${res.url().slice(BASE_URL.length) || "/"}`);
    }
  });

  try {
    await page.goto(`${BASE_URL}${route}`, { waitUntil: "domcontentloaded" });

    // Wait for the page to actually render its content, then let client
    // hydration settle so the measured layout is the interactive one.
    await page.waitForSelector("main", { state: "attached", timeout: 15000 });
    await page.waitForTimeout(800);

    const overflow = await page.evaluate(() => {
      const doc = document.documentElement;
      return doc.scrollWidth - window.innerWidth;
    });
    // 1px of rounding slack; anything more is a real horizontal scrollbar.
    if (overflow > 1) {
      failures.push(`horizontal overflow by ${overflow}px`);
    }
  } catch (err) {
    failures.push(err.message);
  } finally {
    await context.close();
  }

  return failures;
}

async function main() {
  const restaurantId = firstRestaurantId();
  const routes = routesToCheck(restaurantId);
  const browser = await chromium.launch();
  let failed = 0;

  try {
    for (const route of routes) {
      for (const viewport of VIEWPORTS) {
        const failures = await checkRoute(browser, route, viewport);
        const label = `${route} [${viewport.name}]`;
        if (failures.length === 0) {
          console.log(`  ok   ${label}`);
        } else {
          failed += 1;
          console.error(`  FAIL ${label}`);
          for (const failure of failures) {
            console.error(`         ${failure}`);
          }
        }
      }
    }
  } finally {
    await browser.close();
  }

  const total = routes.length * VIEWPORTS.length;
  if (failed > 0) {
    console.error(`\n[smoke] ${failed}/${total} route checks failed`);
    process.exit(1);
  }
  console.log(`\n[smoke] all ${total} route checks passed`);
}

main().catch((err) => {
  console.error("[smoke] FAILED:", err.message);
  process.exit(1);
});
