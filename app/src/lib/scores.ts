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
  trend_slope_90d: number | null;
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
  scores: RestaurantScore[];
  inspection_history: Record<string, InspectionEvent[]>;
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

export type TrendDirection = "improving" | "stable" | "worsening";

export function trendDirection(slope: number | null): TrendDirection {
  if (slope === null) return "stable";
  if (slope > 0.001) return "worsening";
  if (slope < -0.001) return "improving";
  return "stable";
}
