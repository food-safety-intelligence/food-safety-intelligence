# 0006 — Chatbot surface and agent↔model integration

- **Status**: Accepted — Part 1 (stub) shipped; real wiring planned
- **Date**: 2026-06-21
- **Owners to ack**: Aurelia + Jun (web app), Deepak (agent), Jun (PM / scope)

> How the conversational agent connects to the **deployed** web app and the model.
> Records the stub that shipped and the agreed real path. Companion to the design
> proposal in `design/agentic-ai-architecture.md` — **that doc is the spec; this
> record is the decision.** Now that the app is hosted on AWS, the two converge.

## Context

Deepak's agent (`agents/`, Strands + Bedrock Nova 2 Lite) was **not** integrated
into the web app, and the dependency ran backwards: the agent *reads* the app's
precomputed `scores.json`, while the app had **no API route, no `fetch`, and no
agent reference**. The agent's own scoring is a stub
(`SAGEMAKER_USE_STUB` → `md5(name+address) → Beta`).

The app is **deployed on AWS Amplify and Vercel simultaneously**, both
**auto-deploying on push to `main`**, and **features/scores are moving to S3**.
So this is a hosted product, not a laptop demo — the earlier "local-first / no
AWS / no deployment" framing (repo CLAUDE.md and the first draft of this record)
is superseded. A conversational agent answering free-text questions is inherently
request-time and cannot be precomputed, so it needs its own decision rather than
bending the batch-JSON contract.

## Decisions

1. **The chatbot is the only live-inference surface.** Map, search, and detail
   pages stay on the **batch-scored JSON** (moving to S3) — read-only, no model
   call. Only the chatbot does request-time inference. The repo CLAUDE.md
   "no request-time inference / no deployment / no AWS" lines describe the
   superseded laptop MVP; the live Amplify/Vercel deployment is the current reality.

2. **Current implementation = a data-backed stub, with the real seam in place.**
   A floating `ChatWidget` is mounted site-wide; the app's first route,
   `/api/agent`, sits behind `AGENT_USE_STUB` (default on) and answers from
   `scores.json` by name/address keyword match — deterministic, **no model call**.
   It reuses `loadScores`, so it follows the S3 migration automatically. The
   inactive real branch proxies to the hosted agent. **Note:** because
   Amplify/Vercel auto-deploy `main`, merging this publishes the stub to both
   live URLs — treat `main` as production.

3. **The real path adopts the design proposal (we're on AWS now).** An
   **AgentCore Harness (Bedrock Nova 2 Lite)** orchestrates the three Lambda
   tools — `find_restaurants` (Overpass), `get_safety_score`, `explain_restaurant`
   (scores.json on S3). The deployed Next.js `/api/agent` route proxies to
   AgentCore (single response now per the spec's Phase 2a; SSE streaming later).
   This replaces the first draft's "local FastAPI sidecar," which does not fit a
   hosted app.

4. **Hosted inference for `get_safety_score` = joblib-in-Lambda now, SageMaker
   later.** The Lambda **loads the calibrated model from S3 and predicts**,
   reusing the model team's `serve/predict_batch` (`build_scores_table`,
   `score_to_tier`) + `explain/shap_drivers` — so the agent and the batch
   `scores.json` agree by construction. A separate **SageMaker real-time endpoint
   is NOT used initially**: disproportionate for a sub-megabyte model and an
   always-on cost. SageMaker (Serverless Inference, or a real-time endpoint) is
   the **documented future upgrade** for when the model grows (XGBoost / DL),
   needs scale, or as a deliberate AWS showcase. This is the one change from the
   spec's §4, which assumed a SageMaker endpoint.

5. **Real feature lookup, not fabrication.** `get_safety_score`'s
   `_build_feature_row` currently fabricates features; replace it with a lookup of
   the precomputed feature row (`features.parquet` → S3) keyed by `license_id`.
   Cold-start (no license match) → "no Chicago inspection record," never
   fabricated zeros.

6. **The agent's feature list tracks the model contract via a test, not a runtime
   import.** `FEATURE_ORDER` had drifted (26 vs the contract's 26→30→33→36); it is
   now aligned to `foodsafety.models.baseline.ALL_FEATURES`, guarded by a test that
   fails on divergence (PR #18). A runtime import was rejected because it pulls
   sklearn+pandas (~4 s) into the otherwise dependency-light tool.

## Consequences

- **Positive:** the chatbot is demoable now on the live site with zero new infra;
  the route is the single swap seam (Part 2 changes the backend, never the UX);
  the real path **converges with Deepak's AWS-native design** rather than inventing
  a parallel local stack; map/detail keep the fast batch-JSON path on S3.
- **Costs / risks to revisit:**
  - **Auto-deploy:** merging to `main` publishes to the live Amplify + Vercel
    URLs. Main is production; review and verify before merging chatbot changes.
  - `get_safety_score._build_feature_row` still **fabricates** until the features
    lookup lands — do not read the agent as scoring "for real" yet.
  - New AWS pieces (AgentCore harness, the inference Lambda, Bedrock model access,
    S3 data layout) sit in Deepak's agent workstream — needs creds + cost awareness.
  - The stub route reads the full `scores.json` per cold start (amortized by the
    module cache); once data is on S3, `loadScores` fetches from S3 — owned by the
    S3 migration, not this record.

## Sequenced plan (real wiring)

1. Move features/scores to **S3**; point `loadScores` and the Lambda tools at S3.
2. `get_safety_score` Lambda: real `features.parquet` lookup + **joblib-from-S3
   inference** (reuse `predict_batch` / `shap_drivers`).
3. Wire the **AgentCore harness** (Bedrock Nova); `/api/agent` proxies to it; flip
   `AGENT_USE_STUB=false`.
4. SSE streaming + the spec's map-integrated UI
   (`NLPSearchBar` / `AgentChatPanel` / `AgentResultCards`), if pursued — the
   current `ChatWidget` is a simpler standalone surface.
5. **SageMaker** as a later inference upgrade if the model grows or for showcase.
