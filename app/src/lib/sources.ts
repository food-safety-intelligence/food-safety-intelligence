/**
 * The datasets behind each city's scores — the single source of truth.
 *
 * Both the /sources page (SourcesList) and the site footer read this list, so the
 * two can't drift apart. They previously kept separate copies, which is how LA
 * ended up listing two datasets on /sources but only one in the footer.
 */

import type { City } from "@/lib/city";

export interface Source {
  name: string;
  href: string;
  summary: string;
}

export const SOURCES_BY_CITY: Record<City, Source[]> = {
  chicago: [
    {
      name: "Chicago Food Inspections",
      href: "https://data.cityofchicago.org/Health-Human-Services/Food-Inspections/4ijn-s7e5",
      summary:
        "Every food establishment inspection the Chicago Department of Public Health has conducted since 2010. Used for both the label and most prior-history features.",
    },
    {
      name: "Chicago Business Licenses (current + historical)",
      href: "https://data.cityofchicago.org/Community-Economic-Development/Business-Licenses-Current-Active/uupf-x98q",
      summary:
        "Active + full license history: facility type, risk tier, address, and license-age features.",
    },
  ],
  nyc: [
    {
      name: "NYC DOHMH Restaurant Inspection Results",
      href: "https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j",
      summary:
        "Every restaurant inspection the NYC Health Department conducts, each carrying an A / B / C letter grade (a threshold on the violation-point score). Used for the label and prior-history features on the post-COVID (2022+) window.",
    },
  ],
  la: [
    {
      name: "LA County Restaurant and Market Inspections",
      href: "https://data.lacounty.gov/datasets/19b6607ac82c4512b10811870975dbdc",
      summary:
        "LA County Environmental Health restaurant + market inspections, 2023–2026, each carrying an A / B / C grade on a 0–100 scale (higher is cleaner). Used for the label and prior-history features. Published as a bulk CSV on ArcGIS Hub (LA County left Socrata).",
    },
    {
      name: "LA County Restaurant and Market Violations",
      href: "https://data.lacounty.gov/datasets/5eaea9f89b7549ee841da7617d3a9cba",
      summary:
        "Per-violation records joined to inspections on serial number: the source for the shared violation dictionary's theme and severity-tier features.",
    },
  ],
};

/**
 * Datasets used ONLY to audit fairness, never to compute a score.
 *
 * Deliberately kept out of SOURCES_BY_CITY (and out of the footer): those are the
 * inputs a score is computed from, and listing census data beside them would imply
 * demographics feed the model. They don't. The join happens after the model runs,
 * purely to measure whether predictions land unevenly across groups.
 */
export const AUDIT_ONLY_SOURCES: Source[] = [
  {
    name: "US Census Bureau, American Community Survey (5-year)",
    href: "https://www.census.gov/programs-surveys/acs",
    summary:
      "Neighborhood-level demographics (income, race and ethnicity, poverty, country of birth, language). Matched to an establishment's location only after the model has produced a score, to check whether the model's flags and errors fall unevenly across groups. No demographic value is ever a model input.",
  },
  {
    name: "US Census Bureau, TIGER/Line census tracts",
    href: "https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html",
    summary:
      "The tract boundaries used to match an establishment's coordinates to its census tract for that audit.",
  },
];

/** Just the dataset names for a city (footer, prose fallbacks). Scoring sources only. */
export function sourceNames(city: City): string[] {
  return SOURCES_BY_CITY[city].map((s) => s.name);
}
