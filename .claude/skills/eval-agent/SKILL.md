---
name: eval-agent
description: Run the Food Safety chat-agent eval (agents/eval/run_eval.py) — deterministic gates (checker self-test + faithfulness vs scores.json) then the live-agent guardrail suite graded by a Nova Pro LLM judge. Use when asked to "eval the agent", "test the agent guardrails", "run the agent eval", or before merging a prompt/model/temperature change to the agent. Covers the Bedrock execution-role setup, cost, and logging results to docs/agent-experiments.md.
---

# eval-agent

How to evaluate the Food Safety chat agent (`agents/`) on all fronts and log the
result. One entry point: `agents/eval/run_eval.py`.

## What it checks

1. **Gate 1 — checker self-test** (deterministic, no Bedrock): the guardrail
   checker classifies canned good/bad responses correctly.
2. **Gate 2 — faithfulness** (deterministic, no Bedrock): samples `scores.json`,
   runs each record through `get_safety_score`, and asserts `risk_score` /
   `risk_tier` / `license_id` are relayed exactly (the batch-score-to-JSON
   contract, decision record 0010).
3. **Guardrails** (needs Bedrock): runs the agent on adversarial prompts across
   six categories — off-topic/scope, verdict-avoidance, no-record/no-fabrication,
   non-Chicago scope, prompt-injection, tool-outage resilience — and grades each
   response. With `--judge`, an **Amazon Nova Pro** LLM judge grades (more robust
   than the substring heuristics); Nova Pro grading Nova 2 Lite avoids a model
   grading itself.

The full run **gates**: if either deterministic gate fails, it stops before any
Bedrock call (no spend on a run that's already invalid).

## Running it

**Free / deterministic only (no AWS):**

    uv run python agents/eval/run_eval.py --self-test     # checker sanity
    uv run python agents/eval/run_eval.py --faithfulness  # tool vs scores.json

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

Per full `--judge` run ≈ **$0.03** (~3¢): the agent (Nova 2 Lite, ~$0.30/M in)
plus the judge (Nova Pro $0.80/$3.20 per 1M in/out) over six short, mostly
short-circuiting cases. Heuristic-only (no `--judge`) ≈ $0.02; the deterministic
gates are $0. A single `--case` re-check is ~1¢. Run 3–5× to smooth the agent's
stochasticity (`temperature=0.2`) and treat a category as regressed only if it
fails consistently.

## After running

Log the run in `docs/agent-experiments.md` — date, what changed (prompt/model/temp),
the pass counts, and any finding + fix. See the files there for the format. The
eval's value is catching guardrail regressions before a prompt/model change
merges to `main` (merging to `main` deploys to production).

## Notes

- The harness lives outside `tests/`, so CI does not run the Bedrock path; the
  two deterministic gates can run anywhere.
- `find_restaurants` hits the live Overpass API, so the guardrail run needs
  network; the `tool_outage` case simulates an outage deliberately.
