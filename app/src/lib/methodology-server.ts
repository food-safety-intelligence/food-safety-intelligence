/**
 * Server-only loader for the model's evaluation summary — the operating-point
 * table + headline metrics written by `scripts/build_methodology_json.py`.
 * NEVER import from a "use client" component; it uses `node:fs`.
 *
 * Batch-to-JSON contract: the web app never runs the model. The "How this
 * works" page renders these precomputed numbers.
 */

import "server-only";
import { promises as fs } from "node:fs";
import path from "node:path";

export interface OperatingPoint {
  /** Fraction of restaurants flagged (e.g. 0.10 = top 10% by risk). */
  frac: number;
  n_flagged: number;
  /** Share of the flagged list that has an event. */
  precision: number;
  /** Share of ALL events captured by the flagged list. */
  recall: number;
  /** precision / base rate (1.0 = no better than random). */
  lift: number;
  events_caught: number;
}

/** Ties the rendered numbers to the exact code + dataset that produced them. */
export interface Provenance {
  run_id: string;
  git_commit: string | null;
  git_dirty: boolean | null;
  feature_set_version: string;
  features_sha256: string;
}

/** One bar in the global feature-impact chart: mean |log-odds| across the
 *  test set. Higher = the feature moves the score more, on average. */
export interface GlobalImportance {
  feature: string;
  label: string;
  mean_abs_logodds: number;
}

/** One line of the worked waterfall — a single driver's CALIBRATED log-odds
 *  contribution for the example establishment. */
export interface WaterfallDriver {
  feature: string;
  label: string;
  contribution: number;
}

/**
 * One anonymised worked example showing how the model's pieces add up — in
 * calibrated log-odds — to a published probability:
 *   base + Σ drivers + other = total_logit,   sigmoid(total_logit) = probability.
 * The contributions are already in calibrated space, so the sum lands exactly
 * on `probability` (no reconciliation gap with the gauge).
 */
export interface Waterfall {
  base: number;
  drivers: WaterfallDriver[];
  other: number;
  total_logit: number;
  probability: number;
}

export interface Methodology {
  generated_at: string;
  model_version: string;
  /** Absent in older JSON written before provenance was added. */
  provenance?: Provenance;
  test: { n: number; prevalence: number; events: number; split_from: string };
  headline: { pr_auc: number; roc_auc: number; top_decile_lift: number };
  /** Score→tier bands (Low/Moderate/Elevated/High) for the badge legend.
   *  Probability cutoffs; the top band's `max` is null (open-ended). Absent in
   *  older JSON written before tiers were surfaced. */
  risk_tiers?: { label: string; min: number; max: number | null }[];
  operating_points: OperatingPoint[];
  /** Absent in older JSON written before the SHAP section was added. */
  global_importance?: GlobalImportance[];
  waterfall?: Waterfall;
}

let cached: Methodology | null = null;

/**
 * Load `public/data/methodology.json`. If it hasn't been generated yet,
 * return an empty-operating-points shape so the page degrades to a
 * "metrics pending" state rather than crashing the build.
 */
export async function loadMethodology(): Promise<Methodology> {
  if (cached) return cached;
  const file = path.join(process.cwd(), "public", "data", "methodology.json");
  try {
    cached = JSON.parse(await fs.readFile(file, "utf-8")) as Methodology;
  } catch {
    cached = {
      generated_at: "",
      model_version: "",
      test: { n: 0, prevalence: 0, events: 0, split_from: "" },
      headline: { pr_auc: 0, roc_auc: 0, top_decile_lift: 0 },
      operating_points: [],
    };
  }
  return cached;
}
