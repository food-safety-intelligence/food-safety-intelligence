"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Filter, Search } from "lucide-react";
import type { RestaurantScore, RiskTier } from "@/lib/scores";
import { TIER_TEXT_CLASS } from "@/lib/scores";
import { TierPill } from "@/components/TierPill";
import { TrendIndicator } from "@/components/TrendIndicator";
import { MapPlaceholder, NearbyList } from "@/components/MapPlaceholder";
import { cn } from "@/lib/utils";

const ALL_TIERS: RiskTier[] = ["Low", "Moderate", "Elevated", "High"];

/**
 * Home-page interactive shell. Owns the search query + tier filter state and
 * filters the list in-memory. Fine for the 8-row mock; when we move to the
 * full ~28k-row production dataset, we'll either virtualize the table or
 * paginate server-side via searchParams.
 */
export function RestaurantsExplorer({
  scores,
  tierCounts,
  totalEstablishments,
}: {
  scores: RestaurantScore[];
  tierCounts: Record<RiskTier, number>;
  /** Population total — used in the "showing X of Y" count when the parent
   *  sliced the visible set for speed. Defaults to ``scores.length``. */
  totalEstablishments?: number;
}) {
  const [query, setQuery] = useState("");
  const [activeTiers, setActiveTiers] = useState<Set<RiskTier>>(
    new Set(ALL_TIERS),
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return scores
      .filter((r) => activeTiers.has(r.risk_tier))
      .filter((r) =>
        q
          ? `${r.dba_name} ${r.address} ${r.neighborhood}`
              .toLowerCase()
              .includes(q)
          : true,
      );
  }, [scores, query, activeTiers]);

  const toggleTier = (tier: RiskTier) => {
    setActiveTiers((prev) => {
      const next = new Set(prev);
      if (next.has(tier)) next.delete(tier);
      else next.add(tier);
      // never let all tiers be off — re-add all if user toggles last one off
      return next.size === 0 ? new Set(ALL_TIERS) : next;
    });
  };

  return (
    <>
      {/* Search + filter strip */}
      <section className="mb-10">
        <div className="rounded-4xl bg-card border border-line soft-shadow-lg p-3 sm:p-4">
          <div
            className="flex items-center gap-4 px-4 py-3 rounded-3xl bg-cream/60"
            style={{ boxShadow: "0 0 0 4px rgba(72,96,115,0.06)" }}
          >
            <Search className="w-5 h-5 text-ink" strokeWidth={2} />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name, address, or neighborhood"
              className="bg-transparent flex-1 text-lg placeholder:text-muted/70 focus:outline-none"
            />
            <kbd className="text-2xs text-muted px-2 py-1 rounded-md bg-tint">
              ⌘ K
            </kbd>
          </div>
          <div className="flex flex-wrap items-center gap-2 px-3 pt-4 pb-2">
            <span className="text-xs tracking-widest uppercase text-muted mr-2">
              Tiers:
            </span>
            {ALL_TIERS.map((tier) => (
              <button
                key={tier}
                onClick={() => toggleTier(tier)}
                className={cn(
                  "transition-opacity",
                  activeTiers.has(tier) ? "opacity-100" : "opacity-40",
                )}
              >
                <TierPill tier={tier} withCount={tierCounts[tier]} />
              </button>
            ))}
            <span className="grow" />
            <button className="text-xs flex items-center gap-2 text-teal hover:underline">
              <Filter className="w-[14px] h-[14px]" strokeWidth={2} />
              Filter for immunocompromised guidance
            </button>
          </div>
        </div>
      </section>

      {/* Map + side list */}
      <section className="mb-12 grid grid-cols-12 gap-6">
        <div className="col-span-12 lg:col-span-8">
          <MapPlaceholder restaurants={filtered} />
        </div>
        <div className="col-span-12 lg:col-span-4">
          <NearbyList restaurants={filtered} />
        </div>
      </section>

      {/* Full ranked table */}
      <section>
        <div className="flex items-baseline justify-between mb-4 gap-4 flex-wrap">
          <h2 className="text-2xl font-medium tracking-tight">
            {query
              ? `Matching "${query}"`
              : "Highest-risk food establishments today"}
          </h2>
          <span className="text-xs text-muted">
            Sorted by predicted score · {filtered.length} of{" "}
            {scores.length.toLocaleString()}
            {totalEstablishments && totalEstablishments > scores.length && (
              <>
                {" "}
                <span className="text-muted/70">
                  (top {scores.length} shown out of{" "}
                  {totalEstablishments.toLocaleString()} — speed mode)
                </span>
              </>
            )}
          </span>
        </div>

        <div className="rounded-3xl bg-card border border-line soft-shadow overflow-hidden">
          <div className="grid grid-cols-12 px-6 py-3 text-2xs tracking-widest uppercase text-muted border-b border-line bg-cream/40">
            <div className="col-span-5">Establishment</div>
            <div className="col-span-3">Tier</div>
            <div className="col-span-2 text-right">Score</div>
            <div className="col-span-2 text-right">90-day trend</div>
          </div>

          {filtered.length === 0 && (
            <div className="px-6 py-10 text-center text-base text-muted">
              No food establishments match this search.
            </div>
          )}

          {filtered
            .slice()
            .sort((a, b) => b.risk_score - a.risk_score)
            .map((r, i) => (
              <Link
                key={r.license_id}
                href={`/restaurant/${r.license_id}`}
                className={cn(
                  "grid grid-cols-12 px-6 py-4 items-center hover:bg-cream/40 transition-colors",
                  i < filtered.length - 1 && "border-b border-line",
                )}
              >
                <div className="col-span-5">
                  <div className="font-semibold">{r.dba_name}</div>
                  <div className="text-xs text-muted">
                    {r.address} · {r.neighborhood}
                  </div>
                </div>
                <div className="col-span-3">
                  <TierPill tier={r.risk_tier} />
                </div>
                <div
                  className={cn(
                    "col-span-2 text-right num text-xl font-medium",
                    TIER_TEXT_CLASS[r.risk_tier],
                  )}
                >
                  {r.risk_score.toFixed(2)}
                </div>
                <div className="col-span-2 flex justify-end">
                  <TrendIndicator slope={r.trend_slope} compact />
                </div>
              </Link>
            ))}
        </div>
      </section>
    </>
  );
}
