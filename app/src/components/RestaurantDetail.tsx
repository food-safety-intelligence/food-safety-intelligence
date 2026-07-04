"use client";

import { ArrowLeft, Heart, MessageSquarePlus } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { DemoBanner } from "@/components/DemoBanner";
import { DriverList } from "@/components/DriverList";
import { InspectionTimeline } from "@/components/InspectionTimeline";
import { RegisterChatEstablishment } from "@/components/RegisterChatEstablishment";
import { ResultTally } from "@/components/ResultTally";
import { ScoreCard } from "@/components/ScoreCard";
import { Waterfall } from "@/components/Waterfall";
import type { DetailBundle, DetailGlobals } from "@/lib/scores";
import { formatInspectionDate } from "@/lib/utils";

type LoadState =
  | { status: "loading" }
  | { status: "notfound" }
  | { status: "ready"; bundle: DetailBundle; globals: DetailGlobals };

/**
 * Client-rendered detail page. The route is a single statically-exported shell
 * (`/restaurant/?id=`); this component reads the `id` and fetches that one
 * establishment's bundle + the shared globals from same-origin static JSON
 * (scripts/build-detail-data.mjs), so every establishment is reachable without
 * pre-rendering a page each.
 */
export function RestaurantDetail() {
  const id = useSearchParams().get("id");
  // No id → nothing to load; render not-found during render (not via an effect).
  // Key the loader on id so a new id remounts it back to the loading state,
  // keeping the effect's setState calls confined to async callbacks.
  if (!id) return <DetailNotFound />;
  return <DetailLoader key={id} id={id} />;
}

