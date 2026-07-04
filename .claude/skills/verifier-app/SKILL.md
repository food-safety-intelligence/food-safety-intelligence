---
name: verifier-app
description: Build, launch, and capture pixels for the Next.js web app in app/ so a code change can be verified by observing the running UI. The built-in `verify` skill auto-discovers this verifier-* skill as the web surface's evidence-capture protocol. Covers the fast `next dev` path for client-rendered pages, the static-export build served from out/ for the home/detail routes, a Playwright screenshot recipe, and the key routes / test restaurants.
---

# verifier-app

Evidence-capture protocol for the Next.js app (`app/`). The built-in `verify`
skill looks for a `verifier-*` skill matching the surface — this is it for the
web UI, so running `/verify` on an `app/` change picks it up automatically.
Goal: get the changed page rendering and capture a screenshot a reviewer can
look at, not just inspect HTML.

## Pick the surface first: `next dev` (fast) vs static build (faithful)

Two page classes, two verify paths. Choose by what your change touches — don't
pay for the 2-min static build when the page is client-rendered.

- **Client-rendered pages → `next dev` (fast, always fresh).** `/how-it-works`,
  `/sources`, and `/chat` render entirely in the browser (they read
  `useCity()` / `sessionStorage`, not build-time-injected props), so `next dev`
  renders them faithfully — and it has **no static cache to go stale**, which is
  the whole failure mode below. This is the default for a copy/layout/component
  change on those routes.

  ```bash
  cd app
  npm ci                         # once, if node_modules is missing
  npx next dev -p 4142           # UNIQUE port (not the 3000 default); background it
  # then screenshot http://localhost:4142/how-it-works/?city=la etc. (Playwright recipe below)
  ```

  City switch is a query string: `/how-it-works/?city=nyc`, `/sources/?city=la`,
  Chicago is the bare route. Kill the dev server by **PID** when done.

- **Home + detail pages → static build served from `out/`.** `/` and
  `/restaurant/<id>/` depend on `output: "export"` behaviour (`searchParams`,
  `generateStaticParams`) that `next dev` does NOT reproduce (see next section),
  so these MUST be verified against a real build. The detail-bundle gen is the
  slow part (~13 min for all licenses); if you only need the home page or a
  handful of detail pages, set `FSI_DETAIL_ONLY` to skip the full bundle sweep.

### EFS / NFS build gotchas (static path only)

The static build writes `.next` on EFS, which bites in two ways — `next dev`
avoids both:

- **Stale webpack cache serves OLD content.** A rebuild can reuse a stale
  `.next` cache and emit the *previous* version of a page (e.g. showing a
  removed section). If a static build shows content you already changed,
  `rm -rf app/.next` and rebuild.
- **`.nfs*` silly-rename busy files block the delete.** `rm -rf app/.next` can
  fail with `EBUSY: unlink '.next/.nfs…'` while a `next` process still holds the
  file. Kill the holder **by PID** (`ps aux | grep next`, then `kill <pid>`) —
  do **NOT** `pkill -f 'next build'` / `kill $(pgrep -f 'next build')`: that
  pattern matches your own shell's command line and self-kills the shell (the
  process dies with exit 144). After the holder is gone, the `rm -rf` succeeds.

## Build + launch (static export)

The app is a **static export** (`app/next.config.ts` → `output: "export"`): it reads
its data from S3 at **build** time and emits a fully pre-rendered site in `out/`. Two
consequences for verification:

