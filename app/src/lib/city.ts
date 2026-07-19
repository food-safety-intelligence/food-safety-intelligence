// Multi-city support (DR 0016). One static build serves all three cities; the
// selected city is a client concern (URL `?city=` → localStorage → default).
// Every per-city difference — data path, map framing, and the copy that names
// the label/window/source — lives here so components stay city-agnostic.

export type City = "chicago" | "nyc" | "la";

export const CITIES: City[] = ["chicago", "nyc", "la"];
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
  /**
   * What a record's `neighborhood` value means here, which decides how the detail
   * page writes its location line.
   *
   * "within"   the area sits inside cityState, so show both: a NYC record reads
   *            "1307 Avenue Z, Brooklyn, New York, NY 11235".
   * "locality" the value IS the city, so it REPLACES cityState. LA County's feed
   *            names separate incorporated cities (West Hollywood, Santa Monica)
   *            and postal cities (Van Nuys). Appending those to a fixed
   *            "Los Angeles, CA" read as "West Hollywood, Los Angeles, CA"
   *            (wrong, it is not in Los Angeles) and "Los Angeles, Los Angeles,
   *            CA" (duplicated).
   *
   * Omit when the city publishes no neighborhood at all, as Chicago does.
   */
  neighborhoodKind?: "within" | "locality";
  /** Two-letter state, used for the location line when neighborhoodKind is "locality". */
  stateAbbrev: string; // "IL"
  healthDept: string;
  riskLabel: string; // "Predicted 180-day risk"
  typicalNoun: string; // "Chicago food establishment"
  comparedNoun: string; // "currently active food licenses"
  /** Full sentence completing "…whether this establishment will …". */
  outcomeSentence: string;
  /** Footer. */
  footerBlurb: string;
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
  /** Bullet each violation in the expanded inspection-history list. NYC's
   * violations are full sentences with no leading marker (unlike Chicago's
   * "2." codes or LA's "# 23." numbers), so they need a bullet to read as a
   * list. Omitted (falsy) where the text already carries its own marker. */
  bulletViolations?: boolean;
}

/** Parse the numeric inspection score out of an LA history `result` string —
 * "Grade A (score 95)" or a bare "(score 59)" for a sub-70 (ungraded) inspection.
 * Returns null when no score is present. Used by LA's score-driven history buckets. */
