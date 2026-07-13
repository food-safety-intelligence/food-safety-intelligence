"use client";

import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  TrendingUp,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { BackToSearch } from "@/components/BackToSearch";
import { useCity } from "@/components/CityContext";
import { MapView } from "@/components/MapView";
import { TierPill } from "@/components/TierPill";
import { TrendIndicator } from "@/components/TrendIndicator";
import { CITY_CONFIG, type City, dataUrl } from "@/lib/city";
import { fetchJson } from "@/lib/fetch-json";
import { iconForFeature } from "@/lib/driver-icons";
import type {
  DetailBundle,
  PinSummary,
  RiskTier,
  SearchIndex,
  SearchIndexRow,
} from "@/lib/scores";
import {
  ALL_TIERS,
  hasCoords,
  isAllTiers,
  parseTiers,
  TIER_HEX,
} from "@/lib/scores";
import { cn, formatInspectionDate } from "@/lib/utils";
import {
  bitsForSlugs,
  matchesViolations,
  parseViol,
  VIOLATION_CATEGORIES,
} from "@/lib/violations";

/**
 * "For inspectors" — a model-ranked inspection worklist (design handoff:
 * design/design_handoff_for_inspectors/). Reframes the batch risk scores as a
 * priority queue with tier filtering, three sorts, expandable rows (drivers +
 * inspection history, lazy-fetched per license), a model-lift explainer, a
 * "Rising fast" watch list and a client-state "Today's route" builder.
 *
 * Data: entirely derived from the slim search index (fetched once, like
 * MapExplorer) + per-license DetailBundles fetched on first expand. No new
 * pipeline output; no request-time model calls.
 */

type InspectorSort = "risk" | "overdue" | "trend";

function parseInspectorSort(raw: string | null): InspectorSort {
  return raw === "overdue" ? "overdue" : raw === "trend" ? "trend" : "risk";
}

type WorklistView = "list" | "map";

function parseWorklistView(raw: string | null): WorklistView {
  return raw === "map" ? "map" : "list";
}

const SORTS: { key: InspectorSort; label: string }[] = [
  { key: "risk", label: "Highest risk" },
  { key: "overdue", label: "Most overdue" },
  { key: "trend", label: "Worsening fastest" },
];

/** Days since the latest scored inspection beyond which a row is "Overdue". */
const OVERDUE_DAYS = 300;
/** Rows revealed initially / added per "Show more" click. */
const QUEUE_PAGE = 50;

function daysSince(iso: string | null | undefined, now: number): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.floor((now - t) / 86_400_000));
}

/** Just the fields the "Why trust this ranking" card reads from the active
 *  city's methodology.json — the same file the How-it-works page renders, so
 *  the two pages can't drift. Extra fields in the JSON are ignored. Declared
 *  locally (not imported from methodology-server) because that loader is
 *  server-only; the How-it-works city components fetch client-side the same way. */
interface WorklistMethodology {
  test: { prevalence: number };
  headline: { top_decile_lift: number };
  operating_points: { frac: number; precision: number; lift: number }[];
}

