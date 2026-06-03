import { ArrowLeft, ExternalLink } from "lucide-react";
import Link from "next/link";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";

export const metadata = {
  title: "Sources · Food Safety",
  description: "Public datasets behind every score on this site.",
};

const SOURCES = [
  {
    name: "Chicago Food Inspections",
    href: "https://data.cityofchicago.org/Health-Human-Services/Food-Inspections/4ijn-s7e5",
    summary:
      "Every restaurant inspection conducted by Chicago Department of Public Health since 2010. Used for both labels and most of the prior-history features.",
  },
  {
    name: "Chicago 311 Service Requests",
    href: "https://data.cityofchicago.org/Service-Requests/311-Service-Requests/v6vf-nfxy",
    summary:
      "All 311 requests since 2018. We filter to eight food-relevant request types (rodent, garbage carts, sanitation code violations, etc.) and join by spatial proximity to the establishment.",
  },
  {
    name: "Chicago Business Licenses (current)",
    href: "https://data.cityofchicago.org/Community-Economic-Development/Business-Licenses-Current-Active/uupf-x98q",
    summary:
      "Active food licenses — used to pull facility type, risk tier, address, and license-age features.",
  },
  {
    name: "Chicago Business Licenses (historical)",
    href: "https://data.cityofchicago.org/Community-Economic-Development/Business-Licenses/r5kz-chrr",
    summary:
      "Full license history — used to compute license_age_days and license_n_history_rows features.",
  },
];

export default function SourcesPage() {
  return (
    <>
      <SiteHeader activeNav="sources" />

      <main className="max-w-[820px] mx-auto px-8 pt-10 pb-24 flex-1">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-[13px] text-teal hover:underline"
        >
          <ArrowLeft className="w-3.5 h-3.5" strokeWidth={2.5} />
          Back to search
        </Link>

        <header className="mt-6">
          <p className="text-sage text-[12.5px] tracking-[0.18em] uppercase mb-3">
            Sources
          </p>
          <h1 className="text-[3rem] font-light leading-[1.05] tracking-tight">
            Public data, attributed.
          </h1>
          <p className="text-[17px] text-muted leading-[1.65] mt-5 max-w-[58ch]">
            Every score on this site is computed from datasets published by
            the City of Chicago on its Open Data Portal. We don&apos;t scrape,
            buy, or combine private data.
          </p>
        </header>

        <section className="mt-10 space-y-4">
          {SOURCES.map((s) => (
            <a
              key={s.href}
              href={s.href}
              target="_blank"
              rel="noopener noreferrer"
              className="block rounded-3xl bg-card border border-line p-6 soft-shadow hover:border-teal/40 transition-colors"
            >
              <div className="flex items-start justify-between gap-4">
                <h2 className="text-[1.25rem] font-medium tracking-tight">
                  {s.name}
                </h2>
                <ExternalLink
                  className="w-4 h-4 text-muted shrink-0 mt-1"
                  strokeWidth={2}
                />
              </div>
              <p className="text-[14.5px] text-muted leading-relaxed mt-2">
                {s.summary}
              </p>
            </a>
          ))}
        </section>

        <section className="mt-10 rounded-3xl bg-tint border border-line p-6">
          <p className="text-teal text-[12.5px] tracking-[0.18em] uppercase mb-2">
            Refresh cadence
          </p>
          <p className="text-[15px] text-ink/85 leading-relaxed">
            The model is currently scored on a fixed snapshot of the data. A
            scheduled incremental refresh (daily pulls of new inspection /
            complaint / license records) is on the roadmap; the SODA loader
            already uses cursor-based pagination so it can resume from a stored
            watermark without re-pulling the world.
          </p>
        </section>
      </main>

      <SiteFooter />
    </>
  );
}
