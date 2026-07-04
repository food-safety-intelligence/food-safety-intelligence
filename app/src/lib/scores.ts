/**
 * Score types, constants, and pure helpers.
 *
 * This file is safe to import from both server and client components — it
 * has no runtime dependencies on Node.js APIs. Filesystem-based loaders live
 * in `scores-server.ts` and may ONLY be imported by server components.
 *
 * Authoritative schema: docs/interface_contracts.md.
 */

export type RiskTier = "Low" | "Moderate" | "Elevated" | "High";

/**
 * The single biggest driver, in the compact form carried by a map pin /
 * list row. This is `top_drivers[0]` reduced to what a one-line glance needs:
 * the plain-English `label`, the `feature` key (for the topic icon), and the
 * `up` direction (true = raises risk). The signed `shap` magnitude is dropped
 * — rows show direction, not the precise log-odds value (that lives on the
 * detail page).
 */
export interface PinDriver {
  feature: string;
  label: string;
  up: boolean;
}

/**
 * Minimal per-restaurant record shipped to the map for zoom-aware density.
 * Keep this lean — at 23k+ rows every extra field is a noticeable RSC
 * payload hit. The map uses this set for pins; clicking a pin opens the
 * detail page (which fetches the full record server-side).
 *
 * `top_driver` is the one deliberate exception to "keep it lean": carrying
 * the #1 driver lets the map popup and the search-result list rows answer
 * "what's driving this?" without a detail-page round-trip. We ship only the
 * top driver (not all 4), so the per-pin cost stays bounded.
 */
export interface PinSummary {
  license_id: string;
  dba_name: string;
  address: string;
  lat: number;
  lon: number;
  risk_score: number;
  risk_tier: RiskTier;
  top_driver?: PinDriver;
}

export interface Driver {
  feature: string;
  value: string;
  shap: number;
  label: string;
  detail?: string;
}

export interface RestaurantScore {
  license_id: string;
  dba_name: string;
  address: string;
  neighborhood: string;
  zip: string;
  facility_type: string;
  lat: number;
  lon: number;
  risk_score: number;
  risk_tier: RiskTier;
  trend_slope: number | null;
  trend_ci_low?: number | null;
  trend_ci_high?: number | null;
  top_drivers: Driver[];
  /**
   * Server-computed percentile rank of this restaurant's `risk_score` in the
   * full scored population (0–100). 100 = highest score in the dataset.
   * Computed by `loadScores()` in scores-server.ts; not present in
   * scores.json itself.
   */
  percentile_rank?: number;
}

/** Aggregate stats over the entire scored population. Computed server-side. */
export interface PopulationStats {
  total: number;
  median: number;
  mean: number;
}

export interface InspectionEvent {
  date: string;
  type: string;
  result: "Pass" | "Pass w/ Conditions" | "Fail" | string;
  headline: string;
  /**
   * Forecast-only model score (calibrated probability) for this inspection — the
   * trend-chart trajectory point. Null for inspections that predate the feature
   * window (older / burn-in). See decision 0011.
   */
  score?: number | null;
  /**
   * Full violation text for this inspection — the pipe-delimited violations
   * rejoined as newline-separated lines, each "<code>. <NAME> - Comments:
   * <text>". Shown when a timeline row is expanded. Loaded from a separate
   * sharded sidecar (see getInspectionComments) and merged in on the detail
   * page, so it's absent on rows that haven't had comments attached. Empty
   * string means the inspection recorded no violations/comments.
   */
  comments?: string;
}

/**
 * Platt-calibration triple, shipped ONCE per payload (not per row). With it,
 * the detail page reconstructs each establishment's calibrated-log-odds
 * waterfall from data it already has (the row's `risk_score` + `top_drivers`
 * shap values) — see {@link computeWaterfall}. Absent in older scores.json.
 */
export interface Calibration {
  a: number;
  b: number;
  intercept: number;
}

