/**
 * Plain-English descriptions of what each model feature measures and why it's
 * a food-safety risk signal. Shown under each driver in DriverList so a reader
 * understands *which factors are doing the work*, not just the label + bar.
 *
 * Frontend-only: the served `top_drivers[].detail` is currently empty, so these
 * are the fallback. Matching mirrors driver-icons.ts — exact for the canonical
 * features, prefix + keyword for the `flag_kw_<topic>` family.
 */

const EXACT: Record<string, string> = {
  was_fail:
    "Whether this establishment failed its current inspection — the strongest near-term signal of forward risk.",
  n_priority_this_inspection:
    "Priority (code 1–29) violations cited at the current inspection — the serious, higher-risk hazards.",
  n_core_this_inspection:
    "Core (lower-tier) violations at the current inspection — minor issues that still add up.",
  static_inspection_type:
    "The kind of inspection scheduled. Complaint-driven and re-inspections tend to surface more problems than routine canvasses.",
  static_risk_tier:
    "Chicago's own pre-assigned risk category for this establishment type (Risk 1 High → Risk 3 Low).",
  static_facility_type:
    "The kind of establishment (restaurant, grocery, school or hospital kitchen, etc.).",
  static_zip: "The establishment's ZIP-code area.",
  temporal_month:
    "The month of the inspection — captures mild seasonal patterns in violation rates.",
  temporal_quarter:
    "The quarter of the inspection — captures mild seasonal patterns in violation rates.",
  license_age_days:
    "How long the business license has existed — very new and very old licenses can carry different risk.",
  license_n_history_rows:
    "How many license-history records exist (renewals, status changes) — a proxy for business continuity.",
  days_since_last_inspection:
    "Time since the last inspection — long gaps give problems more room to develop unseen.",
  days_since_last_fail:
    "Time since the most recent failed inspection — recent failures weigh more.",
  prior_inspections: "Total inspections on record before this one.",
  prior_fails: "Total failed inspections across the establishment's prior history.",
  prior_priority_violations:
    "Priority (serious) violations across all prior inspections.",
  prior_core_violations:
    "Core (lower-tier) violations across all prior inspections.",
  prior_fail_or_priority_events:
    "Past inspections that ended in a fail or a priority violation.",
  prior_fails_365d: "Failed inspections in the last 12 months — recent failure history.",
  prior_priority_violations_365d:
    "Priority violations cited in the last 12 months — recent serious history.",
  prev_priority_violations:
    "Priority violations cited at the immediately preceding inspection.",
  prior_pass_w_conditions:
    "Past 'Pass with conditions' results — borderline passes that needed follow-up.",
  prior_complaint_inspections:
    "How many past inspections were triggered by 311 complaints rather than routine schedule.",
  prior_reinspections:
    "How many past visits were re-inspections to confirm earlier problems were fixed.",
};

// flag_kw_* family — keyed by the topic substring after the prefix. These flag
// a specific hazard found in recent violation comment text.
const KW: Array<[RegExp, string]> = [
  [
    /(cooling|cool)/,
    "Improper cooling of food cited in recent violations — a common cause of bacterial growth.",
  ],
  [
    /temp/,
    "Temperature-control problems (cold/hot holding) in recent violations — a leading cause of foodborne illness.",
  ],
  [
    /(rodent|vermin|pest|rat|mouse|roach)/,
    "Pest or rodent activity noted in recent violations.",
  ],
  [
    /(soap|towel|handwash|hand[-_ ]?wash|sink|wash)/,
    "Handwashing problems in recent violations — missing soap, paper towels, or sink access.",
  ],
  [
    /(expired|expir|date)/,
    "Expired food or date-marking problems in recent violations.",
  ],
  [
    /(sewage|sewer|drain|leak|plumb|water)/,
    "Sewage, plumbing, or water problems in recent violations.",
  ],
  [
    /(raw|chicken|meat|poultry|cross[-_ ]?contam|cross)/,
    "Raw-food handling or cross-contamination risk in recent violations.",
  ],
  [
    /(manager|certif)/,
    "The certified food-manager requirement was not met at a recent inspection.",
  ],
  [/(mold|mildew)/, "Mold or mildew noted in recent violations."],
];

/**
 * A short description for a model feature, or "" when none is known (the
 * caller then renders just the label). Never throws on unknown input.
 */
export function descriptionForFeature(feature: string): string {
  if (feature in EXACT) return EXACT[feature];
  if (feature.startsWith("flag_kw_")) {
    const topic = feature.slice("flag_kw_".length).toLowerCase();
    for (const [re, text] of KW) {
      if (re.test(topic)) return text;
    }
    return "A specific hazard flagged from recent violation comment text.";
  }
  return "";
}
