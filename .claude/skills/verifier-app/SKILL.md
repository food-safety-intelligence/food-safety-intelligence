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

Capture **every state and viewport** the change affects (desktop + mobile 390px,
each before/after state) — not one hand-picked frame. Then get them into the PR
description. This repo is private, which constrains how:

GitHub **cannot inline-render committed images in a private repo** — its image
proxy fetches `raw.githubusercontent.com` / `…/blob/…?raw=true` unauthenticated
and gets a 404, so `![](…)` embeds show as broken. Two ways to attach:

- **Inline (human / web UI only):** open the PR, edit the description, and
  **drag the PNG files in**. GitHub uploads them to its attachment store
  (`user-attachments`) and they render inline for everyone with repo access.
  This is the ONLY path that produces inline images; an agent with just the
  OAuth token cannot reach that store.

- **Committed file-view links (the agent / headless path — the team default,
  e.g. PRs #19, #27, #29, #31, #32):** commit the PNGs into the repo and
  reference them as clickable **file-view** links. Steps:
  1. Open the PR first so you have its number `N` (a draft PR is fine — create
     it, then finalize the body once the screenshots are committed).
  2. Commit the PNGs under **`design/pr-<N>/`** (e.g. `design/pr-49/`) — this is
     the folder convention. `design/` is checked in (not gitignored) and is the
     documented home for screenshots; a feature-name folder also exists in
     history but **prefer `design/pr-<N>/`**.
  3. In the PR body, link each one via the GitHub **file view**, pinned to the
     screenshot commit's SHA so the link is stable:
     `https://github.com/<owner>/<repo>/blob/<sha>/design/pr-<N>/<name>.png`.
     Use a markdown **link** `- [Collapsed — desktop](…blob/<sha>/…png)`, NOT an
     `![]()` embed (the embed renders broken in a private repo).
  4. Add one line so reviewers know why they're links, not inline images, and
     how to upgrade them: *"GitHub can't inline raw images in a private repo, so
     these are clickable file-view links. For inline rendering, drag the PNGs
     from `design/pr-<N>/` into this description."*

  The current repo is `food-safety-intelligence/food-safety-intelligence` (the
  old `junxu315/…` URL redirects there) — use it for both the API and the blob
  links. `gh pr edit` is broken here; set the body via the REST API
  (`PATCH /repos/<owner>/<repo>/pulls/<N>` with a JSON `{"body": …}`).
