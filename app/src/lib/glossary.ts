/**
 * Canonical definitions for the recurring food-safety terms, shared between
 * the in-context popover ({@link DefineTerm}) and the Definitions section on
 * the how-it-works page — so a term is defined in exactly one place.
 *
 * `id` doubles as the how-it-works anchor (`/how-it-works#<id>`), so a popover's
 * "Full definition" link and the page section stay in sync.
 */

export interface GlossaryEntry {
  id: string;
  term: string;
  /** One/two-sentence definition shown in the popover and the page section. */
  short: string;
}

export const GLOSSARY = {
  "priority-violations": {
    id: "priority-violations",
    term: "Priority violation",
    short:
      "Chicago's serious tier (codes 1–29): the hazards most likely to cause foodborne illness — temperature abuse, handwashing failures, cross-contamination, sewage/plumbing. A priority violation in the next 180 days is part of what the model predicts.",
  },
  "core-violations": {
    id: "core-violations",
    term: "Core violation",
    short:
      "Lower-tier violations (codes 30+): important but less immediately hazardous — labeling, maintenance, equipment, and documentation issues.",
  },
  "inspection-types": {
    id: "inspection-types",
    term: "Inspection type",
    short:
      "Why a visit happened: Canvass (routine, risk-based schedule), Complaint (triggered by a 311 report), License (before a new business opens), or Re-Inspection (follow-up to confirm earlier violations were fixed).",
  },
  "chicago-risk": {
    id: "chicago-risk",
    term: "Chicago risk category",
    short:
      "Chicago assigns each establishment a Risk 1 (High) / 2 (Medium) / 3 (Low) category by how hazardous its food operations are, set at licensing before any inspection. It's an input to our model — not our output score.",
  },
  "risk-tiers": {
    id: "risk-tiers",
    term: "Risk tier",
    short:
      "Our Low / Moderate / Elevated / High bands, assigned from the model's predicted probability. Distinct from Chicago's own Risk 1–3 category.",
  },
} satisfies Record<string, GlossaryEntry>;

export type GlossaryKey = keyof typeof GLOSSARY;

/** Ordered for display on the how-it-works Definitions section. */
export const GLOSSARY_ORDER: GlossaryKey[] = [
  "priority-violations",
  "core-violations",
  "inspection-types",
  "chicago-risk",
  "risk-tiers",
];

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
  return null;
}
