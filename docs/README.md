# Docs

Map of this folder. Short markdown only (per `CLAUDE.md` — no auto-generated API docs).

- **[decisions/](decisions/)** — decision records: the "why" behind choices that
  aren't recoverable from a diff. Start at [decisions/README.md](decisions/README.md)
  for the themed index.
- **[interface_contracts.md](interface_contracts.md)** — source of truth for the
  cross-team data contracts (the three parquets + `scores.json` schema), the
  temporal split, and **data cleaning** (dedup, modelable-results / burn-in /
  right-truncation filters, structural-null handling, the lat/lon geo guard). Schema
  changes need owner sign-off.
- **[experiments.md](experiments.md)** — the human experiment ledger: every modeling
  run with its hypothesis, result, and verdict (negative results included).
- **[weekly/](weekly/)** — Friday async check-ins, one file per week (`YYYY-MM-DD.md`).