export interface ScoresPayload {
  schema_version: string;
  generated_at: string;
  as_of_date: string;
  is_mock: boolean;
  model_version: string;
  label_window_days: number;
  totals: {
    establishments: number;
    tier_counts: Record<RiskTier, number>;
    worsening_30d: number;
    improving_30d: number;
  };
  /** Absent in older JSON written before the per-profile waterfall was added. */
  calibration?: Calibration;
  scores: RestaurantScore[];
  // History is no longer merged into the payload — it's read per-license from
  // shards (see scores-server.ts getInspectionHistory). Kept optional for the
  // raw pipeline JSON shape.
  inspection_history?: Record<string, InspectionEvent[]>;
}

/**
 * Per-license bundle the client-rendered detail page fetches from
 * `/data/detail/<license_id>.json` (written by scripts/build-detail-data.mjs).
 * `restaurant.percentile_rank` is precomputed at build time; `comments` is
 * index-aligned to `history`.
 */
export interface DetailBundle {
  restaurant: RestaurantScore;
  history: InspectionEvent[];
  comments: string[];
}

/**
 * Globals the detail page needs once, fetched from `/data/detail-globals.json`:
 * the demo-mode flag, the Platt-calibration triple (for the waterfall), and the
 * population aggregate stats (for the score percentile). Mirrors what the server
 * detail page used to derive from `loadScores()` + `getPopulationStats()`.
 */
export interface DetailGlobals {
  is_mock: boolean;
  calibration: Calibration | null;
  populationStats: PopulationStats;
}

// ---------------------------------------------------------------------------
// Pure helpers — safe to call from server or client.
// ---------------------------------------------------------------------------

// Tiers are assigned in Python (score_to_tier / RISK_TIER_THRESHOLDS) and shipped
// in scores.json's risk_tier field — the app reads that directly and never buckets
// scores itself. See decision record 0008 (risk-tier thresholds).

/**
 * Map a tier to its colour-token name. Useful for inline styles and lookup
 * tables. For Tailwind class names, use TIER_*_CLASS maps below — Tailwind 4's
 * scanner won't pick up `text-${...}` constructions.
 */
export const TIER_COLOR: Record<RiskTier, "sage" | "amber" | "coral" | "terra"> = {
  Low: "sage",
  Moderate: "amber",
  Elevated: "coral",
  High: "terra",
};

/**
 * Tailwind 4 needs to see each class string verbatim in the source so its
 * compiler can emit the CSS. These maps make tier-aware styling safe.
 */
export const TIER_TEXT_CLASS: Record<RiskTier, string> = {
  Low: "text-sage",
  Moderate: "text-amber",
  Elevated: "text-coral",
  High: "text-terra",
};

export const TIER_BG_CLASS: Record<RiskTier, string> = {
  Low: "bg-sage",
  Moderate: "bg-amber",
  Elevated: "bg-coral",
  High: "bg-terra",
};

export const TIER_HEX: Record<RiskTier, string> = {
  Low: "#7A8F6A",
  Moderate: "#D4A571",
  Elevated: "#DA8A6C",
  High: "#B8634A",
};

/**
 * Reduce a full {@link Driver} to the compact {@link PinDriver} a map pin /
 * list row carries: keep the label + feature key (for the icon), and collapse
 * the signed `shap` to an `up` direction (true = raises risk). A zero `shap`
 * counts as not-raising (`up=false`), matching the sage "lowers risk" styling.
 */
export function toPinDriver(d: Driver): PinDriver {
  return { feature: d.feature, label: d.label, up: d.shap > 0 };
}

/** One step of a per-establishment waterfall, in calibrated log-odds. */
export interface WaterfallStep {
  feature: string;
  label: string;
  /** Calibrated log-odds contribution (signed). */
  contribution: number;
  up: boolean;
}

/**
 * The score broken into calibrated log-odds: `base + Σ steps + (everything else)
 * = total`, and `sigmoid(total) = probability`. The caller renders `steps`,
 * then derives the "everything else" bucket as `total − base − Σ(shown steps)`
 * so the displayed column reconciles exactly at whatever precision it shows.
 */
export interface WaterfallBreakdown {
  base: number;
  steps: WaterfallStep[];
  total: number;
  probability: number;
}

