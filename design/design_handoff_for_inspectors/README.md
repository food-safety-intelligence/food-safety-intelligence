# Handoff: "For Inspectors" page

## Overview
A new top-nav destination for the Food Safety app: a model-ranked inspection worklist for restaurant inspectors. It reframes the existing risk scores as a **priority queue** — "inspect from the top of this list and you'll find failures/critical violations ~4× more often than random visits." Adds tier filtering, sorting, expandable rows (SHAP drivers + inspection history), a model-lift explainer card, a "Rising fast" watch list, and a lightweight "Today's route" builder.

## About the Design Files
`For Inspectors.dc.html` is a **design reference created in HTML** — a prototype showing intended look and behavior, NOT production code. The task is to recreate it in the existing codebase: **Next.js (App Router) + Tailwind 4 + the Clinical Quiet theme**, reusing the app's established components wherever noted below.

## Fidelity
**High-fidelity.** All colors, type, radii and shadows are taken from `app/src/app/globals.css` tokens. Recreate pixel-perfectly, but always prefer the existing Tailwind tokens/classes and shared components over hard-coded values.

## Where it plugs into the existing codebase

- **Route:** `app/src/app/inspectors/page.tsx`
- **Nav:** add `{ id: "inspectors", label: "For inspectors", href: "/inspectors" }` to `NAV` in `components/SiteHeader.tsx` (and to the `NavItem` type). Position: after "Chat", before "For caregivers".
- **Data:** the page is entirely derivable from the existing `SearchIndex` (`/data/search-index.json`) + per-license `DetailBundle`s. No new pipeline output is required for v1. For expanded rows, lazy-fetch `/data/detail/<license_id>.json` on first expand.
- **Reuse, don't rebuild:**
  - `TierPill` — tier badges on rows and filter chips (filter chips are TierPill + `withCount` + toggle behavior)
  - `TrendIndicator` — the trend column (full variant)
  - `iconForFeature` (`lib/driver-icons.ts`) — driver chips/rows (the prototype uses a generic arrow; production should use the topic icon like `ScoreCard`'s top-factor chip)
  - `toPinDriver` / `trendDirection` / `compareByName` from `lib/scores.ts`
  - Driver bars in expanded rows: reuse `driverBarGeometry` / `DriverList` styling conventions (terra = raises, sage = lowers)
- **Top-driver chip sign convention:** identical to `ScoreCard.tsx` — `shap > 0` → `bg-terra/10 text-terra-strong` + ArrowUp; else `bg-sage/15 text-sage-strong` + ArrowDown.

## Screens / Views

### 1. Page header block
- Eyebrow: `text-2xs tracking-widest uppercase text-muted` — "INSPECTOR WORKLIST · AS OF {as_of_date}"
- H1: Instrument Serif (`.serif`), 44px/1.08 — "Inspect where it matters most."
- Lede: 15px/1.6 `text-muted`, max-width 640px. Bold ink on "failed inspection or critical violation"; the "4× more" is serif italic terra at 1.2em.
- Right: three stat cards (white, `border-line`, `rounded-3xl`, `.soft-shadow`, padding 16×22): value in `.num` 26px/600 (terra / coral / ink), label 11px muted. Values come from `totals` in scores payload: High-tier count, worsening count, establishments.

### 2. Controls row
- Left "TIER" label (11px uppercase muted) + 4 toggle chips (High/Elevated/Moderate/Low). Active chip = tier tint bg/fg tokens (`bg-tier-*-bg text-tier-*-fg`), inactive = transparent bg, `border-line`, muted text. Each shows tier count in `.num` 11px at 75% opacity.
- Right "SORT" + 3 radio chips: "Highest risk" (default), "Most overdue" (days since last inspection desc), "Worsening fastest" (trend_slope desc). Active = `bg-ink text-cream`; inactive = bordered transparent.

### 3. Priority queue (main column, grid `1fr 340px`, gap 24px)
Card: white, `rounded-3xl`, `border-line`, `.soft-shadow-lg`, header row "Priority queue" (15px/700) + "{n} establishments · highest expected yield first" (12px muted).

Row (collapsed), grid `44px 1fr auto`, padding 16×24, hover `#FAF7F0`, divider `#EFE9DD`:
- Rank number `.num` 13px, zero-padded ("01")
- Name 14.5px/700 · TierPill (sm) · optional "Overdue" pill (`bg-highlight #F9EAB0`, `#7A5A24` text, shown when days since last inspection > 300)
- Meta line 12.5px muted: "{address} · {neighborhood} · last inspected {n} days ago"
- Top-driver chip (see sign convention above), 11.5px, max-width 420px, truncate
- Right: "TREND" micro-label + TrendIndicator; "SCORE" micro-label + score `.num` 24px/600 colored by tier hex (`TIER_HEX`); chevron rotates 180° when expanded (0.2s)

Row (expanded) — background `#FAF7F0`, two columns (gap 24, left-padded to align under name):
- **"Why the model flags this"**: per driver — label 12.5px, horizontal magnitude bar (6px track `#F1ECE1`, fill terra/sage, width = |shap|/max|shap|), signed value `.num` 12px in terra-strong/sage-strong
- **"Recent inspection history"**: rows of date (`.num` muted) · result (Fail=terra-strong, Pass=sage-strong, Conditions=`#7A5A24`) · headline truncated
- Buttons: "Open full record" (`bg-ink text-cream` pill → links to `/restaurant?license=<id>`) and "Add to today's route" (bordered pill)

### 4. Sidebar (340px)
- **Model lift card** (ink `#2B3239` bg, cream text, `rounded-3xl`): eyebrow "WHY TRUST THIS RANKING"; "~4×" in Instrument Serif 42px + "better than random"; explainer 12.5px at 75% opacity ending with "…it is not a verdict on any establishment."; two hit-rate bars (model-ranked vs random — **placeholder values ~41%/~10%, replace with real backtest numbers**); "Full methodology →" link to `/how-it-works`.
- **Rising fast**: white card; top 3 by trend_slope (> stable band 0.0003), each row name/neighborhood + delta `+{slope×90}/90d` in terra `.num`. Row hover `#FAF7F0`, links to detail page.
- **Today's route**: client-state list of added rows (numbered, removable ×). Empty state: dashed `border-line` box, 12px muted. v2 idea: group by neighborhood.
- **Honest-use note**: `bg-tint #EDE6D8` card, 11.5px muted — "A ranking, not a judgment. …"

## Interactions & Behavior
- Tier chips toggle independently; queue + count update immediately (client-side, same pattern as `computeHomeView`)
- Sort chips are exclusive radio
- Row click toggles expand (multiple rows may be open); chevron rotates; row bg tints
- "Add to today's route" appends license_id to route state (dedupe); × removes
- Recommend URL-state (`?tier=&sort=`) matching the home page's pattern
- Route state can live in `useState` for v1 (or localStorage to survive reload)

## State Management
```ts
tiers: Set<RiskTier>          // default all
sort: "risk" | "overdue" | "trend"
expanded: Record<license_id, boolean>
route: license_id[]
detailCache: Record<license_id, DetailBundle>   // lazy-fetched on expand
```

## Design Tokens (all existing in globals.css)
- cream `#F6F1E9` · card `#FFFFFF` · ink `#2B3239` · muted `#6B7280` · line `#E6DFD3` · tint `#EDE6D8` · highlight `#F9EAB0`
- Tiers: sage `#7A8F6A` / amber `#D4A571` / coral `#DA8A6C` / terra `#B8634A`; text-safe: terra-strong `#7B3C26`, sage-strong `#445539`; tier pill bg/fg token pairs as defined
- Fonts: Manrope (sans), Instrument Serif (serif), IBM Plex Sans (`.num`, tnum)
- Radii: cards `rounded-3xl` (24px); pills `rounded-full`
- Shadows: `.soft-shadow`, `.soft-shadow-lg`
- New hex used in prototype not yet a token: row hover/expanded wash `#FAF7F0`, bar track `#F1ECE1`, row divider `#EFE9DD` — consider deriving from existing tokens or adding

## Copy (exact)
- H1: "Inspect where it matters most."
- Lede: "Establishments ranked by their modeled probability of a **failed inspection or critical violation** in the next 180 days. Working from the top of this list surfaces roughly *4× more* failures per visit than inspecting at random."
- Lift card: "In backtests, visits drawn from the top of this list found failures or critical violations about four times as often as visits chosen at random. Predicts *where to look first* — it is not a verdict on any establishment."
- Footer note: "A ranking, not a judgment. Scores are calibrated probabilities from public inspection, license and 311 data. They prioritize limited inspection capacity — every establishment still gets its regular cadence."

## Assets
None. All icons are lucide (`map-pin`, `trending-up`, `arrow-up`/`arrow-down`, `chevron-down`) — already a dependency.

## Files
- `For Inspectors.dc.html` — the interactive hi-fi prototype (open in a browser; filters, sorting, row expand and route-building all work)
- `screenshots/01-page.png` — page top: header, intro, stat cards, filter/sort controls
- `screenshots/queue.png` — priority queue with a row expanded (drivers + history) and sidebar lift card

Note: screenshots were captured at a narrower viewport than the 1280px+ target; treat the prototype itself as the layout source of truth.
