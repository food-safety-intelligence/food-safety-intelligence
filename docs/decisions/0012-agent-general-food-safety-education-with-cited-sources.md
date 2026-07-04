# 0012 — Agent: general food-safety education with cited authoritative sources

- **Status**: Proposed
- **Date**: 2026-06-28
- **Owners to ack**: Deepak (agentic AI — owner), Bella (eval / serve), Jun (PM / scope guard)

> The chat agent was deliberately narrow: it found Chicago restaurants and
> attached a risk signal, and it **declined** everything else — including general
> food-safety and foodborne-illness questions ("how common is food poisoning?",
> "what is Listeria?"). This records why we widened it to also answer those
> general questions, how we keep the answers trustworthy, and the boundaries we
> kept. The decision reverses part of the earlier tight scope, so it is not
> recoverable from the diff.

> **Update (2026-07-04) — the `OffTopicNonFoodSafety` guardrail topic was later
> REMOVED, superseding what this record says below.** Same day this DR was written,
> a follow-up found that the negatively-defined off-topic topic made Bedrock's
> classifier over-match and **block ~100% of queries** (including core risk
> lookups), so commit `9c92ce7` dropped it: the guardrail now denies only
> **personalised medical + legal advice**, and off-topic requests (recipes, other
> cities, chit-chat) are declined by the **system prompt** instead (verified by the
> eval's off-topic / other-city cases). Confirmed live 2026-07-04: the deployed
> guardrail has only `PersonalisedMedicalAdvice` + `LegalAdvice`. The "re-scoped
> off-topic topic survives" wording in the sections below is stale — read it as
> historical.

## Decision

1. **The agent now answers general food-safety / foodborne-illness questions**
   (statistics, what a pathogen is, safe cooking temperatures, who is at risk, how
   to prevent illness) in addition to its Chicago restaurant-risk job.

2. **Every general answer is grounded in a curated source and cites it.** A new
   tool, `food_safety_info`, returns short vetted facts plus a link to the
   authoritative source the fact came from. The system prompt requires the agent
   to state statistics only from the tool's returned summary and to cite the
   returned link — it must not recall numbers from memory or invent a URL.

3. **Citations come only from a curated allow-list of authoritative sources** —
   CDC, FDA, USDA FSIS, FoodSafety.gov, WHO, NIH MedlinePlus, the Partnership for
   Food Safety Education, and Chicago / Illinois / Cook County public health plus
   the Chicago Data Portal. **No news outlets and no open web search.**

4. **The safety boundaries that defined the agent are kept.** It still gives no
   personalised medical/legal advice (general education is allowed; a personal
   health question is steered to a professional), still never issues an
   eat/don't-eat verdict, and still gives no restaurant risk number without a tool
   match. General facts and restaurant risk scores are kept visibly separate.

## Why

- **The narrow scope refused a reasonable, low-risk question.** "How common is
  food poisoning?" is squarely on-topic for a food-safety assistant and is well
  served by public health data. Declining it was a worse experience than
  answering it with a citation.

- **Curated + cited keeps it trustworthy.** The risk that a model answers a
  health question with a confident-but-wrong statistic is real. Grounding each
  fact in a vetted source and showing the link lets the user verify it, and the
  allow-list means a citation can never point to a weak or made-up domain. This
  mirrors the project's existing anti-fabrication discipline (decision record
  [0005](0005-ethics-bias-and-responsible-ai.md)): no claim without a source.

