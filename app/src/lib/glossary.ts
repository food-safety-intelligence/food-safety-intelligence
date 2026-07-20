/**
 * Canonical definitions for the recurring food-safety terms, shared between
 * the in-context popover ({@link DefineTerm}) and the Definitions section on
 * the how-it-works page — so a term is defined in exactly one place.
 *
 * Definitions split two ways:
 *
 * - **Shared** terms describe the product, not a city: the risk score, the
 *   trend estimate, the tiers, calibration, SHAP, and the two ranking metrics.
 *   Every city shows them, so a deep link like `/how-it-works#risk-score`
 *   resolves whichever city the reader is on.
 * - **City-specific** terms describe one city's inspection regime: Chicago's
 *   priority/core violation codes and risk category, NYC's and LA's letter
 *   grades and point scales.
 *
 * Wording that names the predicted outcome is templated from `CITY_CONFIG`
 * rather than written per city, so a Chicago reader sees "fail an inspection or
 * be cited for a priority violation" and an LA reader sees "be graded B or C"
 * from the same entry.
 *
 * Measured values (ROC-AUC, lift) are deliberately NOT quoted here — they go
 * stale every retrain. The pages read the live numbers from `methodology.json`.
 *
 * `id` doubles as the how-it-works anchor (`/how-it-works#<id>`), so a popover's
 * "Full definition" link and the page section stay in sync.
 */

import { CITY_CONFIG, type City, type CityConfig } from "@/lib/city";

export interface GlossaryEntry {
  id: string;
  term: string;
  /** One/two-sentence definition shown in the popover and the page section. */
  short: string;
  /**
   * Override for the popover's "Full definition" link. Defaults to this term's
   * own Definitions-section anchor (`/how-it-works#<id>`); set it to point at a
   * richer prose section instead (e.g. the trend/score explanations).
   */
  href?: string;
}

/** Terms every city defines. */
export type SharedGlossaryKey =
  | "risk-score"
  | "trend-estimate"
  | "risk-tiers"
  | "severity-tier"
  | "violation-dictionary"
  | "calibration"
  | "shap"
  | "pr-auc"
  | "lift";

/** Terms that only make sense for one city's inspection regime. */
export type CityGlossaryKey =
  | "priority-violations"
  | "core-violations"
  | "inspection-types"
  | "current-inspection"
  | "chicago-risk"
  | "letter-grade"
  | "inspection-score";

export type GlossaryKey = SharedGlossaryKey | CityGlossaryKey;

/** A definition, or a builder for one whose wording depends on the city. */
type Definition = GlossaryEntry | ((c: CityConfig) => GlossaryEntry);

const SHARED: Record<SharedGlossaryKey, Definition> = {
  "risk-score": (c) => ({
    id: "risk-score",
    term: "Risk score",
    short: `The headline 0–100 prediction on the gauge: the production model's estimate that the establishment will ${c.outcomeSentence}. It counts the latest inspection's own result, so it can differ from the trend chart's last point.`,
    // Link to the richer "Reading the score" prose, not just the one-line entry.
    href: "/how-it-works#reading-the-score",
  }),
  "trend-estimate": {
    id: "trend-estimate",
    term: "Trend estimate",
    short:
      "The forecast model's 0–100 risk read as of each past inspection, with that visit's own outcome left out. Plotted as the trend chart's dots so the line shows direction over time, not a second headline number.",
    // Link to the richer "recent trend" prose (two-models explanation).
    href: "/how-it-works#recent-trend",
  },
  "risk-tiers": (c) => ({
    id: "risk-tiers",
    term: "Risk tier",
    short:
      `The Low / Moderate / Elevated / High band shown on the map, list, and detail pages, assigned from the model's predicted probability and recalibrated to ${c.label}'s own distribution.` +
      (c.id === "chicago"
        ? " Distinct from Chicago's own Risk 1–3 category."
        : ""),
  }),
  "severity-tier": {
    id: "severity-tier",
    term: "Severity tier",
    short:
      "A shared way to describe how serious a violation is (imminent-hazard, critical, or general), mapped from each city's own codes via the shared violation dictionary.",
  },
  "violation-dictionary": {
    id: "violation-dictionary",
    term: "Violation dictionary",
    short:
      "A lookup that maps each city's own violation codes to a shared set of plain-language themes (temperature, pest, hygiene, contamination, …) and severity tiers, so one vocabulary describes violations everywhere even though each city files them differently.",
  },
  calibration: (c) => ({
    id: "calibration",
    term: "Calibration",
    short: `A final step that makes the 0–1 score read as a real probability, so a 0.30 really means about 30 in 100 similar establishments went on to ${c.outcomeSentence}.`,
  }),
  shap: {
    id: "shap",
    term: "SHAP driver",
    short:
      "A per-establishment breakdown of which features pushed the score up or down, in log-odds: the signed list shown under “what's driving the score” on a detail page.",
  },
  "pr-auc": {
    id: "pr-auc",
    term: "PR-AUC / ROC-AUC",
    short:
      "Two ranking-quality scores. PR-AUC rewards finding the minority of establishments that go on to a bad outcome, so it moves with how common that outcome is. ROC-AUC is base-rate independent, which makes it the fairer number to compare one city against another. The measured values are in the model card above.",
  },
  lift: {
    id: "lift",
    term: "Top-decile lift",
    short:
      "How much better than chance the top 10% by predicted risk is. A lift of 3 means that slice has three times the bad-outcome rate of the whole population.",
  },
};

