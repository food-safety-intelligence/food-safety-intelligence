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

/** Just the dataset names for a city (footer, prose fallbacks). */
export function sourceNames(city: City): string[] {
  return SOURCES_BY_CITY[city].map((s) => s.name);
}