function laScore(result: string): number | null {
  const m = /score (\d+)/.exec(result);
  return m ? Number(m[1]) : null;
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
      "Chicago publishes every food establishment inspection it conducts. We pair that record with its license history to estimate the chance a place will see a failed inspection or priority violation in the next six months, and show you exactly why.",
    cityState: "Chicago, IL",
    // Chicago's feed has no area column worth publishing, so no neighborhoodKind.
    stateAbbrev: "IL",
    healthDept: "Chicago Department of Public Health",
    riskLabel: "Predicted 180-day risk",
    typicalNoun: "Chicago food establishment",
    comparedNoun: "currently active food licenses",
    outcomeSentence:
      "fail an inspection or be cited for a priority violation in the next 180 days",
    footerBlurb:
      "Open-data project pairing Chicago Food Inspections with license records to estimate forward-window food-safety risk. Not affiliated with the City of Chicago.",
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
      "New York City publishes every restaurant inspection its Health Department conducts, each carrying a letter grade (A / B / C). We use inspection history since the post-COVID restart to estimate the chance a place's next inspection is graded B or C, and show you exactly why. NYC is a research-preview second city with a weaker signal than Chicago.",
    cityState: "New York, NY",
    neighborhoodKind: "within", // borough, genuinely inside New York, NY
    stateAbbrev: "NY",
    healthDept: "New York City Department of Health and Mental Hygiene",
    riskLabel: "Predicted next-inspection risk",
    typicalNoun: "New York food service establishment",
    comparedNoun: "inspected establishments",
    outcomeSentence: "receive a B or C letter grade at its next inspection",
    footerBlurb:
      "Open-data project using NYC Health Department restaurant inspection records to estimate the risk of a B or C grade at the next inspection. A research preview; not affiliated with the City of New York.",
    historyResults: [
      { key: "A", label: "Grade A", bg: "bg-sage", badge: "A", match: (r) => r.startsWith("Grade A") },
      { key: "B", label: "Grade B", bg: "bg-amber", badge: "B", match: (r) => r.startsWith("Grade B") },
      { key: "C", label: "Grade C", bg: "bg-terra", badge: "C", match: (r) => r.startsWith("Grade C") },
    ],
    outcomeNoun: "B or C grades",
    isBadOutcome: (r) => r.startsWith("Grade B") || r.startsWith("Grade C"),
    // NYC violation lines are plain sentences — bullet them so they separate.
    bulletViolations: true,
    // Empirically NYC's forecast-slope magnitudes sit on the same scale as
    // Chicago's, so 0.0003 gives the most honest split (~9% Worsening / ~2%
    // Improving / ~74% Stable). NYC's slope is intrinsically upward-biased
    // (forecast risk rises as prior B/C history accumulates), so "Improving"
    // is genuinely rare — widening the band only erases it, it doesn't balance.
    trendStableBand: 0.0003,
    // Chat is city-scoped (DR 0016): the frontend sends city=nyc and the agent
    // loads NYC data + scopes lookups. Requires the agent redeploy + NYC data in
    // S3 to answer NYC lookups; until then a NYC lookup returns "no record".
    chatSupported: true,
  },
  la: {
    id: "la",
    label: "Los Angeles",
    dataPrefix: "la/",
    // LA County is large; frame the dense core and zoom out one step from
    // Chicago/NYC so more of the county is in view on load.
    center: { lat: 34.02, lon: -118.29 },
    zoom: 9,
    centerLabel: "Los Angeles County · 34.02, −118.29",
    nounPlural: "restaurants and markets", // LA County's feed covers restaurants + retail food markets
    predictionBlurb:
      "the chance a place's next inspection is graded B or C (a score below 90 out of 100)",
    sourceBlurb:
      "Los Angeles County publishes every restaurant and market inspection its Environmental Health division conducts, each carrying a letter grade (A / B / C) on a 0-100 scale where higher is cleaner. We use inspection history since 2023 to estimate the chance a place's next inspection drops to a B or C, and show you exactly why. LA is a research-preview third city with a weaker signal than Chicago.",
    cityState: "Los Angeles, CA",
    neighborhoodKind: "locality", // separate incorporated / postal cities
    stateAbbrev: "CA",
    healthDept: "Los Angeles County Department of Public Health",
    riskLabel: "Predicted next-inspection risk",
    typicalNoun: "Los Angeles County food establishment",
    comparedNoun: "inspected establishments",
    outcomeSentence: "be graded B or C at its next inspection (a score below 90)",
    footerBlurb:
      "Open-data project using LA County Environmental Health restaurant and market inspection records to estimate the risk of a B or C grade at the next inspection. A research preview; not affiliated with the County of Los Angeles.",
    // LA grades run the OPPOSITE way to NYC (A = 90-100, higher is cleaner). Bucket
    // by the parsed SCORE, not the letter: a sub-70 inspection carries no letter
    // grade in the feed (LA has no grade below C) and would otherwise render as a
    // bare "(score 59)" that never colours, tallies, or counts — even though the
    // model treats it as bad. Score-driven buckets fold those in. A = 90-100,
    // B = 80-89, C-or-below = under 80.
    historyResults: [
      { key: "A", label: "Grade A", bg: "bg-sage", badge: "A", match: (r) => (laScore(r) ?? -1) >= 90 },
      { key: "B", label: "Grade B", bg: "bg-amber", badge: "B", match: (r) => { const s = laScore(r); return s !== null && s >= 80 && s < 90; } },
      { key: "C", label: "Grade C or below", bg: "bg-terra", badge: "C", match: (r) => { const s = laScore(r); return s !== null && s < 80; } },
    ],
    outcomeNoun: "B or C grades",
    // Bad = score below 90 (a B or C, or a sub-70 ungraded inspection), read from
    // the score so ungraded-but-low inspections still count toward the headline.
    isBadOutcome: (r) => { const s = laScore(r); return s !== null ? s < 90 : /^Grade [BC]/.test(r); },
    // LA's forecast-slope magnitudes sit on the same scale as Chicago's and NYC's
    // (the forecast model is a prior-history XGBoost), so 0.0003 gives the
    // same honest Worsening / Stable / Improving split.
    trendStableBand: 0.0003,
    // Enabled: LA data is in S3 and merging this PR redeploys the agent LA-aware
    // (city routing + city-aware find_restaurants). If a post-merge check shows LA
    // lookups returning "no record", the runtime role is missing s3:GetObject on
    // web-app-data/la/ (Issue #79 class, Deepak's account) — set back to false until fixed.
    chatSupported: true,
  },
};

export function isCity(v: unknown): v is City {
  return v === "chicago" || v === "nyc" || v === "la";
}

/** Resolve a data file URL for a city (e.g. dataUrl("nyc", "scores.json")).
 * `public/` assets are not auto-prefixed by Next's basePath, so we prepend
 * NEXT_PUBLIC_BASE_PATH ourselves — empty in prod (no-op), set only for the
 * local jupyter-proxy preview. */
export function dataUrl(city: City, file: string): string {
  const base = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
  return `${base}/data/${CITY_CONFIG[city].dataPrefix}${file}`;
}

/**
 * The detail page's location line: "address · area · City, ST ZIP".
 *
 * Only the parts that exist are joined, so a city that publishes no
 * neighborhood (Chicago) leaves no orphaned "·" separator.
 *
 * The area is placed by the city's `neighborhoodKind`:
 *   "within"   shown beside the city, because a NYC borough is inside New York.
 *   "locality" shown INSTEAD of the city, because LA County's feed names
 *              separate incorporated cities. Appending them to a fixed
 *              "Los Angeles, CA" read as "West Hollywood · Los Angeles, CA"
 *              (not where the venue is) and "Los Angeles · Los Angeles, CA".
 */
export function formatLocationLine(
  parts: { address: string; neighborhood: string; zip: string },
  city: City,
): string {
  const cfg = CITY_CONFIG[city];
  const address = parts.address.trim();
  const neighborhood = parts.neighborhood.trim();
  const zip = parts.zip.trim();

  const isLocality = cfg.neighborhoodKind === "locality" && neighborhood !== "";
  const place = isLocality ? `${neighborhood}, ${cfg.stateAbbrev}` : cfg.cityState;
  const cityLine = `${place}${zip ? ` ${zip}` : ""}`;

  return [address, isLocality ? "" : neighborhood, cityLine].filter(Boolean).join(" · ");
}