function DetailLoader({ id }: { id: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetch(`/data/detail/${encodeURIComponent(id)}.json`).then((r) =>
        r.ok ? (r.json() as Promise<DetailBundle>) : Promise.reject(r.status),
      ),
      fetch(`/data/detail-globals.json`).then((r) =>
        r.ok ? (r.json() as Promise<DetailGlobals>) : Promise.reject(r.status),
      ),
    ])
      .then(([bundle, globals]) => {
        if (!cancelled) setState({ status: "ready", bundle, globals });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "notfound" });
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (state.status === "loading") return <DetailSkeleton />;
  if (state.status === "notfound") return <DetailNotFound />;

  const { restaurant, history, comments } = state.bundle;
  const { is_mock, calibration, populationStats } = state.globals;

  // Attach each inspection's full comment text (index-aligned sidecar) so the
  // timeline can expand a row to show it.
  const historyWithComments = history.map((e, i) => ({
    ...e,
    comments: comments[i] ?? "",
  }));

  const lastInspection = history[0]?.date;

  // Location line — join only the parts we have so a missing neighborhood/zip
  // doesn't leave orphaned "·" separators.
  const cityLine = `Chicago, IL${restaurant.zip.trim() ? ` ${restaurant.zip.trim()}` : ""}`;
  const locationLine = [
    restaurant.address.trim(),
    restaurant.neighborhood.trim(),
    cityLine,
  ]
    .filter(Boolean)
    .join(" · ");

  const facilityType = restaurant.facility_type.trim();

  return (
    <>
      {/* Registers this establishment into the chat scope so the floating chat
          can answer "tell me about this restaurant" about it. Clears on unmount
          (navigating away). Renders nothing. */}
      <RegisterChatEstablishment
        licenseId={restaurant.license_id}
        name={restaurant.dba_name}
      />
      <div className="w-full max-w-[1240px] mx-auto px-8 mt-5">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-sm text-teal hover:underline"
        >
          <ArrowLeft className="w-3.5 h-3.5" strokeWidth={2.5} />
          Back to search
        </Link>
      </div>

      {is_mock && <DemoBanner />}

      {restaurant.is_out_of_business && (
        <div className="w-full max-w-[1240px] mx-auto px-8 mt-5">
          <div
            role="note"
            className="rounded-xl border border-line bg-tint px-5 py-3.5 text-sm text-ink"
          >
            <span className="font-semibold">
              This establishment appears to be out of business
            </span>
            {restaurant.closed_since && (
              <>
                {" "}
                — an inspector found it closed on{" "}
                {formatInspectionDate(restaurant.closed_since)}
              </>
            )}
            . The risk information below is historical, not a current signal.
          </div>
        </div>
      )}

      {/* max-w-full on mobile (capped to the viewport) so content wraps instead
          of forcing a horizontal scroll; overflow-x-clip trims any small residual
          overhang from intrinsic-width content (gauge, waterfall) without
          clipping text or the fixed term popover. Desktop keeps the 1240 cap. */}
      <main className="w-full max-w-full lg:max-w-[1240px] overflow-x-clip mx-auto px-8 pt-8 pb-24 flex-1">
        {/* Hero */}
        <section className="mb-10">
          <div className="mb-6">
            <p className="text-sage text-xs tracking-[0.18em] uppercase mb-3">
              Food establishment profile
            </p>
            <h1 className="text-6xl font-light leading-[1.04] tracking-tight">
              {restaurant.dba_name}
            </h1>
            <p className="text-lg text-muted mt-4 leading-relaxed">
              {locationLine}
            </p>
            <div className="flex flex-wrap gap-2 mt-4 items-center text-xs text-muted">
              <span className="px-2.5 py-1 rounded-full bg-tint">
                License #{restaurant.license_id}
              </span>
              {facilityType && (
                <span className="px-2.5 py-1 rounded-full bg-tint">
                  {facilityType}
                </span>
              )}
              {lastInspection && (
                <span className="px-2.5 py-1 rounded-full bg-tint">
                  Last inspected · {formatInspectionDate(lastInspection)}
                </span>
              )}
            </div>
          </div>

          <ScoreCard
            restaurant={restaurant}
            populationStats={populationStats}
            history={history}
          />
        </section>

        {/* Drivers */}
        <section className="mb-12">
          <div className="grid grid-cols-12 gap-8 items-end mb-6">
            <div className="col-span-12 lg:col-span-7">
              <p className="text-sage text-xs tracking-[0.18em] uppercase mb-3">
                What&apos;s driving the score
              </p>
              <h2 className="text-3xl font-light leading-tight tracking-tight">
                {restaurant.top_drivers.length === 1
                  ? "One factor is doing most of the work."
                  : `${restaurant.top_drivers.length} factors are doing most of the work.`}
              </h2>
              <p className="text-md text-muted leading-relaxed mt-3 max-w-[60ch]">
                The model attributes the score to the items below, sorted from
                most to least influential. Positive contributions push the score
                up; negative contributions push it down.
              </p>
            </div>
            <div className="col-span-12 lg:col-span-5 lg:text-right">
              <Link
                href="/how-it-works#definitions"
                className="inline-flex items-center gap-2 text-sm text-teal hover:underline"
              >
                Term definitions →
              </Link>
            </div>
          </div>

          <DriverList drivers={restaurant.top_drivers} />

          {/* How the score adds up — the same drivers as an additive,
              reconciling waterfall (calibrated log-odds). Only when the globals
              ship the calibration triple. */}
          {calibration && (
            <div className="mt-8">
              <div className="flex items-baseline justify-between gap-4 flex-wrap mb-3">
                <h3 className="text-xl font-medium tracking-tight">
                  How the score adds up
                </h3>
                <Link
                  href="/how-it-works#calibrated-log-odds"
                  className="text-sm text-teal hover:underline"
                >
                  What is calibrated log-odds?
                </Link>
              </div>
              <p className="text-base text-muted leading-relaxed mb-4 max-w-[60ch]">
                The same drivers as the bars above, rescaled to the model&apos;s
                calibrated scale so they add up — so the numbers here are smaller
                than the bars (which show raw influence and don&apos;t sum). The
                base, each driver, and everything else total one number, which a
                sigmoid turns into the probability on the gauge — so this column
                reconciles exactly with the score.
              </p>
              <Waterfall restaurant={restaurant} calibration={calibration} />
            </div>
          )}
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
              <p className="text-teal text-xs tracking-[0.18em] uppercase mb-2">
                A note for immunocompromised diners
              </p>
              <p className="text-lg leading-relaxed text-ink/90">
                Drivers tied to recurring violations or nearby pest complaints
                are the patterns your care team would most want you to consider.
                Administrative drivers like &quot;long since last inspection&quot;
                don&apos;t tell you about the kitchen itself.
              </p>
            </div>
          </div>
        </section>

        {/* History + sidebars */}
        <section className="mb-12">
          <div className="mb-6">
            <p className="text-sage text-xs tracking-[0.18em] uppercase mb-3">
              Inspection history
            </p>
            <h2 className="text-3xl font-light leading-tight tracking-tight">
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
            <p className="text-base text-muted leading-relaxed mt-3 max-w-[60ch]">
              Real Chicago Department of Public Health records, independent of the
              predicted risk score above.
            </p>
          </div>

          <div className="grid grid-cols-12 gap-6">
            <div className="col-span-12 md:col-span-7">
              <InspectionTimeline events={historyWithComments} />
            </div>

            <aside className="col-span-12 md:col-span-5 space-y-5">
              <ResultTally events={history} />
            </aside>
          </div>
        </section>

        {/* Caveat */}
        <section className="rounded-3xl bg-card border border-line soft-shadow p-8 mb-8">
          <p className="text-sage text-xs tracking-[0.18em] uppercase mb-3">
            A note on this score
          </p>
          <h3 className="text-2xl font-light leading-snug tracking-tight max-w-[40ch]">
            What this number is, and what it{" "}
            <span
              className="serif italic text-terra"
              style={{ fontSize: "1.08em" }}
            >
              isn&apos;t.
            </span>
          </h3>
          <div className="grid grid-cols-12 gap-6 mt-5 text-md text-ink/85 leading-[1.7]">
            <div className="col-span-12 md:col-span-6">
              <p className="font-medium mb-2">It is a prediction.</p>
              <p>
                A model estimate, drawn from the public record, of whether this
                establishment will fail an inspection or be cited for a priority
                violation in the next 180 days.
              </p>
            </div>
            <div className="col-span-12 md:col-span-6">
              <p className="font-medium mb-2">It is not a verdict.</p>
              <p>
                A &quot;{restaurant.risk_tier}&quot; prediction does not mean this
                food establishment is unsafe to eat at today. It means the
                patterns in the record resemble those that historically precede a
                failed inspection.
              </p>
            </div>
          </div>

          {/* Contextual feedback — carries this establishment's id + name to the
              feedback form so a data correction is tied to the right listing. */}
          <div className="mt-6 pt-5 border-t border-line flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <span className="text-muted">
              Something look wrong with this listing?
            </span>
            <Link
              href={`/feedback?venue=${encodeURIComponent(
                restaurant.license_id,
              )}&name=${encodeURIComponent(restaurant.dba_name)}`}
              className="inline-flex items-center gap-1.5 text-teal font-medium hover:underline"
            >
              <MessageSquarePlus className="w-4 h-4" strokeWidth={2} />
              Tell us
            </Link>
          </div>
        </section>

        <div className="text-center mt-10">
          <Link
            href="/"
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-ink text-cream text-base font-medium hover:bg-teal transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5" strokeWidth={2.5} />
            Back to search
          </Link>
        </div>
      </main>
    </>
  );
}

