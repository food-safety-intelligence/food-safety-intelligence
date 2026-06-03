"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import type { PinSummary, RestaurantScore, RiskTier } from "@/lib/scores";
import { TIER_HEX, TIER_TEXT_CLASS } from "@/lib/scores";
import { TierPill } from "@/components/TierPill";
import { TrendIndicator } from "@/components/TrendIndicator";
import { MapView } from "@/components/MapView";
import { cn } from "@/lib/utils";

const ALL_TIERS: RiskTier[] = ["Low", "Moderate", "Elevated", "High"];

/**
 * Map-first home shell — the design's "Chicago Safety Map" screen, scaled
 * for desktop. Layout:
 *
 *   ┌─────────────────────────────────────────┐
 *   │ floating search + filter chips          │
 *   │                                         │  side list
 *   │             M A P                       │  (scrollable)
 *   │                                         │
 *   │             [zoom controls]             │
 *   └─────────────────────────────────────────┘
 *
 * On a tablet/mobile the side list stacks below the map.
 */
export function MapExplorer({
  scores,
  pins,
  tierCounts,
  totalEstablishments,
}: {
  scores: RestaurantScore[];
  pins: PinSummary[];
  tierCounts: Record<RiskTier, number>;
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

  // The map gets the FULL pin set (all ~23k restaurants) so it can do
  // zoom-aware density on its own. The side list still works against the
  // smaller scoresfull-feature top-N for fast search + rich rows. Tier-chip
  // filtering applies to both.
  const visiblePins = useMemo(
    () => pins.filter((p) => activeTiers.has(p.risk_tier)),
    [pins, activeTiers],
  );

  const toggleTier = (tier: RiskTier) => {
    setActiveTiers((prev) => {
      const next = new Set(prev);
      if (next.has(tier)) next.delete(tier);
      else next.add(tier);
      return next.size === 0 ? new Set(ALL_TIERS) : next;
    });
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-0 lg:gap-6 px-4 lg:px-8 h-full">
      {/* MAP COLUMN */}
      <div className="relative h-[calc(100vh-200px)] lg:h-[calc(100vh-140px)] min-h-[520px] rounded-3xl overflow-hidden border border-line bg-card soft-shadow">
        <MapView pins={visiblePins} className="absolute inset-0" />

        {/* Floating search + filter overlay */}
        <div className="absolute top-4 left-4 right-4 z-10 pointer-events-none">
          <div className="pointer-events-auto rounded-2xl bg-card/95 backdrop-blur border border-line soft-shadow p-2 max-w-[640px]">
            <div className="flex items-center gap-3 px-3 py-2">
              <Search className="w-5 h-5 text-ink" strokeWidth={2} />
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search restaurants or addresses"
                className="bg-transparent flex-1 text-[16px] placeholder:text-muted/70 focus:outline-none"
              />
              <span
                className="text-[10px] text-muted/80 px-2 py-1 rounded-md bg-tint"
                title={`Map shows up to a zoom-dependent cap from ${pins.length.toLocaleString()} restaurants. Side list shows the top ${scores.length} by risk score.`}
              >
                {pins.length.toLocaleString()} pins · zoom for more
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 px-2 pt-2 pb-1">
              {ALL_TIERS.map((tier) => (
                <button
                  key={tier}
                  onClick={() => toggleTier(tier)}
                  className={cn(
                    "transition-opacity",
                    activeTiers.has(tier) ? "opacity-100" : "opacity-35",
                  )}
                  aria-pressed={activeTiers.has(tier)}
                >
                  <TierPill tier={tier} withCount={tierCounts[tier]} size="sm" />
                </button>
              ))}
              <span className="grow" />
              <span className="text-[11px] text-muted mr-2">
                {filtered.length.toLocaleString()} shown
              </span>
            </div>
          </div>
        </div>

        {/* Bottom-left attribution-ish chip */}
        <div className="absolute bottom-3 left-3 z-10 text-[10px] text-muted/80 bg-card/80 backdrop-blur rounded px-2 py-1 pointer-events-none">
          Chicago · 41.88, −87.63
        </div>
      </div>

      {/* SIDE LIST */}
      <aside className="mt-6 lg:mt-0 lg:h-[calc(100vh-140px)] lg:min-h-[520px] flex flex-col">
        <div className="rounded-3xl bg-card border border-line soft-shadow flex flex-col h-full overflow-hidden">
          <div className="px-5 py-4 border-b border-line bg-cream/40">
            <h2 className="font-semibold tracking-tight text-[15px]">
              {query
                ? `Matching "${query}"`
                : "Highest-risk · live"}
            </h2>
            <p className="text-[11px] text-muted mt-0.5">
              {filtered.length.toLocaleString()} restaurants ·{" "}
              {(totalEstablishments ?? scores.length).toLocaleString()} indexed
            </p>
          </div>

          <ul className="flex-1 overflow-y-auto divide-y divide-line">
            {filtered.length === 0 && (
              <li className="px-5 py-8 text-[13px] text-muted text-center">
                No restaurants match these filters.
              </li>
            )}
            {filtered
              .slice()
              .sort((a, b) => b.risk_score - a.risk_score)
              .slice(0, 200)
              .map((r) => (
                <li key={r.license_id}>
                  <Link
                    href={`/restaurant/${r.license_id}`}
                    className="flex items-start gap-3 px-5 py-3 hover:bg-cream/40 transition-colors"
                  >
                    <div
                      className="w-2.5 h-2.5 rounded-full mt-1.5 shrink-0"
                      style={{ background: TIER_HEX[r.risk_tier] }}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-[13.5px] leading-tight truncate">
                        {r.dba_name}
                      </div>
                      <div className="text-[11.5px] text-muted truncate mt-0.5">
                        {r.address}
                      </div>
                      <div className="flex items-center gap-2 mt-1.5">
                        <TierPill tier={r.risk_tier} size="sm" />
                        <TrendIndicator slope={r.trend_slope_90d} />
                      </div>
                    </div>
                    <div
                      className={cn(
                        "num text-[18px] font-medium tabular-nums leading-none",
                        TIER_TEXT_CLASS[r.risk_tier],
                      )}
                    >
                      {r.risk_score.toFixed(2)}
                    </div>
                  </Link>
                </li>
              ))}
          </ul>
        </div>
      </aside>
    </div>
  );
}
