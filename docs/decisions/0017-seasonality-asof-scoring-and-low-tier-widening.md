# 0017 — As-of-common-month scoring + a unified cross-city risk-tier rule

- **Status**: Accepted (pending Jun sign-off on the tier rule — it reshapes
  production tiers for all three cities)
- **Date**: 2026-07-05
- **Owners to ack**: Bella (eval / serve), Jun (PM), Aurelia + Jun (web app — tier
  bands / legend / NYC copy)
- **Supersedes**: the Chicago tier cutoffs in
  [0008](0008-risk-tier-thresholds.md) and the NYC/LA per-city **quantile** tier
  blocks (both replaced by the unified rule in § B).

> Two things prompted this: a reviewer flagged that Emporium Logan Square (a
> barcade, no kitchen) showed **Moderate** driven only by `temporal_month` — a
> calendar factor; and investigating the tiers revealed the three cities set them
> by two different methods that make "Low" mean wildly different things
> (Chicago/LA "Low" ≈ 2.7% realized risk, **NYC "Low" ≈ 23%**).

## A. As-of-common-month scoring (Chicago)

**Problem.** The served score is a calibrated `P(fail-or-priority within 180d)`.
We anchor each venue at its most recent inspection and freeze *every* feature —
including the seasonal `temporal_month` / `temporal_quarter` — at that inspection's
month, then present it as timeless risk. So identical venues differ purely by
inspection timing, and a stale season lingers: Emporium's last inspection was
2023-12-26, so its score carried a December seasonal bump (real-month score
**0.0422**, with `temporal_month = +0.366` the dominant upward driver) long after
December. Seasonality is a *real* population effect, though — dropping the feature
**fails the both-metrics promotion gate** ([0002](0002-xgb-validation-methodology.md);
served test PR-AUC −0.0011, precision@10% −0.0086, ablated ≥ full in 0/3 folds).

**Decision.** At **scoring time only**, override `temporal_month` /
`temporal_quarter` for every venue to the **current calendar month**
(`override_scoring_month()` in `temporal_features.py`, applied to the Model-1 and
Model-2 scoring frames in `retrain_xgb_sigmoid.py`). Train/val/test run on real
months, so offline metrics are unchanged (test PR-AUC 0.382, precision@10% 0.415).
Only those two columns feed the model (`temporal_season` / `temporal_year` /
`temporal_dow` are excluded). Current month — not a fixed neutral month — so the
snapshot reflects the real season; it **breathes** (a July rescore anchors on
summer, December on winter), and the recorded `scoring_month` in the metrics report
tells anyone comparing rescores why a shift happened. Chicago-only (NYC/LA carry no
calendar features).

## B. Unified cross-city risk-tier rule

**Problem.** Chicago set tiers by fixed cutoffs from realized fail-rate (0008);
NYC/LA set them by per-city **quantiles** (p40/p85/p98). Measured on each city's
held-out test set, the current tiers deliver very different risk:

| Tier | Chicago (fixed) | NYC (quantile) | LA (quantile) |
|---|---|---|---|
| Low | 2.6% · 0.24× | **22.8% · 0.56×** | 2.8% · 0.32× |
| High | 40.8% · 3.78× | 64.0% · 1.56× | 19.1% · 2.20× |
| *base rate* | *10.8%* | *41.0%* | *8.7%* |

