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
import { mkdir } from "node:fs/promises";
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

async function exerciseRoute(browser, baseUrl, route) {
  const findings = {
    label: route.label,
    path: route.path,
    errors: [],
    actions: [],
    networkFailures: [],
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
    await page.screenshot({
      path: `${SHOTS_DIR}/${route.label}-initial.png`,
      fullPage: false,
    });
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
  const uniqueButtons = [];
  for (const button of allButtons) {
    const text = ((await button.textContent()) || "").trim();
    const aria = ((await button.getAttribute("aria-label")) || "").trim();
    const key = (text || aria).toLowerCase().slice(0, 60);
    if (!key) continue;
    if (seenKeys.has(key)) continue;
    seenKeys.add(key);
    uniqueButtons.push({ button, key });
    if (uniqueButtons.length >= 20) break;
  }
  findings.actions.push(
    `enumerated ${allButtons.length} button(s), exercising ${uniqueButtons.length} unique`,
  );

  for (const [i, { button }] of uniqueButtons.entries()) {
    let desc = `button#${i}`;
    try {
      const text = await button.textContent();
      const aria = await button.getAttribute("aria-label");
      desc = shortText(text || aria || desc);
      const urlBefore = page.url();
      await button.scrollIntoViewIfNeeded({ timeout: 1000 }).catch(() => {});
      await button.click({ timeout: 2000 });
      await page.waitForTimeout(180);
      const urlAfter = page.url();
      if (urlAfter !== urlBefore) {
        findings.actions.push(
          `→ clicked "${desc}" → navigated to ${new URL(urlAfter).pathname}`,
        );
        // Restore route so subsequent buttons remain reachable.
        await page
          .goto(`${baseUrl}${route.path}`, { waitUntil: "networkidle", timeout: 15000 })
          .catch(() => {});
        await page.waitForTimeout(300);
      } else {
        findings.actions.push(`✓ clicked "${desc}"`);
      }
    } catch (e) {
      findings.actions.push(
        `✗ click failed on "${desc}": ${shortText(e.message, 80)}`,
      );
    }
  }

  // ── Links: enumerate, don't navigate. ──────────────────────────────────
  const links = await page.$$("a[href]");
  findings.actions.push(`enumerated ${links.length} links (not navigated)`);

  // ── Route-specific extras (hover-only things crawlers miss). ──────────
  if (route.label === "home") {
    const marker = await page.$(".maplibregl-marker");
    if (marker) {
      try {
        await marker.hover({ timeout: 2000 });
        await page.waitForTimeout(250);
        findings.actions.push("✓ hovered a map pin");
      } catch (e) {
        findings.actions.push(`✗ map pin hover failed: ${shortText(e.message, 80)}`);
      }
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
    await page.screenshot({
      path: `${SHOTS_DIR}/${route.label}-final.png`,
      fullPage: false,
    });
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
    } else {
      console.log(`\n_(no interactive elements found on this route)_`);
    }
    console.log();
  }

  const verdict =
    errorTotal === 0 && networkTotal === 0
      ? "clean — no errors caught, no network failures."
      : `${errorTotal} error(s), ${networkTotal} network failure(s) across ${allFindings.length} routes.`;
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
}

main().catch((e) => {
  console.error("FATAL:", e.stack || e.message);
  process.exit(1);
});
