---
name: qa-app
description: Drive the running Next.js web app's interactive components — buttons, inputs, links, and a few specific hover targets — and report what works and what's broken. Use on demand before a deploy, after a big PR, or any time you want a "kid clicking everything" sanity pass over `app/`. Different in shape from `verifier-app` (which proves one diff); this one exercises the whole UI.
---

# qa-app

Exercise the web app's UI broadly. Click every button. Type into every input.
Find anything broken. Report what worked and what didn't in plain text.

## When to use

- Before deploying to CloudFront.
- After merging an `app/*` PR that touches more than one component.
- When something feels off in the app and you want to find what's actually broken.
- When the user asks "is everything still working?"

This is **not** a periodic test suite. Run it when there's a reason to.
For per-change verification (one diff, one set of screenshots), use
`verifier-app` instead.

## Pre-flight

1. Confirm the app is built and a static server is running. If not, launch it:

   ```bash
   cd app
   npm run build      # ~30s; runs the prebuild S3 sync + webpack
   python3 -m http.server 4000 --directory out > /tmp/qa-app-server.log 2>&1 &
   ```

   Default target is `http://localhost:4000`. Set `QA_APP_URL` to override
   (e.g. `https://d1uefdb2te19wk.cloudfront.net` to QA the live site).

2. Confirm Playwright + Chromium are installed. If not:

   ```bash
   cd app
   npm install --no-save playwright
   npx playwright install chromium
   ```

## Drive it

From the `app/` directory:

```bash
NODE_PATH="$PWD/node_modules" node ../.claude/skills/qa-app/drive.mjs
```

Override the target URL:

```bash
QA_APP_URL=https://d1uefdb2te19wk.cloudfront.net \
  NODE_PATH="$PWD/node_modules" node ../.claude/skills/qa-app/drive.mjs
```

The script:

- Visits the home page and picks a random restaurant detail route from the
  rendered links (so the exercised detail page changes each run).
- For each route: enumerates every visible `<button>`, `<input>`,
  `<textarea>` and clicks/types into each. Catches console errors,
  unhandled rejections, and failed network requests.
- Tries a few specific hover targets (map pins, driver bars) that a
  generic crawler wouldn't trigger.
- Takes one screenshot per route (initial + final state) and saves them to
  `/tmp/qa-app-<timestamp>/`.
- Emits a markdown report to stdout.

## Output shape

Plain markdown blob. One section per route. Each section names the actions
tried, the errors caught, and any network failures. Example:

```
## QA pass for http://localhost:4000
screenshots → /tmp/qa-app-2026-06-27-14-32-00

### home (/)
**Actions:**
- ✓ typed "pizza" into "Search establishments or addresses"
- ✓ clicked "Search" (no nav, no error)
- ✓ clicked "Highest risk" sort toggle
- → clicked "Open profile" → navigated to /restaurant/14616/ (went back)
- enumerated 247 links

**Errors:**
- (none)

### detail (/restaurant/14616/)
...
```

If the report is empty or short, the route may have rendered but had
nothing interactive; mention that explicitly rather than passing silently.

## What this skill is NOT

- It does not compare against a baseline. Layout changes are not failures.
- It does not assert specific copy strings (use `verifier-app` for that).
- It does not exercise the agent chat conversation; it confirms the chat
  UI renders, but invoking the agent requires the prod Lambda + ALB chain.
- It does not test mobile viewports by default. Rerun with
  `QA_VIEWPORT=mobile` if you want a 390px pass.

## Things the script will not catch on its own

A few interactions need to be added by hand when the UI changes:

- **Map pin click + popup**: the script hovers a marker but does not click
  it. If you change the pin/popup interaction, add a click step here.
- **Mobile menu toggle**: only present at <880px viewport. Run with
  `QA_VIEWPORT=mobile` to exercise.
- **Chart hover tooltips**: Recharts SVG bars don't always trigger via
  generic enumeration; add explicit hover steps in `drive.mjs` if a chart
  tooltip ever regresses.

## Honest reporting

The verdict line at the end of the report should reflect what you actually
saw. Don't say PASS if you skipped a route because Playwright timed out;
say which route, why, and what you did instead. If a button click failed
because the button was off-screen, that's a finding, not a failure of the
script.