const CITY_TERMS: Record<City, Partial<Record<CityGlossaryKey, Definition>>> = {
  chicago: {
    "priority-violations": {
      id: "priority-violations",
      term: "Priority violation",
      short:
        "Chicago's serious tier (codes 1–29): the hazards most likely to cause foodborne illness (temperature abuse, handwashing failures, cross-contamination, sewage/plumbing). A priority violation in the next 180 days is part of what the model predicts.",
    },
    "core-violations": {
      id: "core-violations",
      term: "Core violation",
      short:
        "Lower-tier violations (codes 30+): important but less immediately hazardous (labeling, maintenance, equipment, and documentation issues).",
    },
    "inspection-types": {
      id: "inspection-types",
      term: "Inspection type",
      short:
        "Why a visit happened: Canvass (routine, risk-based schedule), Complaint (triggered by a public complaint), License (before a new business opens), or Re-Inspection (follow-up to confirm earlier violations were fixed).",
    },
    "current-inspection": {
      id: "current-inspection",
      term: "Current inspection result",
      short:
        "Whether the establishment passed or failed the inspection on record as of this score: the model's strongest near-term signal. It describes that latest visit, not a prediction; the score is about the next 180 days.",
    },
    "chicago-risk": {
      id: "chicago-risk",
      term: "Chicago risk category",
      short:
        "Chicago assigns each establishment a Risk 1 (High) / 2 (Medium) / 3 (Low) category by how hazardous its food operations are, set at licensing before any inspection. It's an input to our model, not our output score.",
    },
  },
  nyc: {
    "letter-grade": {
      id: "letter-grade",
      term: "Letter grade (A / B / C)",
      short:
        "New York's public restaurant grade. It's a threshold on the inspection score: A = 0–13 points, B = 14–27, C = 28 or more. Lower is cleaner, the opposite of Los Angeles County's scale.",
    },
    "inspection-score": {
      id: "inspection-score",
      term: "Inspection score",
      short:
        "The sum of violation points at one inspection: public-health hazards score at least 7 points, critical violations at least 5, general violations at least 2. The score maps to the letter grade; a place is counted as bad next time if it reaches 14 (a B or C).",
    },
  },
  la: {
    "letter-grade": {
      id: "letter-grade",
      term: "Letter grade (A / B / C)",
      short:
        "Los Angeles County's public restaurant grade. It's a threshold on the 0–100 inspection score: A = 90–100, B = 80–89, C = 70–79. Higher is cleaner, the opposite of New York's scale.",
    },
    "inspection-score": {
      id: "inspection-score",
      term: "Inspection score",
      short:
        "100 minus the points deducted for violations at one inspection (major and critical violations deduct more). The score maps to the letter grade; a place is counted as bad next time if it drops below 90 (a B or C, or an ungraded sub-70 result).",
    },
  },
};

/** Display order for the how-it-works Definitions section, per city. */
const ORDER: Record<City, GlossaryKey[]> = {
  chicago: [
    "risk-score",
    "trend-estimate",
    "risk-tiers",
    "priority-violations",
    "core-violations",
    "inspection-types",
    "current-inspection",
    "chicago-risk",
    "severity-tier",
    "violation-dictionary",
    "calibration",
    "shap",
    "pr-auc",
    "lift",
  ],
  nyc: [
    "risk-score",
    "trend-estimate",
    "risk-tiers",
    "letter-grade",
    "inspection-score",
    "severity-tier",
    "violation-dictionary",
    "calibration",
    "shap",
    "pr-auc",
    "lift",
  ],
  la: [
    "risk-score",
    "trend-estimate",
    "risk-tiers",
    "letter-grade",
    "inspection-score",
    "severity-tier",
    "violation-dictionary",
    "calibration",
    "shap",
    "pr-auc",
    "lift",
  ],
};

function resolve(def: Definition, config: CityConfig): GlossaryEntry {
  return typeof def === "function" ? def(config) : def;
}

/**
 * Resolve one term for a city. Falls back to Chicago's wording for a
 * city-specific term the given city doesn't define, so an in-context popover
 * always has something to show.
 */
export function glossaryEntry(key: GlossaryKey, city: City): GlossaryEntry {
  const config = CITY_CONFIG[city];
  const def =
    key in SHARED
      ? SHARED[key as SharedGlossaryKey]
      : (CITY_TERMS[city][key as CityGlossaryKey] ??
        CITY_TERMS.chicago[key as CityGlossaryKey]);
  if (!def) {
    throw new Error(`No glossary definition for "${key}"`);
  }
  return resolve(def, config);
}

/** Every term a city's Definitions section shows, in display order. */
export function glossaryFor(city: City): GlossaryEntry[] {
  return ORDER[city].map((key) => glossaryEntry(key, city));
}

/**
 * Map a model feature to the glossary term it relates to, so a driver row can
 * offer an in-context definition. Keyed by feature (not by parsing the label
 * text). Returns null when no term applies (e.g. the keyword flags, which
 * already carry their own inline description).
 */
export function glossaryKeyForFeature(feature: string): GlossaryKey | null {
  if (
    feature === "n_priority_this_inspection" ||
    feature === "prior_priority_violations" ||
    feature === "prior_priority_violations_365d" ||
    feature === "prev_priority_violations"
  ) {
    return "priority-violations";
  }
  if (feature === "n_core_this_inspection" || feature === "prior_core_violations") {
    return "core-violations";
  }
  if (feature === "static_inspection_type") return "inspection-types";
  if (feature === "static_risk_tier") return "chicago-risk";
  if (feature === "was_fail") return "current-inspection";
  return null;
}