A user reading "Low" on the NYC map is told "safe" about a nearly-1-in-4 venue, and
quantile cutoffs drift every rescore (a venue's tier moves when *others* move).

**Decision.** One rule for all three cities. The score is a calibrated probability,
so cutoffs are anchored to each city's **own base rate** (label prevalence):

| Tier | Cutoff | Meaning |
|---|---|---|
| Low | `score < 0.5× base` | clearly below baseline — genuinely low risk |
| Moderate | `0.5× – 1× base` | around the city's own baseline |
| Elevated | `1× base – High_cut` | above baseline |
| High | `score ≥ High_cut` | `High_cut = max(2× base, city p98)` |

Low/Moderate/Elevated boundaries are **fixed** (stable across rescores; "Low" means
the same low risk in every city). **High is the rarer of "≥2× base" or "top 2%"** —
so it stays a small, genuinely-elevated triage slice in every city. Implemented as
`assign_risk_tiers(scores, base_rate)` in `predict_batch.py`; Chicago's
`build_scores_table` and both city producers call it. Per-city numbers:

| City | base | Low | Moderate | Elevated | High | High share |
|---|---|---|---|---|---|---|
| Chicago | 0.108 | `<0.054` | `0.054–0.108` | `0.108–0.216` | `≥0.216` | 1.8% |
| NYC | 0.41 | `<0.205` | `0.205–0.41` | `0.41–0.82` | `≥0.82` | 0.3% |
| LA | 0.087 | `<0.0435` | `0.0435–0.087` | `0.087–0.306` | `≥0.306` | 2.0% |

### Why this rule (stakeholder view)

- **Diner** — needs "Low" to mean *actually safe* the same way in every city, and a
  map that isn't a sea of red. → meaning-based Low + small High.
- **Restaurant owner** — needs fairness/stability: not bumped to a worse tier because
  *neighbours* improved. → fixed cutoffs, not quantiles.
- **Inspector** — capacity-limited triage: a small, high-precision "High" list. →
  the p98 cap.

### Alternatives considered

- **Pure `×base` (Low<0.5×, Mod<1×, Elev<2×, High≥2×).** Rejected: "High" then means
  the same risk everywhere but its *share* swings from 0.3% (NYC) to **8.8%** (LA) —
  LA's map fills with red and "High" stops reading as urgent. The `max(2× base, p98)`
  cap fixes this while keeping High genuinely elevated.
- **Pure quantiles for all three** (make Chicago quantile too). Rejected: consistent
  *share* but "Low" keeps meaning different risk per city (NYC Low = 23%), and it
  reintroduces the reship-instability 0008 rejected.
- **Leave Chicago on 0.06/0.13/0.30 and only unify NYC/LA.** Rejected: leaves Chicago
  the odd one out; not a unified method.

## Effect

- **Emporium** — real-month 0.0422 → **frozen-July 0.0279**, and `temporal_month`
  drops out of the top drivers (replaced by `prior_fails_365d`, inspection type,
  `days_since_last_fail`). Low under the unified rule (0.0279 < 0.054). Both changes
  fix it independently.
- **Tier shares move** (see table). Chicago Low 48% → 64%; High 0.9% → 1.8%. NYC/LA
  Low drops (their quantile "Low" was the bottom 40% regardless of risk).
- **NYC honesty** — NYC "Low" still realizes ~19% (0.47× of a 41% base); the model
  can't separate better on a near-even outcome. The **UI copy should say "lower risk
  *for NYC*", not "safe"** — flagged for the app workstream; not a producer change.

## Consequences

- **Supersedes** 0008's Chicago cutoffs and the NYC/LA quantile blocks; all three
  now tier via `assign_risk_tiers`. 0008 + `interface_contracts.md` § 3 updated.
- **`scores.json` gains a top-level `risk_tier_thresholds`** (the cutoffs a run used)
  so `methodology.json` reports the real bands without recomputing. Additive field,
  no consumer break; the tier *vocabulary* is unchanged.
- **Base rates are fixed reference constants** (`CHICAGO_BASE_RATE = 0.108`;
  `NYC_BASE_RATE = 0.41`; `LA_BASE_RATE = 0.087`) so Low/Moderate/Elevated cutoffs
  don't drift; each producer prints the run's measured test base to spot large drift.
- Full cross-city analysis + measured numbers:
  [`tier-method-cross-city-analysis.md`](../tier-method-cross-city-analysis.md).

## Cross-references

- [0008](0008-risk-tier-thresholds.md) — the tier framework this supersedes.
- [0002](0002-xgb-validation-methodology.md) — the both-metrics gate dropping
  seasonality fails.
- [`interface_contracts.md`](../interface_contracts.md) § 3 — tier table (updated).
