# Prototype / RFC — merge the risk gauge and the trend chart into one chart

**Status: prototype for discussion. Do not merge.** The `/proto` route and
`MergedRiskChart` here are throwaway; if we adopt the idea, the real work
replaces the ScoreCard layout and these files are deleted.

## The idea

Today the detail-page ScoreCard shows two things side by side:

- an **arc gauge** = Model 1 `risk_score` (the production number), and
- a separate **trend chart** = Model 2 forecast-only score over past inspections.

Both models output the same thing — probability of a fail-or-priority in the
next 180 days — so they share one 0–1 scale. This prototype folds them into a
single **risk-trajectory chart**:

- horizontal **tier bands** (Low / Moderate / Elevated / High, per decision 0008)
  as a **neutral grey ramp** (higher tier = slightly darker), with tier labels —
  colour is deliberately kept off the bands so the chart never reads as alarm
  (decision 0011);
- the neutral **Model 2 line** is the trajectory over past inspections
  (ignores each visit's own pass/fail, per decision 0011);
- the **Model 1 `risk_score`** is a tier-coloured value tag pinned to the right
  axis at its risk level (with a faint horizontal "current level" guide) — the
  headline number, shown in context, no leader line. The tag (plus the
  current-tier label) is the **only** colour on the chart.

No forward/extrapolated line: decision 0011 found the loose direction does not
predict, so we don't draw a future line.

### What it fixes

Today the gauge (e.g. `0.23`) and the trend chart's last dot are two *different*
numbers for "now" (Model 1 vs Model 2) sitting next to each other with nothing
explaining the gap. The merge makes that relationship explicit — the small gap
between the last line dot and the current-value tag is "today's inspection nudged
the assessment off the underlying trend."

## Screenshots (real 0.5.0 data)

Each shows the **current** ScoreCard above the **merged** prototype.

- `01-worsening-26pts.png` — dense history (stress-tests labels + axis)
- `02-improving.png`, `03-stable.png`
- `04-high-risk.png` — the concept at its best (clear climb into High)
- `05-few-points-edge.png` — 3-point edge case
- `06-mobile.png` — 390px, no horizontal overflow

## Two decisions needed before this could ship (Aurelia / Jun)

1. **The direction badge.** A big, tier-coloured chart makes any disagreement
   between the slope-based badge and the eye obvious — see `04-high-risk.png`,
   where the badge reads **"Stable"** (slope just under the 0.0003 band) next to
   a line that clearly climbs into High. Today's tiny neutral chart hides this;
   decision 0011 chose small + neutral partly for that reason. Options:
   (a) drop the Improving/Worsening/Stable badge and let the trajectory speak;
   (b) show the badge only for the strict steeply-rising watch-list (the slice
   0011 says actually predicts);
   (c) keep it but retune so it can't contradict a visibly-climbing line.
   This touches the 0011 framing, so it's a product decision, not a polish one.

2. **The y-axis.** A linear 0–1 axis squashes every sub-Elevated place into the
   bottom; the prototype auto-scales to the recent window + a robust p90 so one
   old spike can't dominate. Confirm auto-scale (and that older outliers may
   clamp at the top) is acceptable, or pick a fixed cap.

## How to view

```bash
cd app && npm ci && npx next dev -p <port>
# open http://localhost:<port>/proto/
```
