# 0019 — Agent: on-demand data visualization via a sandboxed code tool

- **Status**: Proposed
- **Date**: 2026-07-19
- **Owners to ack**: Deepak (agentic AI / AWS — owner), Bella (eval / serve / web app), Jun (PM / scope guard)

> The chat agent can now generate a chart from the ACTIVE CITY's precomputed
> food-safety data when the user asks to plot / graph / visualize it (risk
> scores, tiers, trend direction, SHAP drivers, common drivers — filtered,
> sorted, aggregated any way). Because that space of questions is open-ended,
> there is no fixed tool for it: the model writes the pandas + matplotlib code
> and a new `visualize_data` tool runs it. This record captures why that is done
> with sandboxed **code execution** (not a constrained chart spec, not in-browser
> Pyodide), how it stays inside the project's hard rules, and the scope carve-out
> to the "no writing code" decline — none of which is recoverable from the diff.

## Decision

1. **New tool `visualize_data(code, title)`.** The model authors short pandas +
   matplotlib code over a preloaded DataFrame `df` (the ACTIVE CITY's
   `scores.json`, plus derived `top_driver` / `top_driver_topic` columns for
   "common drivers"). The tool runs it and returns the rendered image + the exact
   script.

2. **Execution is server-side, in an isolated Bedrock AgentCore Code Interpreter
   with the network OFF.** The code is untrusted (model-authored), so it runs in a
   hard-isolated microVM that can read the data and draw a figure but cannot reach
   the network or any secret. We chose this over (a) a constrained chart-spec DSL —
   too limiting for "filter/sort/aggregate any way" — and over (b) in-browser
   Pyodide — which ships the data to the client, runs model code in the app's own
   origin (a real exfiltration surface; WASM is not a hard boundary), and, running
   *after* the agent has replied, cannot ground the caption. The server sandbox
   grounds the caption in one turn and leaks nothing.

3. **This is NOT request-time model inference.** A chart is an *aggregate of the
   already-published batch `scores.json`* the web app serves — never a new
   prediction. The permanent batch-score-to-JSON design ([0010](0010-agent-no-request-time-scoring-and-no-record.md))
   is unchanged; `visualize_data` reads the same precomputed file the other
   scoring tools do.

4. **Grounding.** The model's code must `print()` the numbers it plots; the tool
   returns that stdout as `summary`, and the agent must caption ONLY from those
   figures — never a number the summary does not contain. Same anti-fabrication
   rule as every other tool ([0012](0012-agent-general-food-safety-education-with-cited-sources.md)):
   a claim must come from a tool result.

5. **Transport contract.** The rendered PNG and the script are uploaded to a
   private S3 prefix and handed back as short-lived, unguessable **presigned
   URLs** inside a fenced ` ```eatelligence-chart ``` ` block the agent includes
   verbatim. The web app parses that block out of the reply text (like it already
   parses markdown links) and renders the chart inline, with an image/script
   toggle, download, and an enlarge modal; the `/chat` page also lists every chart
   in a left rail. The image bytes and the (long) script never round-trip through
   the model or the replayed history — only two short URLs do.

6. **Scope carve-out.** "Decline writing code/software" now means *general-purpose*
   software. Writing code to chart the ACTIVE CITY's own food-safety data is
   in-scope; charting other cities or non-food data is declined like any off-topic
   request. Charts are aggregates and never a verdict — the risk-signal framing and
   the no-"safe"/"unsafe", no-eat/don't-eat rules still apply to captions.

## Boundaries that do NOT change

- No new datasets: charts come from the existing per-city `scores.json` only.
- The Bedrock guardrail is unchanged (it denies only personalised-medical and
  legal topics); the code carve-out lives in the system prompt, not the guardrail.
- Safe by default off AWS: with no sandbox/bucket configured (local, tests, CI)
  the tool **stubs** — it does not execute the code and returns a placeholder, so
  nothing untrusted runs off the sandbox.

## Consequences

- **New infra (Deepak's account):** an AgentCore Code Interpreter (network SANDBOX)
  + a private `charts/` S3 prefix with a TTL + IAM on the runtime role. One-time
  provisioning; see `agents/runbooks/2026-07-19-code-interpreter-provisioning.md`.
  Runtime env: `FSI_SANDBOX_USE_STUB=false`, `FSI_CHART_BUCKET`,
  `FSI_CODE_INTERPRETER_ID`.
- **Cost** is per-second sandbox compute — on the order of a small fraction of a
  cent per chart; negligible at demo/capstone volume.
- **Eval:** a deterministic tool test (`visualize_data/test_handler.py`, stub mode)
  plus guardrail cases `chart_in_scope` / `chart_offtopic` with checker self-tests
  that ride the free `--self-test` gate in CI. The presigned-URL round trip and the
  live sandbox are validated by a post-deploy smoke test, not in CI.
