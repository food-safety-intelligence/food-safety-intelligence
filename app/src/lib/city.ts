// Multi-city support (DR 0014). One static build serves both cities; the
// selected city is a client concern (URL `?city=` → localStorage → default).
// Every per-city difference — data path, map framing, and the copy that names
// the label/window/source — lives here so components stay city-agnostic.

export type City = "chicago" | "nyc";

export const CITIES: City[] = ["chicago", "nyc"];
export const DEFAULT_CITY: City = "chicago";

export interface CityConfig {
  id: City;
  label: string;
  /** Data path prefix under /data/. Chicago is the historical root (""). */
  dataPrefix: string;
  /** Map framing. */
  center: { lat: number; lon: number };
  zoom: number;
  centerLabel: string;
  /** Copy that changes because the label/window/source differ per city. */
  nounPlural: string; // "food establishments"
  /** One-line description of what the risk score predicts. */
  predictionBlurb: string;
  /** Short source sentence for the home "why this exists" section. */
  sourceBlurb: string;
  /** Detail-page copy that names the label / place / source. */
  cityState: string; // "Chicago, IL"
  healthDept: string;
  riskLabel: string; // "Predicted 180-day risk"
  typicalNoun: string; // "Chicago food establishment"
  comparedNoun: string; // "currently active food licenses"
  /** Full sentence completing "…whether this establishment will …". */
  outcomeSentence: string;
  /** Footer. */
  footerBlurb: string;
  sources: string[];
  /** History section: how inspection outcomes are categorised for this city. */
  historyResults: { key: string; label: string; bg: string; badge: string; match: (result: string) => boolean }[];
  /** Noun for the "N <outcomeNoun>" count in the history headline. */
  outcomeNoun: string; // "failures" / "B or C grades"
  /** Which history results count as a "bad" outcome for that headline count. */
  isBadOutcome: (result: string) => boolean;
  /** |slope| below this reads as "Stable" (per-city so the threshold can track
   * each city's slope scale; empirically both land at 0.0003 here). */
  trendStableBand: number;
  /** Whether the chat agent has data for this city (backend is Chicago-only). */
  chatSupported: boolean;
}

export const CITY_CONFIG: Record<City, CityConfig> = {
  chicago: {
    id: "chicago",
    label: "Chicago",
    dataPrefix: "",
    center: { lat: 41.88, lon: -87.63 },
    zoom: 10,
    centerLabel: "Chicago · 41.88, −87.63",
    nounPlural: "licensed food establishments",  // Chicago's feed covers all licensed food establishments
    predictionBlurb:
      "the chance a place will see a failed inspection or priority violation in the next six months",
    sourceBlurb:
      "Chicago publishes every food establishment inspection it conducts. We pair that record with nearby 311 complaints and license history to estimate the chance a place will see a failed inspection or priority violation in the next six months — and show you exactly why.",
    cityState: "Chicago, IL",
    healthDept: "Chicago Department of Public Health",
    riskLabel: "Predicted 180-day risk",
    typicalNoun: "Chicago food establishment",
    comparedNoun: "currently active food licenses",
    outcomeSentence:
      "fail an inspection or be cited for a priority violation in the next 180 days",
    footerBlurb:
      "Open-data project pairing Chicago Food Inspections with 311 and license records to estimate forward-window food-safety risk. Not affiliated with the City of Chicago.",
    sources: ["Chicago Food Inspections", "Chicago 311 Service Requests", "Chicago Business Licenses"],
    historyResults: [
      { key: "Pass", label: "Pass", bg: "bg-sage", badge: "P", match: (r) => r === "Pass" },
      { key: "PassCond", label: "Pass w/ Conditions", bg: "bg-amber", badge: "!", match: (r) => r === "Pass w/ Conditions" },
      { key: "Fail", label: "Fail", bg: "bg-terra", badge: "×", match: (r) => r === "Fail" },
    ],
    outcomeNoun: "failures",
    isBadOutcome: (r) => r === "Fail",
    trendStableBand: 0.0003,
    chatSupported: true,
  },
  nyc: {
    id: "nyc",
    label: "New York City",
    dataPrefix: "nyc/",
    center: { lat: 40.71, lon: -74.0 },
    zoom: 10,
    centerLabel: "New York City · 40.71, −74.00",
    nounPlural: "licensed restaurants",  // NYC's DOHMH feed is restaurant inspections
    predictionBlurb:
      "the chance a place's next inspection is graded B or C (a score of 14 or more points)",
    sourceBlurb:
      "New York City publishes every restaurant inspection its Health Department conducts, each carrying a letter grade (A / B / C). We use inspection history since the post-COVID restart to estimate the chance a place's next inspection is graded B or C — and show you exactly why. NYC is a research-preview second city with a weaker signal than Chicago.",
    cityState: "New York, NY",
    healthDept: "New York City Department of Health and Mental Hygiene",
    riskLabel: "Predicted next-inspection risk",
    typicalNoun: "New York food service establishment",
    comparedNoun: "inspected establishments",
    outcomeSentence: "receive a B or C letter grade at its next inspection",
    footerBlurb:
      "Open-data project using NYC Health Department restaurant inspection records to estimate the risk of a B or C grade at the next inspection. A research preview; not affiliated with the City of New York.",
    sources: ["NYC DOHMH Restaurant Inspection Results"],
    historyResults: [
      { key: "A", label: "Grade A", bg: "bg-sage", badge: "A", match: (r) => r.startsWith("Grade A") },
      { key: "B", label: "Grade B", bg: "bg-amber", badge: "B", match: (r) => r.startsWith("Grade B") },
      { key: "C", label: "Grade C", bg: "bg-terra", badge: "C", match: (r) => r.startsWith("Grade C") },
    ],
    outcomeNoun: "B or C grades",
    isBadOutcome: (r) => r.startsWith("Grade B") || r.startsWith("Grade C"),
    // Empirically NYC's forecast-slope magnitudes sit on the same scale as
    // Chicago's, so 0.0003 gives the most honest split (~9% Worsening / ~2%
    // Improving / ~74% Stable). NYC's slope is intrinsically upward-biased
    // (forecast risk rises as prior B/C history accumulates), so "Improving"
    // is genuinely rare — widening the band only erases it, it doesn't balance.
    trendStableBand: 0.0003,
    // Chat is city-scoped (DR 0014): the frontend sends city=nyc and the agent
    // loads NYC data + scopes lookups. Requires the agent redeploy + NYC data in
    // S3 to answer NYC lookups; until then a NYC lookup returns "no record".
    chatSupported: true,
  },
};

export function isCity(v: unknown): v is City {
  return v === "chicago" || v === "nyc";
}

/** Resolve a data file URL for a city (e.g. dataUrl("nyc", "scores.json")).
 * `public/` assets are not auto-prefixed by Next's basePath, so we prepend
 * NEXT_PUBLIC_BASE_PATH ourselves — empty in prod (no-op), set only for the
 * local jupyter-proxy preview. */
export function dataUrl(city: City, file: string): string {
  const base = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
  return `${base}/data/${CITY_CONFIG[city].dataPrefix}${file}`;
}
