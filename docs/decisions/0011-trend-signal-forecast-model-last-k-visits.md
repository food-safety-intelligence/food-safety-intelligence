# 0011 — Trend signal: forecast-only model + last-K-visits slope

- **Status**: **Accepted** — landed (contract change acked by all owners)
- **Date**: 2026-06-28 (accepted 2026-07-04)
- **Owners to ack**: Bella (modeling / eval), Deepak (modeling backup), Aurelia
  + Jun (web app), Arun (DE) — the `scores.json` schema is the cross-team contract.
- **Implementation status**:
  - Pipeline / `predict_batch` scalar `trend_slope` + Model 2 — done (#61).
  - Web app consumers + `trendDirection` retune + `TrendChart` — done (#62).
  - Published S3 `scores.json` regenerated on schema 0.5.0 (`trend_slope`) — done (2026-06-29).
  - Agent tool handlers (`get_safety_score`, `explain_restaurant`) — the rename
    half-landed: the handlers kept reading `trend_slope_90d` and reported every
    deployed answer's trend as "stable" from 2026-06-29 until this fix. Renamed
    to `trend_slope`, `_trend_label(None)` now says "not enough inspection
    history", committed fallback regenerated on 0.5.0, and a trend assertion
    added to the eval faithfulness gate so this class of drift fails CI.

> The web app already shows a per-establishment trend (Improving / Worsening /
> Stable + a small chart), driven by the `trend_slope_90d` field. That field is
> broken; this record replaces how it is computed and how it is presented. The
> production `risk_score` is **not** touched.

## Terms

- **Trend** — the *direction* of an establishment's predicted risk across its
  recent inspections: drifting riskier, safer, or holding steady. It is a
  descriptive read of the trajectory, **not** a separate prediction and **not** a
  verdict (see decision 5).
- **`trend_slope`** — the single number that encodes the trend: the OLS slope of a
  model's score across the establishment's recent inspections, in score-per-day.
  **Positive = risk rising (worsening); negative = risk falling (improving);
  ≈0 = stable.** `null` when there are fewer than 2 inspections to fit a line. The
  UI maps its sign to the Improving / Worsening / Stable label and the chart.
- **Model 1 (production)** — the shipped risk model behind `risk_score`; uses all
  features, including the current inspection's own outcome. Unchanged here.
- **Model 2 (forecast-only)** — a second model that predicts the *same* 180-day
  label but drops the current inspection's own outcome, so its score does not see
  today's verdict. Used **only** as the basis for `trend_slope`.
- **Anchor** — the single inspection a license is summarised at: its most recent
  inspection (the row that becomes its `scores.json` record).
- **Coverage** — the share of establishments that get a non-null `trend_slope`
  (full definition under Evidence).

## Context — the shipped trend is broken

`trend_slope_90d` (`foodsafety.serve.predict_batch._compute_trend_slopes`) is an
OLS slope of the **production model's** `risk_score` over the **90 days** before a
license's latest inspection. It fails two ways, both user-facing today:

- **Coverage ~30%.** It needs ≥2 inspections inside a 90-day window, so it is null
  for ~70% of licenses; the UI then shows "Insufficient history" / "Stable". Most
  "Stable" really means "unknown".
- **Re-inspection bounce.** A Fail triggers a mandated ~30-day re-inspection that
  usually passes. The production score (which sees the current outcome) swings
  high→low across that pair, so the slope reads "Improving" mechanically — an
  artifact of the inspection schedule, not the kitchen improving.

## Decision

1. **Two models, one job each.** Keep the production model (**Model 1**, all
   features) as the shipped `risk_score` — unchanged. Add a **forecast-only model
   (Model 2)** that predicts the *same* label (P(fail-or-priority in next 180 days))
   but **drops the 3 current-outcome features** (`was_fail`,
   `n_priority_this_inspection`, `n_core_this_inspection`). Model 2 is used **only**
   to build the trend trajectory; it never sets `risk_score`.

2. **Trend = last-K-visits slope of Model 2.** Replace the 90-day production-score
   slope with an OLS slope of Model 2's score over each license's **last K = 5
   inspections** (≥2 points required). Window→visits fixes coverage; Model 2 makes
   the trend forward-looking — it ignores each visit's own pass/fail, so the
   re-inspection bounce no longer drives the slope.

3. **Rename the field: `trend_slope_90d` → `trend_slope`.** The old name now lies
   (neither 90 days nor the production model). Use a neutral name so it can't go
   stale if K is retuned; the precise definition (forecast model, last-K, K=5)
   lives in [`interface_contracts.md`](../interface_contracts.md) and here.

4. **Real detail-page chart (sequenced as a follow-up).** Ship per-inspection
   Model-2 scores on the detail-page history data (`inspection_history.json` —
   dates already shipped; add a `score` per event), and rewrite `TrendChart` to
   plot the **real last-K (date, score) points** instead of today's synthetic
   straight line. This crosses the `retrain`↔`export_inspection_history` script
   boundary (a new per-inspection forecast-score artifact) and only affects the
   detail-page chart, so it ships **after** the scalar replacement, not bundled
   with it (see Delivery). Until then, the existing synthetic chart is simply fed
   the better `trend_slope`. `trendDirection`'s ±0.001 thresholds are retuned for
   Model 2's score scale as part of the scalar replacement.

5. **Framing — descriptive trend + additive watch-list, never a verdict.** The
   trend is a *descriptive* "how has this drifted" signal plus an additive
   early-warning watch-list. It is **not** a forward-risk verdict. This is
   load-bearing and ties to [0005](0005-ethics-bias-and-responsible-ai.md)
   principle 1: the UI must not imply "Worsening = dangerous" (see Evidence — the
   loose signal does not predict).

## Evidence

Reconstruction of the 2026-06-22 prototype on real data + a K sweep (full run:
[`experiments.md`](../experiments.md) 2026-06-28 row;
`reports/metrics/experiments/trend_deconfound_experiment_2026-06-28.json`). Anchors = each
license's latest non-right-truncated test inspection (n=5,226, base 4.4%, 97.5%
currently-clean); XGBoost for both models.

- **Coverage 0.29 → 0.87.** *Coverage* = the share of establishments that get a
  non-null `trend_slope` — i.e. that have ≥2 inspections to fit a line through
  (the rest show "no trend / insufficient history" in the UI). The old 90-day
  window needed 2 inspections *within 90 days*; last-K-visits needs only 2 of the
  last K, so almost any place with a repeat inspection qualifies. K-independent.
  (On the full production population, including single-inspection licenses that
  can never have a slope, coverage is ~0.73; on test anchors it is 0.87.)
- **Forward-looking, partially:** corr(slope, `last_was_fail`) −0.31 → −0.19. The
  residual is *legitimate* prior-history signal (Model 2 still uses `prior_*`), not
  the re-inspection bounce — the forecast-only model reduces that bounce, it does
  not zero it out.
- **Early-warning lift (clean slice, base 4.4%):** a **strict** steeply-rising
  slope (top decile) selects a slice with **2.26× @K=5** forward fail-rate (2.1–2.3×
  for K∈{3,4,5}, decaying to 1.74× at K=8). A **loose** `slope>0` signal is
  **~1.16× — uninformative.** Reproduces + exceeds the prototype's 1.46×.

**The split that drives the framing:** the strict watch-list predicts (2.26×); the
loose Improving/Worsening/Stable label does not (1.16×). So we ship the trend for
**coverage + honesty** (a real, forward-looking trajectory) and the strict slice as
an **additive watch-list**, but we do not present the loose direction as a
prediction.

## Consequences

- **Serving:** `predict_batch` runs two models — Model 1 for `risk_score`, Model 2
  scored across full history for the trend. Model 2 becomes a saved artifact
  (`data/models/forecast_*.joblib`) trained alongside the production model.
- **Contract (`scores.json` / `scores.parquet`):** `trend_slope_90d` → `trend_slope`
  (rename + new meaning); `inspection_history.json` events gain a per-event `score`.
  Both are owner-tagged schema changes → this record's all-owner ack.
- **Web app:** rename consumers, retune `trendDirection`, rewrite `TrendChart`,
  plumb history scores into `ScoreCard`, update `how-it-works` copy. Requires a
  `/verify` pass (visual change).
- **Delivery:** stacked on the S3 PR (#40) so the regenerate/publish path is
  available.
  - **PR-A** (Python) — this record + experiment + Model 2 + `predict_batch`
    scalar `trend_slope` (rename + last-K forecast) + contract doc + mock.
  - **PR-B** (frontend) — rename consumers + `trendDirection` retune. The
    existing synthetic `TrendChart` is kept, now fed the better slope.
  - **PR-C** (follow-up) — the real per-inspection chart: a forecast-score
    artifact from `retrain`, joined in `export_inspection_history`, and the
    `TrendChart` rewrite to plot real `(date, score)` points.

## Alternatives considered

- **Keep computing `trend_slope_90d` as-is** — rejected; it is broken and live.
- **Keep the name, change the meaning** — rejected; silent semantic drift for every
  consumer.
- **Bake K into the name (`trend_slope_last5`)** — rejected; K is tunable, the name
  would go stale on a retune.
- **Use Model 1's score over last-K (skip Model 2)** — rejected; widening the window
  without the forward-looking model surfaces *more* re-inspection artifacts (worse).
- **Replace `risk_score` with the forecast model** — out of scope and contrary to the
  2026-06-22 product-pivot finding (segment the existing model, don't ship a
  separate forecast score). Model 2 is trend-only.
- **Drop the trend entirely, ship only the strict watch-list** — considered; the
  descriptive trend still has coverage + honesty value, so we keep both.

## Residual risks

- **Re-inspection bounce only partly removed** (−0.19 residual). Monitored; treated
  as legitimate prior-history signal, not removed.
- **The descriptive trend is a weak predictor.** Managed by framing (decision 5),
  not by overclaiming in the UI.
- **K = 5 is a tuned default**, not a truth; revisit if the inspection cadence
  distribution shifts.
- **A second model to maintain.** Model 2 must be retrained whenever the production
  feature set or estimator changes (e.g. after [0009](0009-production-estimator-revisit-logreg-vs-xgb.md)).
