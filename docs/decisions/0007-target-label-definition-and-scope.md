# 0007 — Target label: definition and scope

- **Status**: Accepted
- **Date**: 2026-06-21
- **Owners to ack**: Aurelia + Arun (label / data owners), Bella (modeling), Jun (PM)

> The target label is the most foundational modeling choice — it defines what the
> whole product predicts. Until now it lived only in `CLAUDE.md`,
> `src/foodsafety/data/labels.py`, and `docs/interface_contracts.md`. This record
> consolidates the label's definition and the decisions behind it, including the
> fail-or-priority vs fail-only scope choice (the part that was actively debated).
>
> **Recorded retroactively.** Most of this (target, window, cutoff) is a
> foundational decision made at project start; only the fail-or-priority vs
> fail-only scope was re-litigated on 2026-06-21. The record number reflects when
> it was logged, not its priority — read it as one of the first decisions.

## The label

`y_fail_or_critical_next_180d` — for an anchor inspection at `as_of_date`, **1 if
the same establishment (`license_id`) has a Fail result OR a priority violation
(Chicago codes 1–29) within the 180 days strictly after the anchor, else 0.** The
anchor inspection itself is excluded from its own forward window — we predict what
happens *after* the visit. Authoritative construction: `labels.build_labels`;
schema in [`interface_contracts.md`](../interface_contracts.md).

Mechanically, the label is the forward aggregation of a per-inspection event flag
`is_fail_or_priority` (a Fail result, or any code 1–29 parsed from the
pipe-separated `violations` free text — the 1–29 boundary is inclusive) over the
window `(anchor, anchor + 180 d]` at the same license.

It breaks into five decisions.

