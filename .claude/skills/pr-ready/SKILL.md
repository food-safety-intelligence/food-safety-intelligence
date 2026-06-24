---
name: pr-ready
description: Run the same checks CI runs (Python ruff + pytest, web-app eslint + tsc + vitest) against the local branch BEFORE pushing, fix anything that fails, and draft a clear PR description summarizing the change. Use when the user says "pr-ready", "/pr-ready", "run CI locally", "check before I push/PR", or asks to prep a PR. Mirrors .github/workflows/ci.yml exactly so a green run here means a green run on GitHub.
---

# pr-ready

Run the **same checks GitHub CI runs**, locally, against the current branch
before pushing or opening a PR — then fix every failure and draft the PR
description. The goal is a one-shot green CI: if these pass locally, the
`CI` workflow (`.github/workflows/ci.yml`) passes on GitHub.

The checks below are copied from `ci.yml`. If that file changes, this skill
must change with it — they are the same gate (`make lint` / `make test` / the
`.githooks/pre-commit` hook all mirror it too).

## Environment
- **Python**: CI uses `uv` on Python 3.12. Locally, use the repo venv directly —
  `.venv/bin/python` (base conda lacks `shap`/`xgboost`; `foodsafety` is
  editable-installed in `.venv`). `make test` / `make lint` resolve `uv run
  python` if `uv` is on PATH, else fall back to `python3`.
- **Web app**: use `npm` (NOT pnpm) in `app/`. `app/node_modules` can lag
  `package.json` — if tsc reports "cannot find module" only on test files or a
  devDep looks missing, run `npm install` in `app/` to sync, then re-run.
- Run only what you need: if the change is Python-only, the app job can be
  skipped (and vice-versa) — but say which half you skipped.

## Step 1 — Python checks (ruff + pytest)

Three commands, in CI order. Run all three even if an earlier one fails, so you
see every failure at once.

```bash
.venv/bin/python -m ruff check .          # lint
.venv/bin/python -m ruff format --check . # format (check only — does NOT rewrite)
.venv/bin/python -m pytest                # tests
```

`make lint` runs the two ruff commands; `make test` runs pytest. Notebooks are
excluded from ruff in `pyproject.toml` — this gates the package, `scripts/`,
`tests/`, and agents only.

## Step 2 — Web-app checks (eslint + tsc + vitest)

Only if the change touches `app/`. Same order as CI:

```bash
cd app
npm ci            # locked install, matches CI; use plain `npm install` only to resync a lagging node_modules
npm run lint      # eslint
npx tsc --noEmit  # typecheck
npm test          # vitest
```

## Step 3 — Fix every failure

Work one failure at a time; re-run the single failing command after each fix
before moving on.

- **Ruff lint** — auto-fix the mechanical ones, then re-check:
  `.venv/bin/python -m ruff check --fix .`. For a genuinely-deliberate finding
  use a **scoped** `# noqa: <CODE>` (e.g. an import that must follow `sys.path`
  setup), never a bare `# noqa` (CLAUDE.md rule).
- **Ruff format** — `format --check` only reports; apply with
  `.venv/bin/python -m ruff format .`.
- **Pytest** — read the assertion, fix the **code or the test, not the symptom**.
  Leak-guard tests (`.shift()` / `< as_of_date`) and the both-metrics promotion
  gate exist on purpose — don't loosen them to get green; if one fails, the
  feature is wrong, not the test. The `test_features_baseline_alignment`
  integration test fails until the parquet is rebuilt — that's an expected
  tripwire mid-feature-change, not a CI bug (see `update-model`).
- **ESLint / tsc** — fix the type or lint error at the boundary; no `any`
  (strict mode). Don't silence with `eslint-disable` unless truly warranted.
- **Vitest** — same rule as pytest: fix the cause.

Keep the fixes **scoped to this branch's change** — don't take on repo-wide lint
debt in files you didn't touch. Show each fix inline in chat (snippet or diff),
per the user's review preference. Get an explicit go-ahead before committing —
don't bundle the fix and the commit.

Re-run the full Step 1 / Step 2 command set once at the end to confirm all green
together.

## Step 4 — Draft the PR description

Once everything is green, summarize the change. Base it on the real diff, not
memory:

```bash
git fetch origin main          # token-bridge if gh is off PATH (see CLAUDE.md GitHub auth)
git diff --stat origin/main...HEAD
git log --oneline origin/main..HEAD
```

Write the description in **clear, concise, plain language** (CLAUDE.md
communication rule) — short sentences, spell out non-obvious terms, no internal
finding IDs (C1/M2/etc.). Structure:

- **What & why** — one or two sentences: what the change does and the problem it
  solves.
- **Changes** — a short bullet per cohesive change, grouped by area
  (Python pipeline / web app / docs). Describe behavior, not line counts.
- **Verification** — the checks you ran and their result: "ruff + pytest green,
  app eslint + tsc + vitest green." State honestly which half you skipped and
  why if you skipped one.
- **Contract / scope notes** — if the diff touches a cross-team contract
  (the three parquets or `scores.json`, see `docs/interface_contracts.md`), say
  so and note it needs a PR tagging every owner (Arun, Bella, Deepak, Aurelia,
  Jun). If it touches `app/`, the PR needs verification screenshots — run
  `/verify` (uses `verifier-app`) and drag the PNGs into the PR description in
  the GitHub web UI (a private-repo repo can't inline committed images).

Output the description as a markdown block the user can paste, or — only on
explicit go-ahead — set it via the GitHub REST API (`gh pr edit` is broken in
this space; see CLAUDE.md GitHub auth).

## What this skill does NOT do
- It does not commit, push, or open the PR on its own — it gets you to a green,
  reviewed state and a ready-to-paste description. Wait for the user's go-ahead
  (no bundled actions, CLAUDE.md workflow rule).
- It does not run the data pipeline or notebooks — that's `update-model`.
- It does not replace `/verify` for visual changes — CI's tsc/vitest pass while
  layout/overflow/contrast regressions ship.