/**
 * Reconstruct an establishment's calibrated-log-odds waterfall from the shipped
 * {@link Calibration} triple and the row's own `risk_score` + `top_drivers`.
 *
 * Platt calibration is linear in the raw logit L: `calibrated_logit = −(a·L + b)`
 * and `L = intercept + Σ raw_contributions`. So each driver's calibrated
 * contribution is `−a · shap`, the base is `−a · intercept − b`, and the total
 * calibrated logit is simply `logit(risk_score)` — recovered from the published
 * probability (clamped so the rare p=1.0 doesn't diverge). By construction
 * `sigmoid(total) = risk_score`, so the waterfall lands exactly on the gauge.
 */
export function computeWaterfall(
  r: RestaurantScore,
  cal: Calibration,
): WaterfallBreakdown {
  const slope = -cal.a;
  const base = slope * cal.intercept - cal.b;
  const steps: WaterfallStep[] = r.top_drivers.map((d) => ({
    feature: d.feature,
    label: d.label,
    contribution: slope * d.shap,
    up: d.shap > 0,
  }));
  const p = Math.min(Math.max(r.risk_score, 1e-6), 1 - 1e-6);
  const total = Math.log(p / (1 - p));
  return { base, steps, total, probability: r.risk_score };
}

export type TrendDirection = "improving" | "stable" | "worsening";

/**
 * Minimum |slope| (forecast-score per day) to call a trend non-stable. Tuned to
 * Model 2's last-K-visits scale (decision 0011): the production slopes are tiny
 * (most within ±0.001), and 0.0003 lines "worsening" up with the steeply-rising
 * watch-list threshold from the experiment. Below it the trajectory reads Stable.
 */
export const TREND_STABLE_BAND = 0.0003;

export function trendDirection(
  slope: number | null,
  band: number = TREND_STABLE_BAND,
): TrendDirection {
  if (slope === null) return "stable";
  if (slope > band) return "worsening";
  if (slope < -band) return "improving";
  return "stable";
}

// ---------------------------------------------------------------------------
// Home search/sort — shared between the server loader and the client shell.
// ---------------------------------------------------------------------------

export const ALL_TIERS: RiskTier[] = ["Low", "Moderate", "Elevated", "High"];

export type HomeSort = "risk" | "low" | "name";

/** Lean row for the home side-list. Carries trend (the pin set does not). */
export interface HomeListRow {
  license_id: string;
  dba_name: string;
  address: string;
  risk_score: number;
  risk_tier: RiskTier;
  trend_slope: number | null;
  top_driver?: PinDriver;
}

/**
 * What the server hands the home shell after applying the URL query/filters.
 * Both the side list and the map pins are pre-filtered server-side, so the
 * client component only renders and edits the URL — no client-side filtering.
 */
export interface HomeView {
  listRows: HomeListRow[];
  pins: PinSummary[];
  /** Total matches before the list cap (so the UI can say "200 of 1,402"). */
  matchCount: number;
  /** Total establishments in the index, for the "of N" denominator. */
  total: number;
  tierCounts: Record<RiskTier, number>;
  listLimit: number;
}

/**
 * Parse the `?tier=` URL value (comma-separated tier names) into a validated
 * set. Absent / empty / all-invalid → all tiers (the default browse state).
 */
export function parseTiers(raw: string | undefined): RiskTier[] {
  if (!raw) return [...ALL_TIERS];
  const wanted = new Set(raw.split(","));
  const valid = ALL_TIERS.filter((t) => wanted.has(t));
  return valid.length > 0 ? valid : [...ALL_TIERS];
}

/** True when every tier is selected — i.e. the tier filter is a no-op. */
export function isAllTiers(tiers: RiskTier[]): boolean {
  return tiers.length === ALL_TIERS.length;
}

/** Case-insensitive substring match over name + address. */
export function matchesQuery(
  row: { dba_name: string; address: string },
  q: string,
): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  return `${row.dba_name} ${row.address}`.toLowerCase().includes(needle);
}

/**
 * "A–Z" comparator. Two quirks of raw `dba_name` values break a naive
 * `localeCompare` sort:
 *   - names starting with a digit or symbol ("7-Eleven", "#1 Wok") sort ahead
 *     of the letters, so the list opens on numbers instead of "A";
 *   - some names carry leading whitespace ("  JIMMY FAMOUS BURGER"), and
 *     localeCompare orders a leading space ahead of letters too — floating
 *     those names above the "A"s.
 * Compare on the trimmed name: group letter-initial names first, the rest
 * after, then sort alphabetically within each group.
 */
