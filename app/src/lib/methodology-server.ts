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

/** One split's date range and row count. */
export interface DateWindow {
  start: string;
  end: string;
  n: number;
}

/** One cross-validation fold: the year validated, its date range, and PR-AUC. */
export interface CvFold {
  val_year: number;
  train_n: number;
  val_n: number;
  train_through: string;
  val_from: string;
  val_to: string;
  pr_auc: number;
}

/** Expanding-window cross-validation summary across the development set. */
export interface CrossValidation {
  scheme: string;
  embargo_days: number;
  n_folds: number;
  pr_auc_mean: number | null;
  pr_auc_std: number | null;
  folds: CvFold[];
}

export interface Methodology {
  generated_at: string;
  model_version: string;
  /** Absent in older JSON written before provenance was added. */
  provenance?: Provenance;
  test: { n: number; prevalence: number; events: number; split_from: string };
  /** Chronological split date ranges (train / validation / test). Absent in
   *  older JSON written before the windows were surfaced. */
  windows?: {
    train: DateWindow;
    val: DateWindow;
    test: DateWindow;
  };
  /** Expanding-window cross-validated PR-AUC on the development set (train+val),
   *  one fold per calendar year with a 180-day embargo. Absent in older JSON. */
  cross_validation?: CrossValidation;
  headline: { pr_auc: number; roc_auc: number; top_decile_lift: number };
  /** Score→tier bands (Low/Moderate/Elevated/High) for the badge legend.
   *  Probability cutoffs (top band's `max` is null) + `share` (fraction of
   *  scored establishments, from the served scores.json). Absent in older JSON
   *  written before tiers were surfaced; `share` absent if scores weren't built. */
  risk_tiers?: {
    label: string;
    min: number;
    max: number | null;
    share?: number;
  }[];
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
