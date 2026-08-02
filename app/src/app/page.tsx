import { ArrowRight, Heart } from "lucide-react";
import Link from "next/link";
import { getHomeView, loadScores } from "@/lib/scores-server";
import { ALL_TIERS, type HomeSort, type PinDriver } from "@/lib/scores";
import { CityIntro } from "@/components/CityIntro";
import { DemoBanner } from "@/components/DemoBanner";
import { MapExplorer } from "@/components/MapExplorer";
import { PinDriverLine } from "@/components/MapView";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";

// One list cap for every mode (highest/lowest risk, A–Z, search) — kept
// consistent and bounded; the list reveals 100 rows at a time via "show more".
const LIST_LIMIT = 500;

// A static, generic example of the kind of drivers the model surfaces, so the
// caregivers promise ("we show the top three drivers") is concrete on the home
// page. These are REAL model features (keyword flags the model actually uses),
// shown as an example rather than pulled from one establishment — each place's
// actual, signed drivers live on its detail page.
//
// Chosen to be the hazards that matter most for an immunocompromised diner —
// the classic foodborne-pathogen routes (temperature abuse, cross-contamination,
// handwashing) rather than generic operational signals.
const EXAMPLE_DRIVERS: PinDriver[] = [
  { feature: "flag_kw_temperature", label: "Temperature abuse (bacterial growth)", up: true },
  { feature: "flag_kw_cross_contamination", label: "Cross-contamination risk", up: true },
  { feature: "flag_kw_handwash_sink", label: "Handwashing lapses", up: true },
];

// `output: "export"` pre-renders this page once at build time, so we can't
// read URL params here. Server renders the default unfiltered view; the
// client (MapExplorer) handles search/sort/tier via its own state. URL-driven
// filter persistence is a follow-up — see Scope B in the deploy plan.
const DEFAULT_QUERY = "";
const DEFAULT_SORT: HomeSort = "risk";
const DEFAULT_TIERS = ALL_TIERS;

export default async function HomePage() {
  const [payload, view] = await Promise.all([
    loadScores(),
    getHomeView({
      q: DEFAULT_QUERY,
      tiers: DEFAULT_TIERS,
      sort: DEFAULT_SORT,
      listLimit: LIST_LIMIT,
    }),
  ]);

  return (
    <>
      <SiteHeader activeNav="search" />
      {payload.is_mock && <DemoBanner />}

      {/* MAP-FIRST viewport — the design's "Chicago Safety Map" screen.
          overflow-x-clip guards against a few px of horizontal overflow on very
          narrow screens (≤320px); vertical scroll is unaffected. */}
      <main className="flex-1 flex flex-col pt-4 overflow-x-clip">
        {/* Server renders this default (unfiltered) view for the first paint;
            MapExplorer then fetches the search index and filters per the URL
            client-side, so search/sort/filter and shareable `/?q=` links work
            on the statically-exported page. */}
        <MapExplorer initialView={view} />

        {/* Below-the-fold supplementary content. Map-first means scroll for the rest. */}
        <section className="max-w-[1240px] mx-auto px-8 mt-16 w-full">
          <CityIntro
            initialTotals={{
              establishments: payload.totals.establishments,
              high: payload.totals.tier_counts.High,
            }}
          />
        </section>

        <section className="max-w-[1240px] mx-auto px-8 mt-12 w-full">
          <div className="rounded-3xl bg-tint border border-line p-8 grid grid-cols-12 gap-6 items-center">
            <div className="col-span-12 md:col-span-7">
              <p className="text-sage text-xs tracking-[0.18em] uppercase mb-3 flex items-center gap-2">
                <Heart className="w-3.5 h-3.5" strokeWidth={2} />
                For caregivers
              </p>
              <h3 className="text-3xl tracking-tight leading-tight">
                If you&apos;re choosing for someone with{" "}
                <span
                  className="serif italic text-terra"
                  style={{ fontSize: "1.05em" }}
                >
                  compromised immunity,
                </span>{" "}
                the drivers matter more than the score.
              </h3>
              <p className="text-base text-muted leading-relaxed mt-3 max-w-[60ch]">
                Two food establishments can share the same score for different
                reasons, and for someone with a weakened immune system, the
                reason matters. We surface the top drivers, like temperature
                abuse, cross-contamination, and handwashing lapses, so you can
                match the data to the precautions your care team recommends.
              </p>
            </div>
            <div className="col-span-12 md:col-span-5">
              {/* Example driver preview + its CTA as one unit: a 320px group,
                  right-aligned in the column on desktop, with the button centered
                  under the card. */}
              <div className="md:ml-auto md:max-w-[320px] flex flex-col items-center gap-4">
                <div className="w-full rounded-2xl border border-line bg-card/80 p-4">
                  <div className="text-2xs tracking-widest uppercase text-muted mb-2.5">
                    Example drivers
                  </div>
                  <div className="space-y-2">
                    {EXAMPLE_DRIVERS.map((d) => (
                      <PinDriverLine key={d.feature} driver={d} />
                    ))}
                  </div>
                </div>
                <Link
                  href="/caregivers"
                  className="inline-flex items-center gap-2 px-5 py-3 rounded-full bg-ink text-cream text-base font-medium hover:bg-teal transition-colors"
                >
                  Open the caregiver guide
                  <ArrowRight className="w-3.5 h-3.5" strokeWidth={2.5} />
                </Link>
              </div>
            </div>
          </div>
        </section>

        <div className="pb-16" />
      </main>

      <SiteFooter />
    </>
  );
}
