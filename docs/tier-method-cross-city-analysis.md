# Risk-tier method: cross-city analysis + a unified rule

**Decision-support for [decision record 0017](decisions/0017-seasonality-asof-scoring-and-low-tier-widening.md). Not a decision record itself.**
Owner: Bella (eval / serve). Needs Jun (PM) sign-off — tiers are product-facing.

## The problem

The three cities set risk-tier cutoffs by two different methods:

- **Chicago** — fixed cutoffs, chosen from realized fail-rate (decision record 0008).
- **NYC / LA** — per-city **quantiles** (`p40 / p85 / p98`) of that city's own score
  distribution, computed at build time in `build_nyc_scores.py` / `build_la_scores.py`.

Quantiles were the expedient way to avoid reusing Chicago's absolute numbers on a
city whose scores mean something different. But they have two costs — the same two
decision record 0008 rejected for Chicago: the tier loses absolute meaning, and
cutoffs drift every rescore (a venue can change tier because *others* moved).

Measured on each city's held-out test set, here is what each **current** tier
actually delivers (realized fail-rate · multiple of that city's base rate):

| Tier | Chicago (fixed) | NYC (quantile) | LA (quantile) |
|---|---|---|---|
| Low | 2.6% · 0.24× | **22.8% · 0.56×** | 2.8% · 0.32× |
| Moderate | 8.0% · 0.74× | 37.6% · 0.92× | 10.1% · 1.17× |
| Elevated | 18.9% · 1.75× | 57.3% · 1.40× | 16.3% · 1.88× |
| High | 40.8% · 3.78× | 64.0% · 1.56× | 19.1% · 2.20× |
| *base rate* | *10.8%* | *41.0%* | *8.7%* |

Two things stand out:
1. **"Low" is not comparable.** Chicago/LA "Low" ≈ 2.7% realized risk; **NYC "Low"
   realizes 22.8%** — a user is told "safe" about a nearly-1-in-4 venue.
2. **NYC's tiers barely separate.** Low → High spans only 0.56× → 1.56× base (2.8×),
   versus Chicago's 0.24× → 3.78× (16×). This is a model/label limitation — NYC
   predicts a near-even (41% base), weakly-separable outcome — not a tiering bug.

## Two ways to unify — meaning vs share

You can hold one property constant across cities, not both, because the cities
genuinely differ:

- **`×base` rule** (Low<0.5×, Mod<1×, Elev<2×, High≥2×) fixes what a tier *means*
  (High = ≥2× base everywhere). But **share** then swings — serving-population High
  share goes Chicago 1.8% / NYC 0.3% / **LA 8.8%**. LA's map fills with red; "High"
  stops reading as urgent.
- **Quantile rule** (top 2% = High everywhere) fixes the *share*. But **meaning**
  diverges (NYC "Low" realizes 23%) and cutoffs drift every rescore.

The current mess is Chicago on meaning, NYC/LA on share. Neither pure option is
right: the diner needs "Low" to mean the same thing (→ meaning), the inspector needs
"High" to be a small list (→ share).

## Chosen rule (hybrid) — meaning-based Low, capped High

> **Low `< 0.5× base`, Moderate `0.5–1× base`, Elevated `1× base – High_cut`,
> High `≥ High_cut` where `High_cut = max(2× base, city p98)`.**

Low/Moderate/Elevated are fixed multiples of base (so "Low" means the same low risk
everywhere, stable across rescores); High is the rarer of "≥2× base" or "top 2%", so
it stays a small, genuinely-elevated triage slice in every city. The `max(2× base,
p98)` cap is what stops a low-base city (LA) from dumping every above-average venue
into High. Per-city, on the served population:

| City | base | Low `<0.5×` | Moderate `0.5–1×` | Elevated `1×–cut` | High `≥ High_cut` | High share |
|---|---|---|---|---|---|---|
| Chicago | 0.108 | `<0.054` | `0.054–0.108` | `0.108–0.216` | `≥0.216` | 1.8% |
| NYC | 0.41 | `<0.205` | `0.205–0.41` | `0.41–0.82` | `≥0.82` | 0.3% |
| LA | 0.087 | `<0.0435` | `0.0435–0.087` | `0.087–0.306` | `≥0.306` | 2.0% |

High is small everywhere now (0.3–2.0%). The honest residual moves to **Elevated**
(NYC 24%, LA 36%) — those cities genuinely have more above-baseline venues, but
"Elevated" is a softer, non-alarmist word than "High".

Why the `p98` cap and not a pure `2× base` High: pure `2× base` gives LA **8.8%**
High (see above). Why `0.5/1×` for the lower bands and not quantiles: quantiles make
NYC "Low" mean 23% realized risk.

### What it changes

- **Chicago**: `0.06 / 0.13 / 0.30` → `0.054 / 0.108 / 0.216`. Low barely moves
  (still fixes Emporium); High widens 0.30 → 0.216 (0.9% → 1.8% of venues). This
  **subsumes** the `0.04 → 0.06` Low widening — the cutoff now comes from the rule.
- **NYC / LA**: drop the quantile block; tier via the shared helper.
- **NYC copy**: "Low" still realizes ~19%; UI should say "lower risk *for NYC*", not
  "safe". App-workstream follow-up, not a producer change.

### Implementation

A single shared helper — `assign_risk_tiers(scores, base_rate)` in
`predict_batch.py` — called by Chicago's `build_scores_table` and both city
producers, so the method lives in one place. The thresholds a run used are written
into `scores.json` (`risk_tier_thresholds`), and `methodology.json` reads them, so
the how-it-works bands can't drift from what shipped.

## Recommendation (adopted)

Adopt the hybrid rule for all three cities; retire the NYC/LA quantile blocks and
Chicago's hand-tuned cutoffs. It gives "Low" one meaning everywhere, keeps "High" a
small triage slice, and stays stable across rescores. Recorded in decision record
0017. **Merge needs Jun** — this shifts production tiers for all three cities.