- **News sources were considered and excluded.** They are not authoritative for
  epidemiology/statistics, their links rot and paywall (which breaks a "verifiable
  link" guarantee and the live link-resolution check), and they are editorial
  rather than primary-source. Local public-health agencies + the Chicago Data
  Portal cover the local angle without those problems.

## Alternatives considered

- **Open web search with citations** — rejected. Broader coverage, but it would
  let the agent cite arbitrary or dead pages, which is exactly what the allow-list
  prevents. The curated list trades coverage for verifiability, which is the right
  trade for health information.
- **Remove the medical-advice boundary entirely** — rejected. General education
  is in scope, but a personalised "what should *I* eat / is it safe for *me*"
  ruling is medical advice and stays out; the agent gives the general facts and
  points the user to a professional.
- **Prompt-only change, leave the Bedrock guardrail as-is** — rejected. The
  guardrail's denied topics would still block general food-safety questions at the
  platform layer, so the feature would not actually work in the deployed agent.
  The guardrail's `OffTopicNonFoodSafety` / `PersonalisedMedicalAdvice` topics
  were re-scoped to match. *(Stale — the `OffTopicNonFoodSafety` topic was removed
  the same day; see the Update note at the top.)*

## Consequences

- **New tool `food_safety_info`** (`agents/tools/food_safety_info/`) wired into
  both runners (`run_local.py`, `entrypoint.py`). Its curated registry of facts +
  allow-listed source links is the source of truth for general answers.
- **System prompt** (`agents/system_prompt.txt`) gains a job-B description, a
  general-questions section (cite the returned source; statistics only from the
  tool), and a re-scoped SCOPE / no-advice section (general education allowed;
  personal medical questions steered to a professional).
- **Bedrock guardrail** (`agents/create_guardrail.py`) deny topics re-scoped so
  general food-safety education is not blocked, only genuinely off-topic requests
  and *personalised* medical/legal advice. **Re-provision** the guardrail (re-run
  the script, publish a new version, update the env vars) for the deployed agent.
  *(Superseded — the off-topic topic was dropped the same day (over-blocking); the
  live guardrail denies only personalised medical + legal advice, and off-topic is
  handled by the system prompt. See the Update note at the top.)*
- **Eval** (`agents/eval/run_eval.py`) gains a deterministic citation **allow-list
  gate**, an opt-in **live link-resolution** check (`--links`), and two guardrail
  cases (a general stat must be answered with a cited source; a personal medical
  question must be steered to a professional).
- **Scope.** This widens the agent beyond the original "Chicago restaurants only"
  framing in `CLAUDE.md`. Pending Jun's sign-off as scope guard; the batch-score
  and no-request-time-inference rules are untouched.

## Cross-references

- [0005](0005-ethics-bias-and-responsible-ai.md) — risk signal, not a verdict; no
  fabrication (the discipline this extends to general facts).
- [0010](0010-agent-no-request-time-scoring-and-no-record.md) — the agent's
  scoring behaviour, unchanged here.
- `agents/README.md` — the tool contract for `food_safety_info` and the safety
  layers.
- `docs/agent-experiments.md` — eval runs covering the new cases.

## Update (2026-07-04) — narrow the medical topic so caregiver queries pass

Live chat over-blocked a core use case: "Best options for someone with a
compromised immune system near Harlem" was denied by the `PersonalisedMedicalAdvice`
guardrail topic, whose definition included "whether a food is safe given their
health condition." That's the exact caregiver/immunocompromised food-safety
recommendation the app is built to answer (the "For caregivers" page + the
system-prompt CAREGIVER section). Narrowed the topic to deny only a **personal
medical ruling for the speaker** (diagnosis, treatment, medication, "is it safe
for ME given my condition") and to explicitly allow **ranking restaurants by
food-safety risk** — including for a vulnerable diner. The deny examples are
unchanged, so "safe for ME with my weak immune system" / "what medicine should I
take" stay blocked. Also fixed a self-inflicted **output** block: the system
prompt told the model to append "consult your care team's guidance," which the
output guardrail then treated as personalised medical advice and blocked —
truncating otherwise-good answers; that instruction was removed.

**Deploy:** the guardrail is not reprovisioned on merge — Deepak must re-run
`agents/create_guardrail.py` (publishes a new version; also picks up the already-
updated Chicago+NYC+LA block message) and re-wire the version. The system-prompt
change deploys with the agent on merge.
