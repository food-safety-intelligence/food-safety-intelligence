---
description: Drive the food-safety-intelligence web app's interactive components and report what works. Project-scoped; does NOT conflict with the user-level /qa skill.
---

Invoke the `qa-app` skill defined in `.claude/skills/qa-app/SKILL.md`.

Follow the skill's instructions exactly. In short:

1. Read `.claude/skills/qa-app/SKILL.md` for the full procedure.
2. Confirm the static server is up on `http://localhost:4000`. If not,
   launch it (the SKILL.md has the recipe).
3. Run the driver script:

   ```bash
   node .claude/skills/qa-app/drive.mjs
   ```

   Override the target URL with `QA_APP_URL=https://...` to point at
   CloudFront instead of localhost. Override viewport with `QA_VIEWPORT=mobile`.

4. Read the markdown report the script emits. Surface the verdict line and
   any real errors (page errors, console.errors, non-prefetch network
   failures). Note the screenshot path.
5. If the report flags broken components, point at the screenshot for that
   route so the user can see what happened.
6. Only if the user asks, file GitHub issues for the failures. Follow the
   "Filing GitHub issues" section in SKILL.md — it reads `findings.json`,
   commits the failing screenshots to the `qa-app-screenshots` branch, and
   opens (or comments on) one `qa-app`-labelled issue per run. Never file
   issues automatically.

Honest reporting: if a route timed out or you couldn't reach the server,
say which one and why. Don't pass silently.