### 1. Target — forward-window risk, not the current verdict
We predict a *future* event in a fixed forward window, anchored on each
inspection — a forward-looking risk signal (the product's value), not a
restatement of the inspection that just happened. **Prediction unit (MVP):** one
row per `(license_id, inspection_date)` (`as_of_date` is a synonym); for the web
app we score each license's most recent inspection. Per-restaurant-per-day rolling
is the Phase-2 target (per `CLAUDE.md`).

### 2. Window length — 180 days
A six-month horizon: long enough for a workable positive rate (~10–14%) and to be
operationally meaningful ("risk over the next six months", the UI's framing),
short enough that the signal stays actionable and the features observed at
`as_of_date` stay relevant. `config.LABEL_WINDOW_DAYS = 180`. The resulting
~10–14% positive rate is class imbalance — handled on the **model** side
(`class_weight='balanced'` / `scale_pos_weight`, never SMOTE on a time split; see
0002 + `CLAUDE.md`), not by resampling the label.

### 3. Event scope — fail-OR-priority, NOT fail-only  ← the debated decision
The event counts a **Fail result OR a priority violation (codes 1–29)**, not Fails
alone. Codes **1–29 are Chicago's Priority / Priority-Foundation tier** (FDA
risk-based categorization, adopted in the July-2018 form change) — the violations
most directly tied to foodborne illness (temperature control, contamination,
employee hygiene). Codes 30+ are Core (general sanitation). "Serious" is the
city's classification, not ours.

A 2026-06-21 experiment asked whether a **fail-only** label is a better target,
since the priority arm is the noisier half and a crisper label is more learnable.
Expanding-window CV (6 folds, leak-free, RT-filtered, 180-day embargo) confirmed
fail-only IS more learnable on a lift-over-base-rate basis (raw PR-AUC isn't
comparable across the two prevalences):

| label | prevalence | mean PR-lift | mean P@10-lift | fail-only wins |
|---|---|---|---|---|
| fail-or-priority (current) | 13.6% | 3.22 | 3.70 | — |
| fail-only | 6.1% | 3.61 | 3.86 | 6/6 on PR-lift, 4/6 on P@10-lift |

**We keep fail-or-priority anyway — a product decision, not a metrics one:**
- **It matches what we're building** — a consumer food-safety *risk* layer, not an
  inspection-outcome predictor. Dropping priority violations would narrow it to
  "regulatory-failure risk."
- **Internal consistency** — we already treat 1–29 as the serious tier across ~8
  features (`prior_priority_violations`, `n_priority_this_inspection`,
  `priority_violation_trend`, …) and the UI (how-it-works "codes 1–29", the
  `caregivers` page). Fail-only would make the label the one place that ignores it.
- **A "Fail" is partly an administrative artifact** — Fail vs "Pass w/ Conditions"
  turns on inspector discretion + thresholds; serious priority violations routinely
  occur on inspections that technically pass. Fail-only also concentrates the
  target on the mandated ~30-day re-inspection cadence (the re-inspection feedback
  loop — 0005 principle 6), i.e. more bureaucratic timing, less food safety.
- **Coverage for the vulnerable-diner persona** — the `caregivers` page exists for
  people choosing for someone immunocompromised; for them a missed
  serious-but-passing hazard is worse than an over-flag, and fail-or-priority has
  ~2.2× the prevalence → better hazard recall.
- **The metric edge is thin where it counts** — on P@10-lift (the triage metric)
  the gap is 3.86 vs 3.70 and holds in only 4/6 folds. Not a decisive
  product-grade win.

The responsible-AI angle of this scope choice (broad net → over-flagging vs
protection of vulnerable users) is recorded in
[0005](0005-ethics-bias-and-responsible-ai.md) principle 7.

### 4. Training cutoff — 2019+, with pre-2019 burn-in
Raw inspections exist from **2010**; we train only on those from **2019-01-01
onward**. The **July-2018 Chicago inspection-procedure change** redefined how
violations are recorded, so pre/post labels are not comparable. Pre-2019
inspections are kept as **burn-in** (label NA — see §5) solely so `prior_*` history
features are populated at the start of 2019. `config.TRAIN_START_DATE =
"2019-01-01"`; enforced via `is_burnin` in `labels.build_labels`.

### 5. Label universe & row exclusions
- **Eligible results.** Only `Pass`, `Pass w/ Conditions`, `Fail` are modelable
  outcomes; `Out of Business` / `No Entry` / `Not Ready` / `Business Not Located`
  describe a *non-inspection*, not a food-safety result. The labeled table
  deliberately KEEPS them (for auditing); the `MODELABLE_RESULTS` filter is applied
  downstream at feature build (`features/build.py`), **not** in `labels.py`.
- **Label is NA (not 0) when it can't be computed**, for *either* of two reasons:
  burn-in (pre-2019, §4) **OR** a placeholder license token (`""` / `"0"`, which
  pool unrelated establishments so per-license history would be meaningless). NA
  rows are never trained on. (`na_mask = is_burnin | invalid-license` in
  `labels.build_labels`.)
- **Right-truncation.** An anchor whose 180-day window runs past the dataset's
  latest date has an UNDER-COUNTED label (a future Fail we can't see yet records as
  0). Such rows are flagged `right_truncated` and dropped from the honest
  train/eval basis (and the served eval) so metrics aren't biased at the snapshot
  edge.

## Alternatives considered (scope)
- **Fail-only** — measured more learnable (above), rejected on product grounds. CV
  evidence retained in [`experiments.md`](../experiments.md) so the choice is on
  record as deliberate. Revisit if we add a distinct **inspector-triage** surface
  (where a sharper fail-only ranking could fit that persona) or the city retiers
  violations.
- **Priority-only** — noisiest of the three (prototype top-decile lift 3.2×); not
  pursued.

## Consequences
- The current label, served scores, and operating-point framing all stand; no
  model migration.
- Any future change to scope, window, or cutoff is a **contract change** → schema /
  owner sign-off per [`interface_contracts.md`](../interface_contracts.md).

## Cross-references
- [`experiments.md`](../experiments.md) — the fail-only prototype + CV rows.
- [0005](0005-ethics-bias-and-responsible-ai.md) principle 7 — ethics of label scope.
- [0002](0002-xgb-validation-methodology.md) — the both-metrics evaluation gate the
  scope experiment was judged on.
