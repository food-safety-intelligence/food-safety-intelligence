---
name: verifier-app
description: Build, launch, and capture pixels for the Next.js web app in app/ so a code change can be verified by observing the running UI. The built-in `verify` skill auto-discovers this verifier-* skill as the web surface's evidence-capture protocol. Covers npm ci, next dev, a Playwright screenshot recipe, and the key routes / test restaurants.
---

# verifier-app

Evidence-capture protocol for the Next.js app (`app/`). The built-in `verify`
skill looks for a `verifier-*` skill matching the surface — this is it for the
web UI, so running `/verify` on an `app/` change picks it up automatically.
Goal: get the changed page rendering and capture a screenshot a reviewer can
look at, not just inspect HTML.

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

## Put the screenshots in the PR (this repo is private)

GitHub **cannot inline-render committed images in a private repo** — its image
proxy fetches `raw.githubusercontent.com` unauthenticated and gets a 404, so
`![](raw…)` embeds show as broken. To embed screenshots in a PR description:

- **Human / web UI (the only inline path):** open the PR, edit the description,
  and **drag the PNG files in**. GitHub uploads them to its attachment store
  (`user-attachments`) and they render inline for everyone with repo access.
- **Headless / agent (can't drag-drop):** save the PNGs to a known path and ask
  a human to drop them in. As a non-inline fallback, commit them under `design/`
  and link to the GitHub **file view** (`…/blob/<sha>/design/…png`) — that works
  for logged-in reviewers, but is a click, not an inline image. Do **not** rely
  on `raw.githubusercontent.com` links; they 404 for the renderer.
