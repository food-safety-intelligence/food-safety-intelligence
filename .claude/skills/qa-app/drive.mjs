#!/usr/bin/env node
/**
 * qa-app: drive the running web app and report what works.
 *
 * Target URL via QA_APP_URL (default http://localhost:4000).
 * Viewport via QA_VIEWPORT=mobile for 390px (default 1440x900).
 *
 * Usage from app/ so node resolves @playwright via NODE_PATH:
 *
 *   NODE_PATH="$PWD/node_modules" node ../.claude/skills/qa-app/drive.mjs
 */

import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

// Skill lives outside app/, so a bare `import "playwright"` won't resolve.
// Pin a require() rooted at app/package.json so it finds app/node_modules.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const appPkgJson = path.resolve(__dirname, "../../../app/package.json");
const requireFromApp = createRequire(appPkgJson);
const { chromium } = requireFromApp("playwright");

const APP_URL = (process.env.QA_APP_URL || "http://localhost:4000").replace(
  /\/$/,
  "",
);
const VIEWPORT =
  process.env.QA_VIEWPORT === "mobile"
    ? { width: 390, height: 900 }
    : { width: 1440, height: 900 };

const TS = new Date()
  .toISOString()
  .replace(/[:.]/g, "-")
  .slice(0, 19);
const SHOTS_DIR = `/tmp/qa-app-${TS}`;

const BASE_ROUTES = [
  { path: "/", label: "home" },
  { path: "/chat/", label: "chat" },
  { path: "/how-it-works/", label: "how-it-works" },
  { path: "/caregivers/", label: "caregivers" },
  { path: "/sources/", label: "sources" },
];

const TYPING_VALUES = {
  search: "pizza",
  default: "test",
};

function shortText(s, max = 40) {
  return (s || "").replace(/\s+/g, " ").trim().slice(0, max);
}

async function buttonKey(handle) {
  const text = ((await handle.textContent()) || "").trim();
  const aria = ((await handle.getAttribute("aria-label")) || "").trim();
  return (text || aria).toLowerCase().slice(0, 60);
}

// Re-resolve a button by its key right before acting on it. Clicking one
// button often re-renders a React list and detaches any handle captured
// earlier ("Element is not attached to the DOM"), so handles are never
// reused across a click. Only visible buttons match — hidden responsive
// controls (e.g. the mobile map/list toggle on a desktop viewport) are
// skipped rather than counted as failures.
async function findVisibleButtonByKey(page, key) {
  for (const handle of await page.$$("button:not([disabled])")) {
    if ((await buttonKey(handle)) === key && (await handle.isVisible())) {
      return handle;
    }
  }
  return null;
}

