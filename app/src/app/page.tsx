import { ArrowRight, Heart } from "lucide-react";
import Link from "next/link";
import type { PinDriver } from "@/lib/scores";
import { getMapPins, loadScores } from "@/lib/scores-server";
import { DemoBanner } from "@/components/DemoBanner";
import { MapExplorer } from "@/components/MapExplorer";
import { PinDriverLine } from "@/components/MapView";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";

// Iteration-speed knob — see comment history in scores-server.ts. The
// floating search is still in-memory client-side; the cap controls how big
// the RSC payload is. Bump to 1000+ once we add `?q=` server-side search.
const HOME_LIMIT = 200;

// Illustrative only — a static preview of what "the top drivers" look like, so
// the caregivers promise ("we show the top three drivers") is concrete on the
// home page. Not tied to any real establishment; each place's actual, signed
// drivers live on its detail page. Uses real feature keys so the icons match.
const ILLUSTRATIVE_DRIVERS: PinDriver[] = [
  { feature: "flag_kw_temperature", label: "Recurring temperature violations", up: true },
  { feature: "flag_kw_pest", label: "Recent pest activity noted", up: true },
  { feature: "days_since_last_inspection", label: "Long gap since last inspection", up: true },
];

export default async function HomePage() {
  const [payload, pins] = await Promise.all([loadScores(), getMapPins()]);

  const visibleScores = payload.scores
    .slice()
    .sort((a, b) => b.risk_score - a.risk_score)
    .slice(0, HOME_LIMIT);

  return (
    <>
      <SiteHeader activeNav="search" />
      {payload.is_mock && <DemoBanner />}

      {/* MAP-FIRST viewport — the design's "Chicago Safety Map" screen. */}
      <main className="flex-1 flex flex-col pt-4">
        <MapExplorer
          scores={visibleScores}
          pins={pins}
          tierCounts={payload.totals.tier_counts}
          totalEstablishments={payload.totals.establishments}
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
                reasons.
                We show the top three drivers — recurring temperature
                violations, nearby pest complaints, long gaps since last
                inspection — so you can match the data to the precautions your
                care team recommends.
              </p>
            </div>
            <div className="col-span-12 md:col-span-5 flex flex-col gap-4 md:items-end">
              {/* Illustrative driver preview — makes the "top three drivers"
                  promise above concrete. Reuses the same driver row as the map
                  list/popup for visual consistency. */}
              <div className="w-full md:max-w-[320px] rounded-2xl border border-line bg-card/80 p-4">
                <div className="text-[11px] tracking-widest uppercase text-muted mb-2.5">
                  Illustrative drivers
                </div>
                <div className="space-y-2">
                  {ILLUSTRATIVE_DRIVERS.map((d) => (
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
        </section>

        <div className="pb-16" />
      </main>

      <SiteFooter />
    </>
  );
}