- **`next dev` is NOT a faithful surface.** Under `output: "export"` the home page 500s
  (it can't read `searchParams`), and only the detail pages whose id is in
  `generateStaticParams` (top-500 by risk) exist. **Verify against a real build served
  from `out/`**, not `next dev`.
- The build's prebuild step pulls `scores.json` + `inspection_history.json` from S3 and
  falls back to the committed `app/public/data/*` when there are no AWS creds — so it
  builds offline, just with the committed (possibly older) data.

```bash
cd app
npm ci                                         # deps are NOT committed; use npm, not pnpm
npm run build                                  # prebuild syncs S3 → /tmp, then exports to out/ (~2 min, 500+ pages)
python3 -m http.server 4100 --directory out    # serve the static export
```

Drive `http://localhost:4100/…` (note `trailingSlash` is on — use `/restaurant/<id>/`).
Search/sort/filter are **client-side**, so query strings work even though the server is
static: `/?q=pizza`, `/?tier=High`, `/?sort=name` all filter in the browser.

If `npm run build` runs **out of memory** (`heap out of memory` / `SIGABRT`), do NOT just
raise `NODE_OPTIONS` — Next's static-gen workers don't inherit it (they cap at ~2 GB
regardless). The cause is a server loader holding too much data per worker; fix the loader
to read per-page slices.

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
  await page.goto("http://localhost:4100/restaurant/2304080/", { waitUntil: "networkidle" });
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

Only the **top-500-by-risk** detail pages are built into `out/`. If a test id 404s
(it wasn't in that cut, or the build used a different data snapshot), pick a built one
from `ls app/out/restaurant/`.

Surfaces to confirm:

- **Driver panel** — diverging bars (terra right = raises risk, sage left =
  lowers), axis legend, how-to-read footer, per-row hover tooltip.
- **"Top factor" chip** beside the gauge — correct driver, up/down arrow,
  colour matches direction, long labels truncate (with a `title` tooltip).
- Labels are plain English — **no raw `snake_case` column names**.
- No layout breaks at mobile width (390px).

Other routes worth a glance: `/` (map + list), `/how-it-works` (methodology).

## Route-conditional / global UI

For a component that shows or hides itself per route (e.g. something mounted in
the root layout that should be absent on one page), verify it on **both** a
**direct load** of the route AND **after client-side navigation** to it — a
component that stays mounted across nav can keep stale state and only the
direct-load path exercises the first render. Also account for **`trailingSlash`**
(on in `next.config`): `usePathname()` returns the trailing-slash form (e.g.
`/chat/`, not `/chat`), so a `pathname === "/route"` guard silently fails — test
that the show/hide actually holds, don't trust the code reading correct. None of
this is caught by `tsc`/lint/`next build`; it only shows up in the running app.

## Verifying chat content rendering (`/chat`)

The chat renders agent replies from a live backend (`queryAgent` → AgentCore),
which is NOT reachable from a static-export build. To screenshot how a specific
reply renders (bold, links, lists, long/edge-case content) **without** a backend,
**seed the transcript**: `ChatInterface` persists messages to `sessionStorage`
under `fsi_chat_messages` and hydrates them on mount. The floating launcher reuses
the same component, so the same seed renders there too.

Two things to get right:

- A browser **reload** starts a fresh conversation — the chat drops the saved
  transcript when Navigation Timing reports `type === "reload"`; a soft
  navigation keeps it. Playwright `page.goto(url)` is a `"navigate"`, so the seed
  survives — **do not use `page.reload()`** (it would clear the seed).
- **Seed with `addInitScript`** so the values are set before the page's own
  scripts run. Set both keys: `fsi_chat_messages` (a JSON array of
  `{role: "user" | "agent", content: string}`) and `fsi_chat_session` (any
  33+ char id). The renderer is markdown-lite: `**bold**`, lists, newlines, and
  `[label](url)` links (http(s) only — other schemes render as plain text).

```js
const messages = [
  { role: "user", content: "How common is food poisoning in the US?" },
  { role: "agent", content:
      "About **1 in 6 Americans** get sick each year.\nSources:\n" +
      "- [CDC](https://www.cdc.gov/food-safety/about/index.html)" },
];
await page.addInitScript((msgs) => {
  sessionStorage.setItem("fsi_chat_messages", JSON.stringify(msgs));
  sessionStorage.setItem("fsi_chat_session", "00000000-0000-4000-8000-000000000000");
}, messages);
await page.goto("http://localhost:4100/chat/", { waitUntil: "networkidle" });
await page.waitForTimeout(1000);
await page.screenshot({ path: "/tmp/chat.png", fullPage: true });
```

Confirm the **DOM**, not only the pixels — e.g. that source links became real
anchors (correct `href`, `target="_blank"`, `rel="noopener noreferrer"`) and that
an unsafe-scheme link is NOT an anchor:

```js
const anchors = await page.$$eval("a", (els) =>
  els.map((a) => ({ text: a.textContent, href: a.href, rel: a.rel })));
```

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
