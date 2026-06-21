import { ArrowRight, Heart } from "lucide-react";
import Link from "next/link";
import { getHomeView, loadScores } from "@/lib/scores-server";
import { parseTiers, type HomeSort, type PinDriver } from "@/lib/scores";
import { DemoBanner } from "@/components/DemoBanner";
import { MapExplorer } from "@/components/MapExplorer";
import { PinDriverLine } from "@/components/MapView";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";

// The home list is capped for payload size; search/sort/filters narrow the
// full population server-side (see getHomeView), so the cap never hides a
// match — it only bounds the no-query "highest-risk" preview.
const HOME_LIMIT = 200;

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

export default async function HomePage({
  searchParams,
}: {
  // Next 16: searchParams is async.
  searchParams: Promise<{ q?: string; tier?: string; sort?: string }>;
}) {
  const sp = await searchParams;
  const query = (sp.q ?? "").trim();
  const sort: HomeSort = sp.sort === "name" ? "name" : "risk";
  const tiers = parseTiers(sp.tier);

  const [payload, view] = await Promise.all([
    loadScores(),
    getHomeView({ q: query, tiers, sort, listLimit: HOME_LIMIT }),
  ]);

  return (
    <>
      <SiteHeader activeNav="search" />
      {payload.is_mock && <DemoBanner />}

      {/* MAP-FIRST viewport — the design's "Chicago Safety Map" screen. */}
      <main className="flex-1 flex flex-col pt-4">
        <MapExplorer
          view={view}
          query={query}
          sort={sort}
          activeTiers={tiers}
        />

        {/* Below-the-fold supplementary content. Map-first means scroll for the rest. */}
        <section className="max-w-[1240px] mx-auto px-8 mt-16 w-full">
          <div className="grid grid-cols-12 gap-6 items-end">
            <div className="col-span-12 lg:col-span-7">
              <p className="text-sage text-[12.5px] tracking-[0.18em] uppercase mb-3">
                A risk signal, not a verdict
              </p>
              <h2 className="text-[2.4rem] font-light tracking-tight leading-[1.1]">
                Why this exists
              </h2>
              <p className="text-[16px] text-muted leading-[1.6] mt-4 max-w-[58ch]">
                Chicago publishes every food establishment inspection it
                conducts. We
                pair that record with nearby 311 complaints and license
                history to estimate the chance a place will see a failed
                inspection or priority violation in the next six months — and
                show you exactly why.
              </p>
            </div>
            <div className="col-span-12 lg:col-span-5 grid grid-cols-2 gap-3">
              <div className="rounded-2xl bg-card p-5 soft-shadow border border-line">
                <div className="text-[11px] tracking-widest uppercase text-muted">
                  In the index
                </div>
                <div className="num text-[28px] font-medium mt-1 leading-none">
                  {payload.totals.establishments.toLocaleString()}
                </div>
                <div className="text-[12px] text-muted mt-1">
                  licensed establishments
                </div>
              </div>
              <div className="rounded-2xl bg-card p-5 soft-shadow border border-line">
                <div className="text-[11px] tracking-widest uppercase text-muted">
                  High tier today
                </div>
                <div className="num text-[28px] font-medium mt-1 leading-none text-terra">
                  {payload.totals.tier_counts.High.toLocaleString()}
                </div>
                <div className="text-[12px] text-muted mt-1">
                  {(
                    (payload.totals.tier_counts.High /
                      payload.totals.establishments) *
                    100
                  ).toFixed(1)}
                  % of all licenses
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="max-w-[1240px] mx-auto px-8 mt-12 w-full">
          <div className="rounded-3xl bg-tint border border-line p-8 grid grid-cols-12 gap-6 items-center">
            <div className="col-span-12 md:col-span-7">
              <p className="text-sage text-[12.5px] tracking-[0.18em] uppercase mb-3 flex items-center gap-2">
                <Heart className="w-3.5 h-3.5" strokeWidth={2} />
                For caregivers
              </p>
              <h3 className="text-[1.75rem] tracking-tight leading-tight">
                If you&apos;re choosing for someone with{" "}
                <span
                  className="serif italic text-terra"
                  style={{ fontSize: "1.05em" }}
                >
                  compromised immunity,
                </span>{" "}
                the drivers matter more than the score.
              </h3>
              <p className="text-[14.5px] text-muted leading-relaxed mt-3 max-w-[60ch]">
                Two food establishments can share the same score for different
                reasons — and for someone with a weakened immune system, the
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
                  <div className="text-[11px] tracking-widest uppercase text-muted mb-2.5">
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
                  className="inline-flex items-center gap-2 px-5 py-3 rounded-full bg-ink text-cream text-[14px] font-medium hover:bg-teal transition-colors"
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