async function exerciseRoute(browser, baseUrl, route) {
  const findings = {
    label: route.label,
    path: route.path,
    errors: [],
    actions: [],
    networkFailures: [],
    screenshots: {},
  };

  const context = await browser.newContext({ viewport: VIEWPORT });
  const page = await context.newPage();

  page.on("pageerror", (e) =>
    findings.errors.push(`pageerror: ${shortText(e.message, 120)}`),
  );
  page.on("console", (m) => {
    if (m.type() === "error") {
      findings.errors.push(`console.error: ${shortText(m.text(), 120)}`);
    }
  });
  page.on("requestfailed", (r) => {
    const err = r.failure()?.errorText ?? "unknown";
    // Next.js prefetches HEAD requests on link hover and cancels them when
    // they're no longer needed. ERR_ABORTED here is expected, not a real
    // failure — skip it.
    if (err === "net::ERR_ABORTED") return;
    findings.networkFailures.push(`${r.method()} ${r.url()}: ${err}`);
  });

  try {
    await page.goto(`${baseUrl}${route.path}`, {
      waitUntil: "networkidle",
      timeout: 30000,
    });
  } catch (e) {
    findings.errors.push(`goto failed: ${shortText(e.message, 120)}`);
    await context.close();
    return findings;
  }
  await page.waitForTimeout(600);

  try {
    const initialPath = `${SHOTS_DIR}/${route.label}-initial.png`;
    await page.screenshot({ path: initialPath, fullPage: false });
    findings.screenshots.initial = initialPath;
  } catch {}

  // ── Inputs: type a test value into each. ──────────────────────────────
  const inputs = await page.$$(
    "input[type=text], input[type=search], input:not([type]):not([readonly]), textarea",
  );
  for (const [i, input] of inputs.entries()) {
    try {
      const placeholder =
        (await input.getAttribute("placeholder"))?.toLowerCase() || "";
      const aria =
        (await input.getAttribute("aria-label"))?.toLowerCase() || "";
      const desc = shortText(placeholder || aria || `input#${i}`, 50);
      const value =
        placeholder.includes("search") || aria.includes("search")
          ? TYPING_VALUES.search
          : TYPING_VALUES.default;
      await input.fill(value, { timeout: 1500 });
      await page.waitForTimeout(200);
      findings.actions.push(`✓ typed "${value}" into "${desc}"`);
    } catch (e) {
      findings.actions.push(
        `✗ input typing failed: ${shortText(e.message, 80)}`,
      );
    }
  }

  // Clear typed values so subsequent button clicks aren't filter-affected.
  for (const input of inputs) {
    try {
      await input.fill("", { timeout: 500 });
    } catch {}
  }

  // ── Buttons: click each unique one. Dedupe by visible text and cap
  // at 20 per route so a long virtualised list (e.g. the home side list,
  // which is rendered as buttons) doesn't lead to N clicks of the same
  // kind of thing.
  const allButtons = await page.$$("button:not([disabled])");
  const seenKeys = new Set();
  const uniqueKeys = [];
  for (const button of allButtons) {
    // Only enumerate visible buttons so hidden responsive controls aren't
    // exercised on the wrong viewport. Keep keys (strings), not handles —
    // each handle is re-resolved at click time (see findVisibleButtonByKey).
    if (!(await button.isVisible())) continue;
    const key = await buttonKey(button);
    if (!key) continue;
    if (seenKeys.has(key)) continue;
    seenKeys.add(key);
    uniqueKeys.push(key);
    if (uniqueKeys.length >= 20) break;
  }
  findings.actions.push(
    `enumerated ${allButtons.length} button(s), exercising ${uniqueKeys.length} unique visible`,
  );

  // Let the page settle before driving it — the risk list re-renders as
  // markers and rows hydrate, and clicking a still-moving element times out
  // on Playwright's actionability check (it requires a stable target; 2s is
  // generous for the click itself, so a timeout means "never settled", not
  // "slow click").
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(300);

  for (const key of uniqueKeys) {
    let desc = shortText(key);
    let outcome;
    const button = await findVisibleButtonByKey(page, key);
    if (!button) {
      // The key vanished after an earlier click re-rendered the page
      // (e.g. a list item or suggestion chip). Not a failure.
      findings.actions.push(`· skipped "${desc}" (no longer in DOM)`);
      continue;
    }
    try {
      const text = await button.textContent();
      const aria = await button.getAttribute("aria-label");
      desc = shortText(text || aria || desc);
      await button.scrollIntoViewIfNeeded({ timeout: 1000 }).catch(() => {});
      // Only click what a user could actually click. The home risk list is
      // an internally-scrolling container with hundreds of rows; scrollIntoView
      // can't reliably position every row, so some land off-screen or under
      // the list's sticky header. Hit-test with the browser's own
      // elementFromPoint and skip unreachable elements instead of fighting
      // the click until it times out (which read as false failures).
      const reachable = await button
        .evaluate((el) => {
          const r = el.getBoundingClientRect();
          if (r.width === 0 || r.height === 0) return false;
          const cx = r.x + r.width / 2;
          const cy = r.y + r.height / 2;
          if (cx < 0 || cy < 0 || cx > window.innerWidth || cy > window.innerHeight)
            return false;
          const top = document.elementFromPoint(cx, cy);
          return !!top && (el === top || el.contains(top) || top.contains(el));
        })
        .catch(() => false);
      if (!reachable) {
        findings.actions.push(`· skipped "${desc}" (off-screen or covered)`);
        continue;
      }
      const urlBefore = page.url();
      await button.click({ timeout: 2000 });
      await page.waitForTimeout(180);
      const urlAfter = page.url();
      if (urlAfter !== urlBefore) {
        outcome = `→ clicked "${desc}" → navigated to ${new URL(urlAfter).pathname}`;
        // Restore route so subsequent buttons remain reachable.
        await page
          .goto(`${baseUrl}${route.path}`, { waitUntil: "networkidle", timeout: 15000 })
          .catch(() => {});
        await page.waitForTimeout(300);
      } else {
        outcome = `✓ clicked "${desc}"`;
      }
    } catch (e) {
      outcome = `✗ click failed on "${desc}": ${shortText(e.message, 80)}`;
    }
    findings.actions.push(outcome);
  }

  // ── Links: enumerate, don't navigate. ──────────────────────────────────
  const links = await page.$$("a[href]");
  findings.actions.push(`enumerated ${links.length} links (not navigated)`);

  // ── Route-specific extras (hover-only things crawlers miss). ──────────
  if (route.label === "home") {
    // Try several markers: the first one is often under the floating search
    // box and not hoverable, so a single-marker attempt spuriously times out.
    const markers = await page.$$(".maplibregl-marker");
    if (markers.length) {
      let hovered = false;
      let lastErr = "";
      for (const marker of markers.slice(0, 8)) {
        try {
          await marker.hover({ timeout: 1500 });
          await page.waitForTimeout(200);
          hovered = true;
          break;
        } catch (e) {
          lastErr = shortText(e.message, 80);
        }
      }
      findings.actions.push(
        hovered
          ? `✓ hovered a map pin (of ${markers.length})`
          : `✗ map pin hover failed on all ${Math.min(markers.length, 8)} tried: ${lastErr}`,
      );
    } else {
      findings.actions.push("⚠ no map pins found (selector .maplibregl-marker)");
    }
  }

  if (route.label === "detail") {
    // Driver rows in the explanation panel.
    const drivers = await page.$$("[data-driver], .driver-row, [data-driver-bar]");
    if (drivers.length) {
      try {
        await drivers[0].hover({ timeout: 1500 });
        await page.waitForTimeout(200);
        findings.actions.push(`✓ hovered a driver row (of ${drivers.length})`);
      } catch (e) {
        findings.actions.push(
          `✗ driver hover failed: ${shortText(e.message, 80)}`,
        );
      }
    } else {
      findings.actions.push("⚠ no driver rows matched fallback selectors");
    }
  }

  try {
    const finalPath = `${SHOTS_DIR}/${route.label}-final.png`;
    await page.screenshot({ path: finalPath, fullPage: false });
    findings.screenshots.final = finalPath;
  } catch {}

  await context.close();
  return findings;
}

