---
name: verify-app
description: Build, launch, and capture pixels for the Next.js web app in app/ so a code change can be verified by observing the running UI. Invoke as /verify-app when verifying an app/ UI change. Covers npm ci, next dev, a Playwright screenshot recipe, and the key routes / test restaurants.
---

# verify-app

Evidence-capture protocol for the Next.js app (`app/`) — invoke it
(`/verify-app`) when verifying an app/ UI change. Goal: get the changed page
rendering and capture a screenshot a reviewer can look at, not just inspect
HTML.

## Build + launch

```bash
cd app
npm ci          # deps are NOT committed; use npm, not pnpm
npm run dev     # serves http://localhost:3000 (compiles on first request)
```

## Capture pixels

No browser ships by default. Install Chromium WITHOUT touching `package.json`,
then add its system libraries. This is an Ubuntu image (apt + sudo available);
the recipe below is verified working here.

```bash
cd app
npm install --no-save playwright      # the package; --no-save keeps it out of package.json
npx playwright install chromium       # browser binary (~150 MB) -> ~/.cache/ms-playwright
# Chromium needs system libs (libnss3, libatk, libgbm, libxkbcommon, ...).
# Let Playwright apt-install them. Preserve PATH so sudo finds node/npx:
sudo apt-get update -qq
sudo env "PATH=$PATH" npx playwright install-deps chromium
```

Sanity-check the browser binary resolved its libs (empty output = good):

```bash
ldd ~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome | grep "not found"
```

Screenshot script — run with `node`. **Gotcha:** if the script lives outside
`app/` (e.g. `/tmp`), set `NODE_PATH` to the app's `node_modules`, because node
resolves `require` relative to the SCRIPT's location, not the cwd.

```js
// /tmp/shot.js
const { chromium } = require("playwright");
(async () => {
  const browser = await chromium.launch();          // headless by default
  const page = await browser.newPage({ viewport: { width: 1280, height: 1600 } });
  await page.goto("http://localhost:3000/restaurant/2304080", { waitUntil: "networkidle" });
  await page.waitForTimeout(800);                    // let client hydration settle
  await page.screenshot({ path: "/tmp/detail-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 1800 }); // mobile
  await page.screenshot({ path: "/tmp/detail-mobile.png", fullPage: true });
  await browser.close();
})();
```

```bash
cd app && NODE_PATH="$PWD/node_modules" node /tmp/shot.js
```

Only if you genuinely cannot `sudo` (no root): report BLOCKED on pixels, fall
back to server-rendered HTML inspection plus a human browser check, and name the
path you did not exercise.

## What to check — restaurant detail page

Route `/restaurant/<license_id>`. Known test restaurants:

| Case | license_id | Expectation |
|---|---|---|
| Mixed drivers | `2304080` | diverging bars on BOTH sides of the centre zero axis |
| High risk | `1493350` | drivers mostly raise risk (terra, bars extend right) |
| Low risk | `2627692` | drivers mostly lower risk (sage, bars extend left) |

Surfaces to confirm:

- **Driver panel** — diverging bars (terra right = raises risk, sage left =
  lowers), axis legend, how-to-read footer, per-row hover tooltip.
- **"Top factor" chip** beside the gauge — correct driver, up/down arrow,
  colour matches direction, long labels truncate (with a `title` tooltip).
- Labels are plain English — **no raw `snake_case` column names**.
- No layout breaks at mobile width (390px).

Other routes worth a glance: `/` (map + list), `/how-it-works` (methodology).
