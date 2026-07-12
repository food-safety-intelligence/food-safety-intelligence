---
name: eval-agent
description: Run the Food Safety chat-agent eval (agents/eval/run_eval.py) — six deterministic gates (checker self-test, faithfulness vs scores.json, citation allow-list, and the records/review link-builder structure + injection checks), an opt-in live link-resolution check, then the live-agent guardrail suite across all covered cities (Chicago + NYC + LA) graded by a Nova Pro LLM judge. Use when asked to "eval the agent", "test the agent guardrails", "check the agent citations / links", "run the agent eval", or before merging a prompt/model/temperature/tool change to the agent. Covers the Bedrock execution-role setup, cost, and logging results to docs/agent-experiments.md.
---

# eval-agent

How to evaluate the Food Safety chat agent (`agents/`) on all fronts and log the
result. One entry point: `agents/eval/run_eval.py`.

## What it checks

Six **deterministic gates** run first (free, no Bedrock), then the live-agent
guardrail suite:

1. **Gate 1 — checker self-test**: the guardrail checker classifies canned
   good/bad responses correctly.
2. **Gate 2 — faithfulness**: samples `scores.json`, runs each record through
   `get_safety_score`, and asserts `risk_score` / `risk_tier` / `license_id` are
   relayed exactly (the batch-score-to-JSON contract, decision record 0010).
3. **Gate 3 — citation allow-list**: every URL the `food_safety_info` tool can
   cite is https and on the curated allow-list, so the agent can only cite
   authoritative public-health sources (decision record 0012).
4. **Gate 4 — records-link filters**: the `find_inspection_records` link builder
   emits a well-formed per-city query URL (Chicago / NYC filtered SoQL, LA county
   lookup page) whose filter matches the requested license_ids / ZIP / geo box.
5. **Gate 5 — review-link structure**: `find_reviews` returns direct
   Yelp/Google/TripAdvisor links, not search-page detours.
6. **Gate 6 — link-builder injection safety**: hostile input (quotes, SoQL/URL
   metacharacters) can't break out of the built query URL.

Gates 4–6 also run standalone via `--link-checks` (deterministic, no network).

**Live link-resolution** (`--links`, needs network, opt-in — not a gate):
fetches every **citation URL and every records link** and flags dead ones
(404/410/DNS); the records links are replayed as live SODA `$query` calls
(Chicago + NYC) to confirm they still resolve to ≥1 real record. A bot-block
(403/etc.) is reachable-but-restricted, not dead. Run before a release to catch
link rot; kept out of the gate because it hits external gov sites.

**Guardrails** (needs Bedrock): runs the agent on ~20 adversarial prompts across
all covered cities (**Chicago + NYC + LA**) — off-topic/scope (recipes, coding,
math), verdict-avoidance, no-record/no-fabrication, **out-of-coverage-city scope
and cross-city switching** (the agent covers Chicago, NYC, and LA; a city outside
those is declined, and NYC/LA grade framing is checked), prompt-injection,
tool-outage resilience, **general-info (a general food-safety question must be
answered WITH a cited source; a personal medical question must be steered to a
professional)**, and reviews — and grades each response. With `--judge`, an
**Amazon Nova Pro** LLM judge grades (more robust than the substring heuristics);
Nova Pro grading Nova 2 Lite avoids a model grading itself.

A few cases are **checker-only** (`self_test_only=True`): they run in the Gate-1
self-test but are skipped in the paid live run because the live tool chain can't
reach the behaviour. The closed-venue case (`closed_venue_historical`, decision
0014: a closed establishment's score must be disclosed as historical, not a live
signal) is one — a closed venue is gone from OpenStreetMap, so `find_restaurants`
never surfaces it for an end-to-end run; the self-test verifies the framing rule
against canned responses instead.

The full run **gates**: if any deterministic gate (1–6) fails, it stops before any
Bedrock call (no spend on a run that's already invalid).

## Running it

**Free / deterministic only (no AWS):**

    uv run python agents/eval/run_eval.py --self-test     # checker sanity
    uv run python agents/eval/run_eval.py --faithfulness  # tool vs scores.json
    uv run python agents/eval/run_eval.py --citations     # citation allow-list
    uv run python agents/eval/run_eval.py --link-checks   # records/review link structure + injection (gates 4-6)
    uv run python agents/eval/run_eval.py --links         # live-resolve citation + records links (network)

**Full run (needs Bedrock).** The agent calls Bedrock (Nova 2 Lite) and the
judge calls Nova Pro, so you need an identity with Bedrock access **and** model
access granted for both `amazon.nova-2-lite-v1:0` and `amazon.nova-pro-v1:0`
(us-east-1). In the SageMaker space the `bella_davies` IAM user in
`~/.aws/credentials` is **S3-only** — bypass it so boto3 falls through to the
**SageMaker execution role**, which has Bedrock:

    AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_REGION=us-east-1 \
      uv run python agents/eval/run_eval.py --judge

Re-check a single case cheaply after a fix:

    AWS_SHARED_CREDENTIALS_FILE=/dev/null AWS_REGION=us-east-1 \
      uv run python agents/eval/run_eval.py --judge --case is_it_safe_verdict

Override the judge model with `FSI_JUDGE_MODEL_ID`. Exit code is non-zero on any
failure, so the command can gate a release check.

## Cost (Bedrock us-east-1)

Per full `--judge` run ≈ **$0.08–0.10** (under a dime): the agent (Nova 2 Lite,
~$0.30/M in) plus the judge (Nova Pro $0.80/$3.20 per 1M in/out) over the ~20
adversarial cases (many short-circuit on a decline with no tool call).
Heuristic-only (no `--judge`) ≈ $0.05; the deterministic gates are $0. A single
`--case` re-check is ~1¢. Run 3–5× to smooth the agent's stochasticity
(`temperature=0.2`) and treat a category as regressed only if it fails
consistently.

## After running

Log the run in `docs/agent-experiments.md` — date, what changed (prompt/model/temp),
the pass counts, and any finding + fix. See the files there for the format. The
eval's value is catching guardrail regressions before a prompt/model change
merges to `main` (merging to `main` deploys to production).

## Notes

- The harness lives outside `tests/`, so CI does not run the Bedrock path; the
  deterministic gates can run anywhere (Gates 4–6 build links but hit no network).
- `find_restaurants` hits the live Overpass API, so the guardrail run needs
  network; the `tool_outage` case simulates an outage deliberately.
- A guardrail case carries a `city` field (chicago / nyc / la); the run sets the
  active city so NYC/LA framing and per-city inspection-records links are
  exercised, not just Chicago.
