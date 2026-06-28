# Docs

Map of this folder. Short markdown only (per `CLAUDE.md` — no auto-generated API docs).

- **[project_plan.md](project_plan.md)** — the project's intent and testable
  claims (problem, data, approach, NLP + fairness strategy, success criteria).
  `CLAUDE.md` remains the scope authority; this is the why/what/how behind it.
- **[decisions/](decisions/)** — decision records: the "why" behind choices that
  aren't recoverable from a diff. Start at [decisions/README.md](decisions/README.md)
  for the themed index.
- **[interface_contracts.md](interface_contracts.md)** — source of truth for the
  cross-team data contracts (the three parquets + `scores.json` schema), the
  temporal split, and **data cleaning** (dedup, modelable-results / burn-in /
  right-truncation filters, structural-null handling, the lat/lon geo guard). Schema
  changes need owner sign-off.
- **[model-experiments.md](model-experiments.md)** — the human experiment ledger: every modeling
  run with its hypothesis, result, and verdict (negative results included).
- **[agent-experiments.md](agent-experiments.md)** — the same ledger for the chat-agent
  eval runs (faithfulness + guardrails), the findings and prompt/judge changes they drove.
- **[fairness_audit.md](fairness_audit.md)** — living record of the group-performance
  fairness audit (per-facility-type / per-ZIP verdict + interpretation). *(lands with
  the fairness-audit PR.)*
- **[weekly/](weekly/)** — Friday async check-ins, one file per week (`YYYY-MM-DD.md`).
