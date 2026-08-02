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
- Emits a markdown report to stdout, and writes a machine-readable
  `findings.json` (same dir as the screenshots) for the issue-filing step.

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

## Filing GitHub issues for what broke

**Opt-in, not automatic.** Only file issues when the user asks ("file
issues for the failures", "open tickets for what's broken"). A QA run that
finds nothing should never open an issue.

The driver writes `findings.json` next to the screenshots. Each route has
`hasFailures`, its `errors` / `networkFailures` / `failedActions`, and the
`screenshots` paths. File **one issue per run** that lists every failing
route, and attach the failing routes' screenshots.

This repo is **private**, so an image URL pointing at repo content does not
render inline (GitHub's proxy fetches it unauthenticated and 404s). The
automated path is **commit the screenshot, then link it** — the link opens
the image (one click), it is not embedded. The commit and the issue both go
through the GitHub REST API; `gh` is not installed in this space, so read the
OAuth token from `~/.config/gh/hosts.yml` and call the API with `curl`:

```bash
TOK=$(python3 -c "import yaml,os; h=yaml.safe_load(open(os.path.expanduser('~/.config/gh/hosts.yml'))); k=list(h)[0]; print(h[k]['oauth_token'])")
REPO=food-safety-intelligence/food-safety-intelligence
API=https://api.github.com/repos/$REPO
```

Steps (only for routes with `hasFailures: true`):

1. **Ensure the label exists** (ignore the 422 if it already does):

   ```bash
   curl -s -X POST -H "Authorization: token $TOK" "$API/labels" \
     -d '{"name":"qa-app","color":"d73a4a","description":"qa-app skill findings"}' >/dev/null
   ```

2. **Ensure a screenshots branch exists.** Keep QA screenshots off feature
   branches and `main` — commit them to a dedicated `qa-app-screenshots`
   branch. If `GET $API/git/ref/heads/qa-app-screenshots` 404s, create it
   from `main`'s SHA via `POST $API/git/refs`
   (`{"ref":"refs/heads/qa-app-screenshots","sha":"<main sha>"}`).

3. **Upload each failing route's screenshots** to that branch under
   `design/qa-app/<run-timestamp>/<route>-<state>.png` using the Contents
   API (base64, no local git needed):

   ```bash
   B64=$(base64 -w0 /tmp/qa-app-<ts>/home-final.png)
   curl -s -X PUT -H "Authorization: token $TOK" \
     "$API/contents/design/qa-app/<ts>/home-final.png" \
     -d "{\"message\":\"qa-app screenshot\",\"branch\":\"qa-app-screenshots\",\"content\":\"$B64\"}"
   ```

   The link to put in the issue is the blob view (renders a clickable image
   for any logged-in teammate):
   `https://github.com/$REPO/blob/qa-app-screenshots/design/qa-app/<ts>/home-final.png`

4. **Build the issue body** — one section per failing route: its
   `failedActions`, `errors`, and `networkFailures` as bullets, then the
   screenshot link(s). Head it with the run's app URL and viewport.

5. **De-dupe before creating.** `GET $API/issues?state=open&labels=qa-app`.
   Use a stable title: `qa-app: failures on <comma-separated routes> (<viewport>)`.
   - If an open issue has that exact title, **POST a comment** to it with the
     new run's body (`POST $API/issues/<n>/comments`) instead of opening a
     duplicate.
   - Otherwise **create** it: `POST $API/issues` with
     `{"title":..., "body":..., "labels":["qa-app"]}`.

6. **Report back** the issue URL(s) you created or commented on, and the
   `qa-app-screenshots` paths you pushed. Screenshots on that branch are
   disposable QA artifacts — prune the branch when it gets large.

Honest reporting applies here too: only file the failures the run actually
caught. A spurious click timeout on a hidden control is not a bug — judge
before filing (see "Honest reporting" below).

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
