"use client";

// Per-city Sources list (DR 0016). The /sources page shows the datasets behind the
// selected city's scores — Chicago at the root, NYC/LA as added cities — read from
// the client-side city context so it tracks the same ?city= / picker the rest of
// the app uses. Data governance (how-it-works §5) links here rather than re-listing.

import { ExternalLink } from "lucide-react";
import { useCity } from "@/components/CityContext";
import { CITY_CONFIG, type City } from "@/lib/city";

interface Source {
  name: string;
  href: string;
  summary: string;
}

const SOURCES_BY_CITY: Record<City, Source[]> = {
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

export function SourcesList() {
  const { city } = useCity();
  const c = CITY_CONFIG[city];
  const sources = SOURCES_BY_CITY[city];

  return (
    <>
      <header className="mt-6">
        <p className="text-sage text-xs tracking-[0.18em] uppercase mb-3">Sources</p>
        <h1 className="text-5xl font-light leading-[1.05] tracking-tight">Public data, attributed.</h1>
        <p className="text-lg text-muted leading-[1.65] mt-5 max-w-[58ch]">
          Every score for <strong className="text-ink font-medium">{c.label}</strong>{" "}
          is computed from the public datasets below. We don&apos;t scrape, buy, or combine private data, and
          the app collects nothing from the people who visit it.
        </p>
      </header>

      <section className="mt-10 space-y-4">
        {sources.map((s) => (
          <a
            key={s.href}
            href={s.href}
            target="_blank"
            rel="noopener noreferrer"
            className="block rounded-3xl bg-card border border-line p-6 soft-shadow hover:border-teal/40 transition-colors"
          >
            <div className="flex items-start justify-between gap-4">
              <h2 className="text-xl font-medium tracking-tight">{s.name}</h2>
              <ExternalLink className="w-4 h-4 text-muted shrink-0 mt-1" strokeWidth={2} />
            </div>
            <p className="text-base text-muted leading-relaxed mt-2">{s.summary}</p>
          </a>
        ))}
      </section>

      <section className="mt-10 rounded-3xl bg-tint border border-line p-6">
        <p className="text-teal text-xs tracking-[0.18em] uppercase mb-2">Refresh cadence</p>
        <p className="text-md text-ink/85 leading-relaxed">
          Scores are computed on a fixed snapshot and published as static JSON. The detail page
          shows each establishment&apos;s &ldquo;as of&rdquo; date. A scheduled incremental refresh
          is on the roadmap. See how the data is handled under{" "}
          <a href="/how-it-works#data-governance" className="text-teal hover:underline">Data governance</a>.
        </p>
      </section>
    </>
  );
}