export function compareByName(a: string, b: string): number {
  const at = a.trimStart();
  const bt = b.trimStart();
  const aLetter = /^\p{L}/u.test(at);
  const bLetter = /^\p{L}/u.test(bt);
  if (aLetter !== bLetter) return aLetter ? -1 : 1;
  return at.localeCompare(bt);
}

/** Validate a raw `?sort=` value into a {@link HomeSort}; default "risk". */
export function parseSort(raw: string | null | undefined): HomeSort {
  return raw === "name" ? "name" : raw === "low" ? "low" : "risk";
}

// ---------------------------------------------------------------------------
// Client search index
//
// The home page is statically exported, so it can't filter per-request on the
// server. Instead the browser fetches a slim index of EVERY establishment
// (scripts/gen-search-index.mjs) and filters with `computeHomeView` below —
// the client-side twin of the server's `getHomeView`, producing the same
// `HomeView` shape so `MapExplorer` renders identically either way.
// ---------------------------------------------------------------------------

/** One establishment in the slim client search index. */
export interface SearchIndexRow {
  license_id: string;
  dba_name: string;
  address: string;
  lat: number | null;
  lon: number | null;
  risk_score: number;
  risk_tier: RiskTier;
  trend_slope: number | null;
  top_driver: PinDriver | null;
}

/** The whole `search-index.json` file the client fetches once. */
export interface SearchIndex {
  schema_version: string;
  generated_at: string | null;
  total: number;
  tier_counts: Record<RiskTier, number>;
  rows: SearchIndexRow[];
}

function hasCoords(r: SearchIndexRow): boolean {
  return (
    r.lat != null &&
    r.lon != null &&
    !Number.isNaN(r.lat) &&
    !Number.isNaN(r.lon)
  );
}

/**
 * Apply the URL query/tier/sort to the slim index, client-side. Mirrors the
 * server's `getHomeView`: filter by tier + query over the full population,
 * sort, cap the list, and build the (coordinate-bearing) map pins — so the
 * statically-exported page gets the same search/sort/filter the server used
 * to do per-request, now in the browser.
 */
export function computeHomeView(
  index: SearchIndex,
  opts: { q: string; tiers: RiskTier[]; sort: HomeSort; listLimit: number },
): HomeView {
  const { q, tiers, sort, listLimit } = opts;
  const tierSet = new Set(tiers);
  const tierActive = !isAllTiers(tiers);

  const matched = index.rows.filter(
    (r) => (!tierActive || tierSet.has(r.risk_tier)) && matchesQuery(r, q),
  );

  const byScore = (a: SearchIndexRow, b: SearchIndexRow) =>
    sort === "name"
      ? compareByName(a.dba_name, b.dba_name)
      : sort === "low"
        ? a.risk_score - b.risk_score
        : b.risk_score - a.risk_score;

  const listRows: HomeListRow[] = matched
    .slice()
    .sort(byScore)
    .slice(0, listLimit)
    .map((r) => ({
      license_id: r.license_id,
      dba_name: r.dba_name,
      address: r.address,
      risk_score: r.risk_score,
      risk_tier: r.risk_tier,
      trend_slope: r.trend_slope,
      top_driver: r.top_driver ?? undefined,
    }));

  const pins: PinSummary[] = matched
    .filter(hasCoords)
    .sort((a, b) =>
      sort === "low" ? a.risk_score - b.risk_score : b.risk_score - a.risk_score,
    )
    .map((r) => ({
      license_id: r.license_id,
      dba_name: r.dba_name,
      address: r.address,
      lat: r.lat as number,
      lon: r.lon as number,
      risk_score: r.risk_score,
      risk_tier: r.risk_tier,
      top_driver: r.top_driver ?? undefined,
    }));

  return {
    listRows,
    pins,
    matchCount: matched.length,
    total: index.total,
    tierCounts: index.tier_counts,
    listLimit,
  };
}
