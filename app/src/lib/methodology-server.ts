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

export interface Methodology {
  generated_at: string;
  model_version: string;
  test: { n: number; prevalence: number; events: number; split_from: string };
  headline: { pr_auc: number; roc_auc: number; top_decile_lift: number };
  operating_points: OperatingPoint[];
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
