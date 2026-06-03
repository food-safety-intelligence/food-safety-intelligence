import { ArrowLeft, Heart } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { DemoBanner } from "@/components/DemoBanner";
import { DriverList } from "@/components/DriverList";
import {
  InspectionTimeline,
  ResultTally,
} from "@/components/InspectionTimeline";
import { ScoreCard } from "@/components/ScoreCard";
import { SiteFooter } from "@/components/SiteFooter";
import { SiteHeader } from "@/components/SiteHeader";
import {
  getInspectionHistory,
  getPopulationStats,
  getRestaurant,
  loadScores,
} from "@/lib/scores-server";
import { formatInspectionDate } from "@/lib/utils";

// In Next.js 16 with the App Router, `params` is a Promise that must be awaited.
// See node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/page.md.
export default async function RestaurantDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  const [restaurant, history, payload, populationStats] = await Promise.all([
    getRestaurant(id),
    getInspectionHistory(id),
    loadScores(),
    getPopulationStats(),
  ]);

  if (!restaurant) notFound();

  const lastInspection = history[0]?.date;

  return (
    <>
      <SiteHeader activeNav="search" />

      <div className="max-w-[1240px] mx-auto px-8 mt-5">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-[13px] text-teal hover:underline"
        >
          <ArrowLeft className="w-3.5 h-3.5" strokeWidth={2.5} />
          Back to search
        </Link>
      </div>

      {payload.is_mock && <DemoBanner />}

      <main className="max-w-[1240px] mx-auto px-8 pt-8 pb-24 flex-1">
        {/* Hero */}
        <section className="grid grid-cols-12 gap-8 mb-10">
          <div className="col-span-12 lg:col-span-7">
            <p className="text-sage text-[12.5px] tracking-[0.18em] uppercase mb-3">
              Restaurant profile
            </p>
            <h1 className="text-[3.4rem] font-light leading-[1.04] tracking-tight">
              {restaurant.dba_name}
            </h1>
            <p className="text-[16px] text-muted mt-4 leading-relaxed">
              {restaurant.address} &nbsp;·&nbsp; {restaurant.neighborhood}{" "}
              &nbsp;·&nbsp; Chicago, IL {restaurant.zip}
            </p>
            <div className="flex flex-wrap gap-2 mt-4 items-center text-[12px] text-muted">
              <span className="px-2.5 py-1 rounded-full bg-tint">
                License #{restaurant.license_id}
              </span>
              <span className="px-2.5 py-1 rounded-full bg-tint">
                {restaurant.facility_type}
              </span>
              {lastInspection && (
                <span className="px-2.5 py-1 rounded-full bg-tint">
                  Last inspected · {formatInspectionDate(lastInspection)}
                </span>
              )}
            </div>
          </div>

          <div className="col-span-12 lg:col-span-5">
            <ScoreCard
              restaurant={restaurant}
              populationStats={populationStats}
            />
          </div>
        </section>

        {/* Drivers */}
        <section className="mb-12">
          <div className="grid grid-cols-12 gap-8 items-end mb-6">
            <div className="col-span-12 lg:col-span-7">
              <p className="text-sage text-[12.5px] tracking-[0.18em] uppercase mb-3">
                What&apos;s driving the score
              </p>
              <h2 className="text-[2rem] font-light leading-tight tracking-tight">
                {restaurant.top_drivers.length === 1
                  ? "One factor is doing most of the work."
                  : `${
                      restaurant.top_drivers.length
                    } factors are doing most of the work.`}
              </h2>
              <p className="text-[15px] text-muted leading-relaxed mt-3 max-w-[60ch]">
                The model attributes the score to the items below, sorted from
                most to least influential. Positive contributions push the
                score up; negative contributions push it down.
              </p>
            </div>
            <div className="col-span-12 lg:col-span-5 lg:text-right">
              <Link
                href="/how-it-works#priority-violations"
                className="inline-flex items-center gap-2 text-[13px] text-teal hover:underline"
              >
                What is a priority violation?
              </Link>
            </div>
          </div>

          <DriverList drivers={restaurant.top_drivers} />
        </section>

        {/* Caregiver note */}
        <section className="mb-12">
          <div className="rounded-3xl bg-tint border border-line p-7 grid grid-cols-12 gap-6 items-start">
            <div className="col-span-12 md:col-span-2">
              <span className="inline-flex w-12 h-12 rounded-2xl bg-card items-center justify-center soft-shadow">
                <Heart className="w-[22px] h-[22px] text-teal" strokeWidth={1.8} />
              </span>
            </div>
            <div className="col-span-12 md:col-span-10">
              <p className="text-teal text-[12.5px] tracking-[0.18em] uppercase mb-2">
                A note for immunocompromised diners
              </p>
              <p className="text-[16.5px] leading-relaxed text-ink/90">
                Drivers tied to recurring violations or nearby pest complaints
                are the patterns your care team would most want you to
                consider. Administrative drivers like &quot;long since last
                inspection&quot; don&apos;t tell you about the kitchen itself.
              </p>
            </div>
          </div>
        </section>

        {/* History + sidebars */}
        <section className="mb-12">
          <div className="mb-6">
            <p className="text-sage text-[12.5px] tracking-[0.18em] uppercase mb-3">
              Inspection history
            </p>
            <h2 className="text-[2rem] font-light leading-tight tracking-tight">
              {history.length} inspection{history.length === 1 ? "" : "s"} on
              record.{" "}
              <span
                className="serif italic text-terra"
                style={{ fontSize: "1.05em" }}
              >
                {history.filter((e) => e.result === "Fail").length} failure
                {history.filter((e) => e.result === "Fail").length === 1
                  ? ""
                  : "s"}
                .
              </span>
            </h2>
            <p className="text-[14.5px] text-muted leading-relaxed mt-3 max-w-[60ch]">
              Real Chicago Department of Public Health records, independent of
              the predicted risk score above.
            </p>
          </div>

          <div className="grid grid-cols-12 gap-6">
            <div className="col-span-12 md:col-span-7">
              <InspectionTimeline events={history} />
            </div>

            <aside className="col-span-12 md:col-span-5 space-y-5">
              <ResultTally events={history} />
            </aside>
          </div>
        </section>

        {/* Caveat */}
        <section className="rounded-3xl bg-card border border-line soft-shadow p-8 mb-8">
          <p className="text-sage text-[12.5px] tracking-[0.18em] uppercase mb-3">
            A note on this score
          </p>
          <h3 className="text-[1.6rem] font-light leading-snug tracking-tight max-w-[40ch]">
            What this number is, and what it{" "}
            <span
              className="serif italic text-terra"
              style={{ fontSize: "1.08em" }}
            >
              isn&apos;t.
            </span>
          </h3>
          <div className="grid grid-cols-12 gap-6 mt-5 text-[15px] text-ink/85 leading-[1.7]">
            <div className="col-span-12 md:col-span-6">
              <p className="font-medium mb-2">It is a prediction.</p>
              <p>
                A model estimate, drawn from the public record, of whether this
                establishment will fail an inspection or be cited for a
                priority violation in the next 180 days.
              </p>
            </div>
            <div className="col-span-12 md:col-span-6">
              <p className="font-medium mb-2">It is not a verdict.</p>
              <p>
                A &quot;{restaurant.risk_tier}&quot; prediction does not mean
                this restaurant is unsafe to eat at today. It means the
                patterns in the record resemble those that historically precede
                a failed inspection.
              </p>
            </div>
          </div>
        </section>

        <div className="text-center mt-10">
          <Link
            href="/"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-ink text-cream text-[14px] font-medium hover:bg-teal transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" strokeWidth={2.5} />
            Back to search
          </Link>
        </div>
      </main>

      <SiteFooter />
    </>
  );
}
