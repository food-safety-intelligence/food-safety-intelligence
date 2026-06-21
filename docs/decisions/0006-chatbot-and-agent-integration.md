# 0006 — Chatbot surface and agent↔model integration

- **Status**: Accepted — Part 1 (stub) shipped; Part 2 (real wiring) planned, not built
- **Date**: 2026-06-21
- **Owners to ack**: Aurelia + Jun (web app), Deepak (agent), Jun (PM / scope)

> How the conversational agent connects to the web app and the model. Records
> both what shipped now (a stubbed chatbot) and the agreed path to wire the real
> agent later, so the future work is a swap rather than a redesign.

## Context

Deepak's agent (`agents/`, Strands + Bedrock Nova 2 Lite) was **not** integrated
into the web app, and the dependency ran backwards: the agent *reads* the app's
precomputed `scores.json`, while the app had **no API route, no `fetch`, and no
agent reference**. The agent's own scoring is a stub (`SAGEMAKER_USE_STUB` →
`md5(name+address) → Beta`), and its real path targets a SageMaker endpoint that
does not exist.

The app's standing contract is "two languages joined at JSON": Python writes
`scores.json`, the app reads only that static file, and nothing calls a model at
request time. A conversational agent that answers free-text questions cannot be
precomputed — it is inherently a request-time feature — so it needs its own
decision rather than bending the batch-JSON contract.

## Decisions

1. **The chatbot is the only live-inference surface.** Map, search, and the
   restaurant detail pages stay on the batch-JSON contract (read `scores.json`,
   no model call). Only the chatbot does anything at request time. The old
   "no request-time inference / no local sidecar" rule was written for a
   static-JSON MVP and does **not** bind a free-text conversational agent; this
   record is the documented exception.

2. **Current implementation = a stub, with the real seam in place.** A floating
   `ChatWidget` (hand-rolled Tailwind, no shadcn) is mounted site-wide from the
   root layout. The app's first route handler, `/api/agent`, sits behind
   `AGENT_USE_STUB` (default on): it answers from `scores.json` by name/address
   substring match, ranked by risk — deterministic, no model call. The inactive
   real branch proxies to an agent sidecar at `AGENT_URL`. This mirrors the
   Python `sagemaker_stub` idiom (ship both `_invoke_stub` and `_invoke_real`).

3. **Future real path is local-first, no AWS.** When wired for real, scoring runs
   **in-process on the laptop**: load the saved calibrated joblib model and reuse
   the model team's own `serve/predict_batch` (`build_scores_table`,
   `score_to_tier`) and `explain/shap_drivers` — so the agent and the precomputed
   `scores.json` agree by construction rather than via a parallel reimplementation.
   The conversational layer is a **stubbed orchestrator** (scripted
   find → score → explain), with `BedrockModel`/Nova as a later swap. A small
   **FastAPI sidecar** holds the model warm and the route proxies to it.
   **SageMaker stays a documented future swap only** — not required for the demo.

4. **The agent's feature list tracks the model contract via a test, not a
   runtime import.** `FEATURE_ORDER` was hardcoded and had drifted (26 while the
   contract moved 26 → 30 → 33 → 36). It is now aligned to
   `foodsafety.models.baseline.ALL_FEATURES`, guarded by a test that imports
   `ALL_FEATURES` and fails on divergence. A runtime import was rejected because
   it pulls sklearn+pandas (~4 s) into the otherwise dependency-light stub.

## Consequences

- **Positive:** the chatbot is demoable today with zero AWS; the route is the
  single swap seam, so Part 2 changes the backend, never the UX; the map/detail
  pages keep their fast, reproducible static-JSON path.
- **Costs / risks to revisit:**
  - The real path introduces one live process (the sidecar) — a `next dev`
    companion, and new Python deps (`fastapi`, `uvicorn`) that need
    `pyproject.toml` + justification when added.
  - The agent's `handler._build_feature_row` still **fabricates** features
    (missing 12 of the 36 contract columns → 0 on the real path); real scoring
    requires replacing it with a `features.parquet` lookup keyed by `license_id`
    (the planned next step). Until then, do not read the agent as scoring "for real."
  - Local in-process inference couples `agents/` → the `foodsafety` package; fine
    for the laptop/sidecar path, but a standalone Lambda deploy would need the
    feature list vendored.
  - This is the first `/api/agent` route — it crosses the still-written repo
    CLAUDE.md "no API routes / no request-time inference" rule. Flagged in the PR;
    resolve in the CLAUDE.md scope refresh.

## Sequenced plan (Part 2)

1. Real `features.parquet` lookup in `get_safety_score` (replace fabrication).
2. Local in-process joblib inference reusing `predict_batch` + `shap_drivers`.
3. Stub-LLM orchestrator (no Bedrock).
4. FastAPI sidecar + flip the `/api/agent` real branch; `BedrockModel`/Nova later.

Each lands as its own branch off fresh `main`, validated independently.