export function InspectorWorklist() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  // URL is the source of truth for tier/sort (shareable, same pattern as the
  // home page). Route + expanded state are session-local by design.
  // Memoized on the raw param so the React Compiler can rely on identity.
  const tierParam = searchParams.get("tier") ?? undefined;
  const activeTiers = useMemo(() => parseTiers(tierParam), [tierParam]);
  const sort = parseInspectorSort(searchParams.get("sort"));

  // Violation-category filter, URL-driven like tier/sort. Memoized on the raw
  // param (same React Compiler pattern as activeTiers). bits=0 → no filter.
  const violParam = searchParams.get("viol") ?? undefined;
  const activeViol = useMemo(() => parseViol(violParam), [violParam]);
  const violBits = bitsForSlugs(activeViol);

  const view = parseWorklistView(searchParams.get("view"));

  // City-scoped data — the header's CityToggle switches it. Expanded rows and
  // the route reset with the city (license ids are per-city).
  const { city } = useCity();
  const cfg = CITY_CONFIG[city];
  const [index, setIndex] = useState<SearchIndex | null>(null);
  const [meth, setMeth] = useState<WorklistMethodology | null>(null);
  const [failed, setFailed] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [route, setRoute] = useState<string[]>([]);
  const [visibleCount, setVisibleCount] = useState(QUEUE_PAGE);

  // Reset the city-scoped state when the city changes — adjust-state-during-
  // render (React's recommended alternative to a reset effect; same pattern as
  // MapExplorer's resultKey), so no cascading-render lint error.
  const [prevCity, setPrevCity] = useState(city);
  if (city !== prevCity) {
    setPrevCity(city);
    setIndex(null);
    setMeth(null);
    setFailed(false);
    setExpanded({});
    setRoute([]);
    setVisibleCount(QUEUE_PAGE);
  }

  useEffect(() => {
    const controller = new AbortController();
    fetchJson<SearchIndex>(dataUrl(city, "search-index.json"), {
      signal: controller.signal,
    })
      .then((d) => setIndex(d))
      .catch(() => {
        // A transient blip on the multi-MB index is retried inside fetchJson;
        // only a genuine, retries-exhausted failure marks the worklist failed.
        if (!controller.signal.aborted) setFailed(true);
      });
    return () => controller.abort();
  }, [city]);

  // Backtest metrics for the "Why trust this ranking" card, read from the same
  // methodology.json the How-it-works page renders (per active city). Secondary
  // to the worklist itself, so a fetch failure just leaves the card blank rather
  // than erroring the page.
  useEffect(() => {
    let alive = true;
    fetch(dataUrl(city, "methodology.json"))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d: WorklistMethodology) => {
        if (alive) setMeth(d);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [city]);

  // "now" is fixed per mount so day-counts don't drift between renders.
  const [now] = useState(() => Date.now());

  const setParams = (next: {
    tiers?: RiskTier[];
    sort?: InspectorSort;
    viol?: string[];
    view?: WorklistView;
  }) => {
    const params = new URLSearchParams(searchParams.toString());
    if (next.tiers) {
      if (isAllTiers(next.tiers)) params.delete("tier");
      else params.set("tier", next.tiers.join(","));
    }
    if (next.sort) {
      if (next.sort === "risk") params.delete("sort");
      else params.set("sort", next.sort);
    }
    if (next.viol) {
      // Unlike tiers, all-six-selected is NOT a no-op (it still excludes
      // establishments whose latest inspection was clean), so the param
      // only clears when the selection is empty.
      if (next.viol.length === 0) params.delete("viol");
      else params.set("viol", next.viol.join(","));
    }
    if (next.view) {
      if (next.view === "list") params.delete("view");
      else params.set("view", next.view);
    }
    const qs = params.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };

  const toggleTier = (tier: RiskTier) => {
    const set = new Set(activeTiers);
    if (set.has(tier)) set.delete(tier);
    else set.add(tier);
    // Toggling the last tier off would show nothing forever — treat it as
    // resetting to all tiers, matching parseTiers's all-invalid fallback.
    const next = ALL_TIERS.filter((t) => set.has(t));
    setParams({ tiers: next.length > 0 ? next : [...ALL_TIERS] });
    setVisibleCount(QUEUE_PAGE);
  };

  const toggleViol = (slug: string) => {
    const set = new Set(activeViol);
    if (set.has(slug)) set.delete(slug);
    else set.add(slug);
    setParams({
      viol: VIOLATION_CATEGORIES.filter((c) => set.has(c.slug)).map(
        (c) => c.slug,
      ),
    });
    setVisibleCount(QUEUE_PAGE);
  };

  // An inspection worklist must never contain a closed venue (DR 0014) — every
  // derived view on this page (queue, stats, Rising fast, tier counts) starts
  // from activeRows, so a flagged establishment can't appear anywhere here.
  // Indexes built from pre-0.6.0 scores.json carry no flag; those rows count
  // as active until the pipeline change lands (PR #131).
  const activeRows = useMemo(
    () => (index ? index.rows.filter((r) => !r.is_out_of_business) : []),
    [index],
  );

  // An index built before violation tagging has no vc on ANY row — hide the
  // violation chips rather than render controls that can never match.
  const indexHasVc = useMemo(
    () => activeRows.some((r) => r.vc !== undefined),
    [activeRows],
  );

  // A ?viol= URL against an index built before violation tagging must not
  // become an invisible, unclearable filter (the chip row is hidden then) —
  // treat the mask as inactive when no row carries vc.
  const effectiveViolBits = indexHasVc ? violBits : 0;

  const rows = useMemo(() => {
    const tierSet = new Set(activeTiers);
    const tierActive = !isAllTiers(activeTiers);
    const matched = activeRows.filter(
      (r) =>
        (!tierActive || tierSet.has(r.risk_tier)) &&
        matchesViolations(r.vc, effectiveViolBits),
    );
    const days = (r: SearchIndexRow) => daysSince(r.as_of_date, now) ?? -1;
    return matched.slice().sort((a, b) => {
      if (sort === "overdue") return days(b) - days(a);
      if (sort === "trend")
        return (b.trend_slope ?? -9) - (a.trend_slope ?? -9);
      return b.risk_score - a.risk_score;
    });
  }, [activeRows, activeTiers, effectiveViolBits, sort, now]);

  // "Worsening" uses the same source-of-truth band as the per-row trend pill
  // (CITY_CONFIG.trendStableBand) and the producer's payload totals
  // (predict_batch.py, DR 0011) — so the stat card equals the count of
  // "Worsening" pills the inspector sees in the list below, not a stale cutoff.
  const worseningCount = useMemo(
    () =>
      activeRows.filter((r) => (r.trend_slope ?? 0) > cfg.trendStableBand)
        .length,
    [activeRows, cfg],
  );

  const risingFast = useMemo(
    () =>
      activeRows
        .filter((r) => (r.trend_slope ?? 0) > cfg.trendStableBand)
        .sort((a, b) => (b.trend_slope ?? 0) - (a.trend_slope ?? 0))
        .slice(0, 3),
    [activeRows, cfg],
  );

  const rowById = useMemo(() => {
    const m = new Map<string, SearchIndexRow>();
    for (const r of activeRows) m.set(r.license_id, r);
    return m;
  }, [activeRows]);

  // Tier chip counts / stat cards are computed over ACTIVE venues so they
  // agree with the queue — the payload's tier_counts still include closed
  // establishments (their historical tier).
  const tierCounts = useMemo(() => {
    if (!index) return undefined;
    const counts = { Low: 0, Moderate: 0, Elevated: 0, High: 0 } as Record<
      RiskTier,
      number
    >;
    for (const r of activeRows) counts[r.risk_tier] += 1;
    return counts;
  }, [index, activeRows]);

  // Chip counts over ACTIVE venues, like tierCounts (population-level; they
  // don't shrink when other filters are applied).
  const violCounts = useMemo(() => {
    const counts = VIOLATION_CATEGORIES.map(() => 0);
    for (const r of activeRows) {
      const vc = r.vc ?? 0;
      for (const c of VIOLATION_CATEGORIES) {
        if (vc & (1 << c.id)) counts[c.id] += 1;
      }
    }
    return counts;
  }, [activeRows]);

  // "Why trust this ranking" numbers, straight from the active city's
  // methodology.json. The top-decile operating point gives the model-ranked
  // hit rate + its lift over random; test.prevalence is the base rate a random
  // visit would hit. Null until the metrics load (or if they fail to).
  const trust = useMemo(() => {
    if (!meth) return null;
    const top10 = meth.operating_points.find(
      (p) => Math.round(p.frac * 100) === 10,
    );
    if (!top10) return null;
    const modelHit = top10.precision;
    const randomHit = meth.test.prevalence;
    const lift = top10.lift || meth.headline.top_decile_lift;
    return {
      lift,
      modelHit,
      randomHit,
      // Bars carry the comparison, not the absolute precision: anchor the model
      // bar wide and scale the random bar by 1/lift so the visual ratio equals
      // the real lift (e.g. a ~1.6x city shows near-equal bars, honestly).
      modelPct: 88,
      randomPct: lift > 0 ? Math.round(88 / lift) : 0,
    };
  }, [meth]);

  const visible = rows.slice(0, visibleCount);

  // Pins in active-sort order: MapView's zoom-density cap draws the FIRST N
  // pins, so the map surfaces the same establishments as the top of the list
  // (e.g. "Worsening fastest" puts trending pins on first). activeRows already
  // excludes closed venues, so no is_out_of_business handling here.
  const mapPins = useMemo<PinSummary[]>(
    () =>
      view === "map"
        ? rows.filter(hasCoords).map((r) => ({
            license_id: r.license_id,
            dba_name: r.dba_name,
            address: r.address,
            lat: r.lat,
            lon: r.lon,
            risk_score: r.risk_score,
            risk_tier: r.risk_tier,
            top_driver: r.top_driver ?? undefined,
          }))
        : [],
    [rows, view],
  );

  return (
    <main className="flex-1 w-full max-w-full lg:max-w-[1240px] overflow-x-clip mx-auto px-4 sm:px-8 pt-10 pb-18">
      <BackToSearch className="inline-flex items-center gap-2 text-sm text-teal hover:underline mb-6" />
      {/* ---- Page intro + stat cards ---- */}
      <div className="flex flex-wrap items-end justify-between gap-5">
        <div className="max-w-[640px]">
          <p className="text-2xs tracking-[0.2em] uppercase text-muted">
            Inspector worklist
          </p>
          <h1 className="serif text-5xl mt-2.5 mb-3.5">
            Inspect where it matters&nbsp;most.
          </h1>
          <p className="text-md text-muted">
            Establishments ranked by how likely each is to{" "}
            <strong className="text-ink font-semibold">
              {cfg.outcomeSentence}
            </strong>
            {". "}Working from the top of this list surfaces{" "}
            <span className="serif italic text-terra text-lg">
              {trust ? `${trust.lift.toFixed(1)}×` : "several times"}
            </span>{" "}
            more {cfg.outcomeNoun} per visit than inspecting at random.
          </p>
        </div>
        <div className="flex flex-wrap gap-2.5">
          <StatCard
            value={tierCounts ? tierCounts.High.toLocaleString() : "—"}
            label="High-tier establishments"
            valueClass="text-terra"
          />
          <StatCard
            value={index ? worseningCount.toLocaleString() : "—"}
            label="Worsening trend (up to past 5 visits)"
            valueClass="text-coral"
          />
          {/* Deviates from the handoff's "Scored citywide": counts active
              venues only, so the card agrees with the queue (DR 0014). */}
          <StatCard
            value={index ? activeRows.length.toLocaleString() : "—"}
            label="Active establishments"
            valueClass="text-ink"
          />
        </div>
      </div>

      {/* ---- Controls ---- */}
      <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-2xs tracking-[0.14em] uppercase text-muted mr-1.5">
            Tier
          </span>
          {/* Chips run High → Low (per the handoff) — the worklist's frame is
              "worst first", unlike the home page's Low-first tally. */}
          {[...ALL_TIERS].reverse().map((tier) => {
            const on = activeTiers.includes(tier);
            return (
              <button
                key={tier}
                type="button"
                onClick={() => toggleTier(tier)}
                aria-pressed={on}
                className="rounded-full cursor-pointer"
              >
                <TierPill
                  tier={tier}
                  inactive={!on}
                  withCount={tierCounts?.[tier]}
                  className="px-3.5 py-1.5"
                />
              </button>
            );
          })}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-2xs tracking-[0.14em] uppercase text-muted mr-1">
            Sort
          </span>
          {SORTS.map((s) => {
            const on = sort === s.key;
            return (
              <button
                key={s.key}
                type="button"
                onClick={() => {
                  setParams({ sort: s.key });
                  setVisibleCount(QUEUE_PAGE);
                }}
                aria-pressed={on}
                className={cn(
                  "rounded-full px-3.5 py-1.5 text-xs font-medium cursor-pointer transition-colors",
                  on
                    ? "bg-ink text-cream border border-ink"
                    : "bg-transparent text-ink border border-line hover:bg-tint",
                )}
              >
                {s.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* ---- Violation filter ---- */}
      {indexHasVc && (
        <div
          role="group"
          aria-label="Filter by violations at last inspection"
          className="mt-3 flex flex-wrap items-center gap-1.5"
        >
          <span className="text-2xs tracking-[0.14em] uppercase text-muted mr-1.5">
            Violations at last inspection
          </span>
          {VIOLATION_CATEGORIES.map((c) => {
            const on = activeViol.includes(c.slug);
            return (
              <button
                key={c.slug}
                type="button"
                onClick={() => toggleViol(c.slug)}
                aria-pressed={on}
                className={cn(
                  "rounded-full px-3.5 py-1.5 text-xs font-medium cursor-pointer transition-colors",
                  on
                    ? "bg-ink text-cream border border-ink"
                    : "bg-transparent text-ink border border-line hover:bg-tint",
                )}
              >
                {c.label}
                <span
                  className={cn("num ml-1.5", on ? "text-cream/70" : "text-muted")}
                >
                  {violCounts[c.id].toLocaleString()}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* ---- Main grid: queue + sidebar ---- */}
      <div className="mt-5 grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-6 items-start">
        {/* ===== Priority queue ===== */}
        <section
          aria-label="Priority queue"
          className="bg-card border border-line rounded-3xl overflow-hidden soft-shadow-lg"
        >
          <div className="flex flex-wrap items-center justify-between gap-2 px-6 pt-5 pb-3.5 border-b border-line">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
              <h2 className="text-md font-bold">Priority queue</h2>
              <p className="text-xs text-muted">
                <span className="num">{rows.length.toLocaleString()}</span>{" "}
                establishments · highest expected yield first
              </p>
            </div>
            {/* List | Map toggle — same segmented pattern as the home page's
                mobile Map/List switch. URL-driven (?view=map). */}
            <div
              role="group"
              aria-label="Queue view"
              className="inline-flex rounded-lg border border-line overflow-hidden text-xs"
            >
              {(["list", "map"] as const).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setParams({ view: v })}
                  aria-pressed={view === v}
                  className={cn(
                    "px-3 py-1 capitalize transition-colors cursor-pointer",
                    v === "map" && "border-l border-line",
                    view === v
                      ? "bg-ink text-cream"
                      : "text-muted hover:bg-cream/60",
                  )}
                >
                  {v}
                </button>
              ))}
            </div>
          </div>

          {failed && (
            <p className="px-6 py-10 text-sm text-muted text-center">
              The worklist index couldn&apos;t load. Reload the page to try
              again.
            </p>
          )}
          {!failed && !index && (
            <p className="px-6 py-10 text-sm text-muted text-center">
              Loading the worklist…
            </p>
          )}

          {index && !failed && view === "map" && (
            <div className="relative h-[70vh] min-h-[480px]">
              <MapView
                pins={mapPins}
                className="absolute inset-0"
                center={{
                  lat: CITY_CONFIG[city].center.lat,
                  lon: CITY_CONFIG[city].center.lon,
                  zoom: CITY_CONFIG[city].zoom,
                }}
              />
            </div>
          )}

          {index && !failed && view === "list" && (
            <>
              {rows.length === 0 && (
                <p className="px-6 py-10 text-sm text-muted text-center">
                  No establishments match these filters.
                </p>
              )}
              {visible.map((r, i) => (
                <QueueRow
                  key={r.license_id}
                  row={r}
                  city={city}
                  rank={i + 1}
                  days={daysSince(r.as_of_date, now)}
                  expanded={!!expanded[r.license_id]}
                  onToggle={() =>
                    setExpanded((e) => ({
                      ...e,
                      [r.license_id]: !e[r.license_id],
                    }))
                  }
                  onAddToRoute={() =>
                    setRoute((ids) =>
                      ids.includes(r.license_id) ? ids : [...ids, r.license_id],
                    )
                  }
                />
              ))}
              {rows.length > visibleCount && (
                <div className="p-3">
                  <button
                    type="button"
                    onClick={() => setVisibleCount((c) => c + QUEUE_PAGE)}
                    className="w-full rounded-xl border border-line py-2 text-sm text-teal hover:bg-cream/50 transition-colors cursor-pointer"
                  >
                    Show {Math.min(QUEUE_PAGE, rows.length - visibleCount)} more
                  </button>
                </div>
              )}
            </>
          )}
        </section>

        {/* ===== Sidebar ===== */}
        <div className="flex flex-col gap-5">
          {/* Model lift card */}
          <section
            aria-label="Why trust this ranking"
            className="bg-ink text-cream rounded-3xl p-6 soft-shadow-lg"
          >
            <p className="text-2xs tracking-[0.16em] uppercase opacity-65">
              Why trust this ranking
            </p>
            <p className="serif text-4xl leading-none mt-3 mb-1">
              {trust ? `${trust.lift.toFixed(1)}×` : "—"}
              <span className="font-sans text-lg font-medium opacity-80 ml-2">
                better than random
              </span>
            </p>
            <p className="text-sm leading-relaxed opacity-75 mt-2.5">
              In backtests, visits drawn from the top of this list found{" "}
              {cfg.outcomeNoun}{" "}
              {trust ? `${trust.lift.toFixed(1)} times` : "several times"} as
              often as visits chosen at random. Predicts{" "}
              <em>where to look first</em>. It is not a verdict on any
              establishment.
            </p>
            <div className="mt-4 flex flex-col gap-2">
              <LiftBar
                label="Model-ranked visits: hit rate"
                value={trust ? `${(trust.modelHit * 100).toFixed(0)}%` : "—"}
                pct={trust ? trust.modelPct : 0}
                barClass="bg-coral"
              />
              <LiftBar
                label="Random visits: hit rate"
                value={trust ? `${(trust.randomHit * 100).toFixed(0)}%` : "—"}
                pct={trust ? trust.randomPct : 0}
                barClass="bg-cream/45"
              />
            </div>
            <Link
              href="/how-it-works"
              className="inline-block mt-3.5 text-xs opacity-60 underline hover:opacity-90"
            >
              Full methodology →
            </Link>
          </section>

          {/* Rising fast */}
          <section
            aria-label="Rising fast"
            className="bg-card border border-line rounded-3xl px-6 py-5 soft-shadow"
          >
            <div className="flex items-center gap-2">
              <TrendingUp
                className="w-[15px] h-[15px] text-terra"
                strokeWidth={2.5}
              />
              <h2 className="text-base font-bold">Rising fast</h2>
            </div>
            <p className="text-xs text-muted mt-1.5 mb-3">
              Steepest score increase over an establishment&apos;s last few
              visits, worth a look even below the High tier.
            </p>
            <div className="flex flex-col gap-0.5">
              {risingFast.map((r) => (
                <Link
                  key={r.license_id}
                  href={`/restaurant/?id=${r.license_id}`}
                  className="flex items-center justify-between gap-2.5 py-2 px-2.5 -mx-2.5 rounded-xl hover:bg-[#FAF7F0] transition-colors"
                >
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold truncate">
                      {r.dba_name}
                    </span>
                    <span className="block text-2xs text-muted truncate">
                      {r.address}
                    </span>
                  </span>
                  <TrendIndicator
                    slope={r.trend_slope}
                    compact
                    className="shrink-0"
                  />
                </Link>
              ))}
              {index && risingFast.length === 0 && (
                <p className="text-xs text-muted">
                  Nothing rising above the stable band right now.
                </p>
              )}
            </div>
          </section>

          {/* Today's route */}
          <section
            aria-label="Today's route"
            className="bg-card border border-line rounded-3xl px-6 py-5 soft-shadow"
          >
            <h2 className="text-base font-bold">Today&apos;s route</h2>
            <p className="text-xs text-muted mt-1.5">
              Queue rows you add appear here for an efficient day plan.
            </p>
            {route.length === 0 ? (
              <div className="mt-3.5 border-[1.5px] border-dashed border-line rounded-2xl p-4.5 text-center text-xs text-muted">
                No stops yet. Expand a row and press{" "}
                <strong className="text-ink">Add to today&apos;s route</strong>
              </div>
            ) : (
              <ol className="mt-3 flex flex-col gap-1.5">
                {route.map((id, i) => (
                  <li
                    key={id}
                    className="flex items-center gap-2.5 text-sm px-3 py-2 bg-[#FAF7F0] rounded-xl"
                  >
                    <span className="num text-muted">{i + 1}</span>
                    <span className="font-semibold flex-1 truncate">
                      {rowById.get(id)?.dba_name ?? id}
                    </span>
                    <button
                      type="button"
                      aria-label={`Remove ${rowById.get(id)?.dba_name ?? id} from route`}
                      onClick={() =>
                        setRoute((ids) => ids.filter((x) => x !== id))
                      }
                      className="text-muted hover:text-ink text-base leading-none cursor-pointer"
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </section>

          {/* Honest-use note */}
          <aside className="border border-line rounded-3xl px-5 py-4 text-xs text-muted leading-relaxed bg-tint">
            <strong className="text-ink">A ranking, not a judgment.</strong>{" "}
            Scores are calibrated probabilities from public food-safety
            inspection records. They prioritize limited inspection capacity.
            Every establishment still gets its regular cadence.
          </aside>
        </div>
      </div>
    </main>
  );
}

function StatCard({
  value,
  label,
  valueClass,
}: {
  value: string;
  label: string;
  valueClass: string;
}) {
  return (
    <div className="bg-card border border-line rounded-3xl px-5.5 py-4 min-w-[118px] soft-shadow">
      <div className={cn("num text-2xl font-semibold", valueClass)}>
        {value}
      </div>
      <div className="text-2xs text-muted mt-0.5">{label}</div>
    </div>
  );
}

function LiftBar({
  label,
  value,
  pct,
  barClass,
}: {
  label: string;
  value: string;
  pct: number;
  barClass: string;
}) {
  return (
    <div>
      <div className="flex justify-between text-2xs mb-1">
        <span className="opacity-75">{label}</span>
        <span className="num">{value}</span>
      </div>
      <div className="h-[7px] rounded-sm bg-cream/15 overflow-hidden">
        <div
          className={cn("h-full rounded-sm", barClass)}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/** Icon component resolved by the caller — stable ref, satisfies the
 *  react-hooks/static-components rule (same pattern as PinDriverLine). */
function DriverGlyph({ icon: Icon }: { icon: LucideIcon }) {
  return <Icon className="w-3 h-3 shrink-0" strokeWidth={2} />;
}

function QueueRow({
  row,
  city,
  rank,
  days,
  expanded,
  onToggle,
  onAddToRoute,
}: {
  row: SearchIndexRow;
  city: City;
  rank: number;
  days: number | null;
  expanded: boolean;
  onToggle: () => void;
  onAddToRoute: () => void;
}) {
  const d = row.top_driver;
  const overdue = days !== null && days > OVERDUE_DAYS;
  // Neighborhood is empty in the current feed (contract 0.7.0 data ask), so
  // the meta line is address + recency; parts join gracefully when absent.
  const metaBits = [row.address.trim()].filter(Boolean);

  return (
    <div className="border-b border-[#EFE9DD] last:border-b-0">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className={cn(
          "w-full text-left grid grid-cols-[44px_1fr_auto] gap-3.5 items-center px-4 sm:px-6 py-4 cursor-pointer transition-colors hover:bg-[#FAF7F0]",
          expanded && "bg-[#FAF7F0]",
        )}
      >
        <span className="num text-sm font-semibold text-ink text-center">
          {String(rank).padStart(2, "0")}
        </span>
        <span className="min-w-0">
          <span className="flex items-center gap-2.5 flex-wrap">
            <span className="font-bold text-base">{row.dba_name}</span>
            <TierPill tier={row.risk_tier} size="sm" />
            {overdue && (
              <span className="inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-semibold bg-highlight text-[#7A5A24]">
                Overdue
              </span>
            )}
          </span>
          <span className="block text-sm text-muted mt-0.5 truncate">
            {metaBits.join(" · ")}
            {days !== null && (
              <>
                {metaBits.length > 0 && " · "}last inspected{" "}
                <span className="num">{days.toLocaleString()}</span> days ago
              </>
            )}
          </span>
          {d && (
            <span
              className={cn(
                "mt-1.5 inline-flex items-center gap-1.5 rounded-full px-2.5 py-[3px] text-xs font-medium max-w-[420px]",
                d.up
                  ? "bg-terra/10 text-terra-strong"
                  : "bg-sage/15 text-sage-strong",
              )}
            >
              <DriverGlyph icon={iconForFeature(d.feature)} />
              <span className="truncate">{d.label}</span>
              {d.up ? (
                <ArrowUp className="w-3 h-3 shrink-0" strokeWidth={2.5} />
              ) : (
                <ArrowDown className="w-3 h-3 shrink-0" strokeWidth={2.5} />
              )}
            </span>
          )}
        </span>
        <span className="flex items-center gap-4.5">
          <span className="text-right hidden sm:block">
            <span className="block text-2xs tracking-[0.12em] uppercase text-muted">
              Trend
            </span>
            <TrendIndicator slope={row.trend_slope} className="mt-0.5" />
          </span>
          <span className="text-right min-w-[64px]">
            <span className="block text-2xs tracking-[0.12em] uppercase text-muted">
              Score
            </span>
            <span
              className="num text-2xl font-semibold"
              style={{ color: TIER_HEX[row.risk_tier] }}
            >
              {row.risk_score.toFixed(2)}
            </span>
          </span>
          <ChevronDown
            className={cn(
              "w-4 h-4 text-muted transition-transform duration-200",
              expanded && "rotate-180",
            )}
            strokeWidth={2}
          />
        </span>
      </button>
      {expanded && (
        <ExpandedDetail
          licenseId={row.license_id}
          city={city}
          onAddToRoute={onAddToRoute}
        />
      )}
    </div>
  );
}

/**
 * Expanded row: lazy-fetches the establishment's DetailBundle on first render
 * (module-level cache so re-expanding is free), then shows the full driver
 * list with magnitude bars and the recent inspection history.
 */
const detailCache = new Map<string, DetailBundle>();

function ExpandedDetail({
  licenseId,
  city,
  onAddToRoute,
}: {
  licenseId: string;
  city: City;
  onAddToRoute: () => void;
}) {
  const cacheKey = `${city}:${licenseId}`;
  const [bundle, setBundle] = useState<DetailBundle | null>(
    detailCache.get(cacheKey) ?? null,
  );
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (detailCache.has(cacheKey)) return;
    let alive = true;
    fetch(dataUrl(city, `detail/${encodeURIComponent(licenseId)}.json`))
      .then((r) =>
        r.ok ? r.json() : Promise.reject(new Error(String(r.status))),
      )
      .then((b: DetailBundle) => {
        detailCache.set(cacheKey, b);
        if (alive) setBundle(b);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [cacheKey, city, licenseId]);

  if (failed) {
    return (
      <p className="px-6 pb-5 pl-[82px] text-sm text-muted">
        Couldn&apos;t load this establishment&apos;s record.
      </p>
    );
  }
  if (!bundle) {
    return (
      <p className="px-6 pb-5 pl-[82px] text-sm text-muted">Loading record…</p>
    );
  }

  const drivers = bundle.restaurant.top_drivers;
  const maxMag = Math.max(1e-9, ...drivers.map((x) => Math.abs(x.shap)));
  const history = bundle.history.slice(0, 3);
  // Colour each result by the city's OWN outcome semantics — Grade A/B/C for NYC
  // and LA, Pass / Pass w-Conditions / Fail for Chicago — via the shared
  // historyResults buckets (sage = good, amber = middle, terra = bad). Matching
  // on the literal strings "Pass"/"Fail" would drop every NYC/LA grade into one
  // undifferentiated colour.
  const resultTextColor = (result: string): string => {
    const cat = CITY_CONFIG[city].historyResults.find((c) => c.match(result));
    if (!cat) return "text-muted";
    if (cat.bg === "bg-sage") return "text-sage-strong";
    if (cat.bg === "bg-terra") return "text-terra";
    return "text-[#7A5A24]"; // amber / middle tier (Pass w/ Conditions, Grade B)
  };

  return (
    <div className="px-4 sm:px-6 lg:pl-[82px] pb-5 pt-1 grid grid-cols-1 md:grid-cols-2 gap-6 bg-[#FAF7F0]">
      <div>
        <p className="text-2xs tracking-[0.14em] uppercase text-muted mb-2.5">
          Why the model flags this
        </p>
        <div className="flex flex-col gap-2">
          {drivers.map((dr) => {
            const up = dr.shap > 0;
            return (
              <div
                key={dr.feature}
                className="grid grid-cols-[1fr_90px_44px] gap-2.5 items-center"
              >
                <span className="text-sm leading-snug">{dr.label}</span>
                <span className="relative h-1.5 bg-[#F1ECE1] rounded-full overflow-hidden">
                  <span
                    className={cn(
                      "absolute inset-y-0 left-0 rounded-full",
                      up ? "bg-terra" : "bg-sage",
                    )}
                    style={{
                      width: `${Math.round((Math.abs(dr.shap) / maxMag) * 100)}%`,
                    }}
                  />
                </span>
                <span
                  className={cn(
                    "num text-xs font-medium text-right",
                    up ? "text-terra-strong" : "text-sage-strong",
                  )}
                >
                  {up ? "+" : "−"}
                  {Math.abs(dr.shap).toFixed(2)}
                </span>
              </div>
            );
          })}
        </div>
      </div>
      <div>
        <p className="text-2xs tracking-[0.14em] uppercase text-muted mb-2.5">
          Recent inspection history
        </p>
        <div className="flex flex-col gap-1.5">
          {history.length === 0 && (
            <p className="text-sm text-muted">No inspections on record.</p>
          )}
          {history.map((h, i) => (
            <div
              key={`${h.date}-${i}`}
              className="flex items-baseline gap-2.5 text-sm"
            >
              <span className="num text-muted shrink-0">
                {formatInspectionDate(h.date)}
              </span>
              <span
                className={cn("font-semibold shrink-0", resultTextColor(h.result))}
              >
                {h.result || "—"}
              </span>
              <span className="text-muted truncate">
                {/* LA labels items "# 23. …"; drop the leading hash for display. */}
                {h.headline.replace(/^#\s+/, "") || "No violations recorded"}
              </span>
            </div>
          ))}
        </div>
        <div className="mt-3.5 flex flex-wrap gap-2">
          <Link
            href={`/restaurant/?id=${licenseId}`}
            className="rounded-full px-4 py-[7px] text-xs font-semibold bg-ink text-cream hover:opacity-90 transition-opacity"
          >
            Open full record
          </Link>
          <button
            type="button"
            onClick={onAddToRoute}
            className="rounded-full px-4 py-[7px] text-xs font-semibold border border-line text-ink hover:bg-tint transition-colors cursor-pointer"
          >
            Add to today&apos;s route
          </button>
        </div>
      </div>
    </div>
  );
}