/** Shown while the bundle is fetching. Mirrors the main column width. */
function DetailSkeleton() {
  return (
    <main className="w-full max-w-[1240px] mx-auto px-8 pt-16 pb-24 flex-1">
      <div className="animate-pulse space-y-6" aria-busy="true" aria-live="polite">
        <span className="sr-only">Loading establishment details…</span>
        <div className="h-4 w-40 rounded bg-line" />
        <div className="h-14 w-2/3 rounded bg-line" />
        <div className="h-5 w-1/3 rounded bg-line" />
        <div className="h-64 w-full rounded-3xl bg-line/60" />
        <div className="h-40 w-full rounded-3xl bg-line/60" />
      </div>
    </main>
  );
}

/** Shown when the id is missing or its bundle doesn't exist. */
function DetailNotFound() {
  return (
    <main className="w-full max-w-[1240px] mx-auto px-8 pt-24 pb-24 flex-1 text-center">
      <h1 className="text-3xl font-light tracking-tight mb-3">
        Establishment not found
      </h1>
      <p className="text-muted mb-8 max-w-[48ch] mx-auto leading-relaxed">
        We couldn&apos;t find a food establishment for this link. It may have been
        removed from the dataset, or the link may be incomplete.
      </p>
      <Link
        href="/"
        className="inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-ink text-cream text-base font-medium hover:bg-teal transition-colors"
      >
        <ArrowLeft className="w-3.5 h-3.5" strokeWidth={2.5} />
        Back to search
      </Link>
    </main>
  );
}