async function pickRandomDetailRoute(browser, baseUrl) {
  const ctx = await browser.newContext({ viewport: VIEWPORT });
  const page = await ctx.newPage();
  try {
    await page.goto(`${baseUrl}/`, {
      waitUntil: "networkidle",
      timeout: 30000,
    });
    const hrefs = await page.$$eval('a[href^="/restaurant/"]', (as) =>
      as.map((a) => a.getAttribute("href")).filter(Boolean),
    );
    const unique = Array.from(new Set(hrefs));
    if (!unique.length) return null;
    const pick = unique[Math.floor(Math.random() * unique.length)];
    return { label: "detail", path: pick };
  } catch {
    return null;
  } finally {
    await ctx.close();
  }
}

function emitReport(allFindings) {
  console.log(`\n## QA pass for ${APP_URL}`);
  console.log(`viewport: ${VIEWPORT.width}x${VIEWPORT.height}`);
  console.log(`screenshots → ${SHOTS_DIR}\n`);

  let errorTotal = 0;
  let networkTotal = 0;
  let actionFailTotal = 0;
  for (const f of allFindings) {
    console.log(`### ${f.label} (${f.path})`);
    if (f.errors.length) {
      console.log(`\n**Errors:**`);
      for (const e of f.errors) console.log(`- ${e}`);
      errorTotal += f.errors.length;
    }
    if (f.networkFailures.length) {
      console.log(`\n**Network failures:**`);
      for (const n of f.networkFailures) console.log(`- ${n}`);
      networkTotal += f.networkFailures.length;
    }
    if (f.actions.length) {
      console.log(`\n**Actions:**`);
      for (const a of f.actions) console.log(`- ${a}`);
      // A leading "✗" marks an interaction that failed (click, type, hover).
      // These feed the verdict so a route where everything failed can't
      // report "clean" just because no console/network error fired.
      actionFailTotal += f.actions.filter((a) => a.startsWith("✗")).length;
    } else {
      console.log(`\n_(no interactive elements found on this route)_`);
    }
    console.log();
  }

  const verdict =
    errorTotal === 0 && networkTotal === 0 && actionFailTotal === 0
      ? "clean — no errors, no network failures, no failed interactions."
      : `${errorTotal} error(s), ${networkTotal} network failure(s), ` +
        `${actionFailTotal} failed interaction(s) across ${allFindings.length} routes.`;
  console.log(`---\n**Summary:** ${verdict}\n`);
}

async function main() {
  await mkdir(SHOTS_DIR, { recursive: true });

  const browser = await chromium.launch();

  const detail = await pickRandomDetailRoute(browser, APP_URL);
  const routes = [BASE_ROUTES[0], ...(detail ? [detail] : []), ...BASE_ROUTES.slice(1)];

  const allFindings = [];
  for (const route of routes) {
    const finding = await exerciseRoute(browser, APP_URL, route);
    allFindings.push(finding);
  }

  await browser.close();
  emitReport(allFindings);

  // Machine-readable findings for the issue-filing step (see SKILL.md).
  // Each route carries its failed interactions split out so the filer can
  // build an issue body without re-parsing the markdown.
  const routes_json = allFindings.map((f) => ({
    label: f.label,
    path: f.path,
    errors: f.errors,
    networkFailures: f.networkFailures,
    failedActions: f.actions.filter((a) => a.startsWith("✗")),
    screenshots: f.screenshots,
    hasFailures:
      f.errors.length > 0 ||
      f.networkFailures.length > 0 ||
      f.actions.some((a) => a.startsWith("✗")),
  }));
  const report = {
    appUrl: APP_URL,
    viewport: `${VIEWPORT.width}x${VIEWPORT.height}`,
    shotsDir: SHOTS_DIR,
    routes: routes_json,
    anyFailures: routes_json.some((r) => r.hasFailures),
  };
  const reportPath = `${SHOTS_DIR}/findings.json`;
  await writeFile(reportPath, JSON.stringify(report, null, 2));
  console.log(`findings JSON → ${reportPath}`);
}

main().catch((e) => {
  console.error("FATAL:", e.stack || e.message);
  process.exit(1);
});
