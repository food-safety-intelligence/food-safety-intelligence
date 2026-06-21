"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import type { HomeSort, HomeView, RiskTier } from "@/lib/scores";
import { ALL_TIERS, isAllTiers, TIER_HEX, TIER_TEXT_CLASS } from "@/lib/scores";
import { TierPill } from "@/components/TierPill";
import { TrendIndicator } from "@/components/TrendIndicator";
import { MapView, PinDriverLine } from "@/components/MapView";
import { cn } from "@/lib/utils";

// How long to wait after the last keystroke before pushing `?q=` to the URL.
// Keeps typing responsive (local state updates instantly) while avoiding a
// server round-trip per character.
const SEARCH_DEBOUNCE_MS = 300;

// Side-list reveals incrementally (a "show more" step) so a fresh load — and
// especially mobile, where the list isn't a fixed-height scroll panel — isn't
// hundreds of rows tall.
const LIST_PAGE = 25;

/**
 * Map-first home shell — the design's "Chicago Safety Map" screen.
 *
 * URL-driven: search (`?q=`), tier filter (`?tier=`), and sort (`?sort=`) all
 * live in the URL. The server (`getHomeView`) does ALL filtering/sorting over
 * the full population and hands back the capped list + filtered pins; this
 * component only renders them and edits the URL. That's what makes search
 * reach every establishment and every tier — not just the top-N shipped down.
 *
 * Mobile shows one pane at a time (Map / List toggle); desktop shows both.
 */
export function MapExplorer({
  view,
  query,
  sort,
  activeTiers,
}: {
  view: HomeView;
  query: string;
  sort: HomeSort;
  activeTiers: RiskTier[];
}) {
  const router = useRouter();
  const pathname = usePathname();

  // Local mirror of the query so the input stays responsive while the URL
  // catches up on a debounce. Seeded from the URL-derived prop.
  const [input, setInput] = useState(query);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Mobile shows ONE pane at a time (map or list) to avoid a tall map stacked
  // above a long list; desktop shows both side by side.
  const [mobileView, setMobileView] = useState<"map" | "list">("map");
  // How many list rows are revealed (the "show more" step).
  const [visibleCount, setVisibleCount] = useState(LIST_PAGE);

  // Reset the reveal to page 1 when the result set changes (query / sort / tier).
  // Adjust-state-during-render (React's recommended alternative to a reset
  // effect) — no extra commit, no cascading-render lint error.
  const resultKey = `${query}|${sort}|${activeTiers.join(",")}`;
  const [prevResultKey, setPrevResultKey] = useState(resultKey);
  if (resultKey !== prevResultKey) {
    setPrevResultKey(resultKey);
    setVisibleCount(LIST_PAGE);
  }

  // Keep the input in sync when the URL query changes from outside the box
  // (back/forward, a cleared search) — but never clobber what the user is
  // actively typing.
  useEffect(() => {
    if (document.activeElement !== inputRef.current) setInput(query);
  }, [query]);

  const hasQuery = query.trim().length > 0;
  const tierActive = !isAllTiers(activeTiers);
  const activeSet = new Set(activeTiers);

  const hrefFor = (next: {
    q?: string;
    sort?: HomeSort;
    tiers?: RiskTier[];
  }): string => {
    const q = (next.q ?? query).trim();
    const s = next.sort ?? sort;
    const t = next.tiers ?? activeTiers;
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (s !== "risk") params.set("sort", s);
    if (!isAllTiers(t)) params.set("tier", t.join(","));
    const qs = params.toString();
    return qs ? `${pathname}?${qs}` : pathname;
  };

  const onSearchChange = (value: string) => {
    setInput(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      router.replace(hrefFor({ q: value }), { scroll: false });
    }, SEARCH_DEBOUNCE_MS);
  };

  const toggleTier = (tier: RiskTier) => {
    const next = new Set(activeSet);
    if (next.has(tier)) next.delete(tier);
    else next.add(tier);
    // Empty selection is meaningless → treat as "all".
    const tiers =
      next.size === 0 ? [...ALL_TIERS] : ALL_TIERS.filter((t) => next.has(t));
    router.replace(hrefFor({ tiers }), { scroll: false });
  };

  const setSort = (s: HomeSort) => {
    router.replace(hrefFor({ sort: s }), { scroll: false });
  };

  const { listRows, pins, matchCount, total, tierCounts } = view;
  const capped = matchCount > listRows.length;
  const visibleRows = listRows.slice(0, visibleCount);
  const moreInList = listRows.length - visibleRows.length;

  return (
    <div className="flex flex-col h-full">
      {/* Mobile-only Map / List toggle — desktop shows both panes. */}
      <div className="lg:hidden px-4 pb-3">
        <div
          role="group"
          aria-label="View"
          className="inline-flex rounded-lg border border-line overflow-hidden text-[13px]"
        >
          {(["map", "list"] as const).map((v) => (
            <button
              key={v}
              onClick={() => setMobileView(v)}
              aria-pressed={mobileView === v}
              className={cn(
                "px-4 py-1.5 capitalize transition-colors",
                v === "list" && "border-l border-line",
                mobileView === v
                  ? "bg-ink text-cream"
                  : "text-muted hover:bg-cream/60",
              )}
            >
              {v}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-0 lg:gap-6 px-4 lg:px-8 flex-1 min-h-0">
        {/* MAP COLUMN */}
        <div
          className={cn(
            mobileView === "map" ? "block" : "hidden",
            "lg:block relative h-[calc(100vh-220px)] lg:h-[calc(100vh-140px)] min-h-[480px] rounded-3xl overflow-hidden border border-line bg-card soft-shadow",
          )}
        >
          <MapView pins={pins} className="absolute inset-0" />

          {/* Floating search + filter overlay */}
          <div className="absolute top-4 left-4 right-4 z-10 pointer-events-none">
            <div className="pointer-events-auto rounded-2xl bg-card/95 backdrop-blur border border-line soft-shadow p-2 max-w-[640px]">
              <div className="flex items-center gap-3 px-3 py-2">
                <Search className="w-5 h-5 text-ink" strokeWidth={2} />
                <input
                  ref={inputRef}
                  type="text"
                  value={input}
                  onChange={(e) => onSearchChange(e.target.value)}
                  placeholder="Search food establishments or addresses"
                  className="bg-transparent flex-1 text-[16px] placeholder:text-muted/70 focus:outline-none"
                  aria-label="Search food establishments or addresses"
                />
                <span
                  className="text-[10px] text-muted/80 px-2 py-1 rounded-md bg-tint"
                  title={`Searches all ${total.toLocaleString()} indexed food establishments server-side, across every risk tier.`}
                >
                  {total.toLocaleString()} indexed
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-1.5 px-2 pt-2 pb-1">
                {ALL_TIERS.map((tier) => (
                  <button
                    key={tier}
                    onClick={() => toggleTier(tier)}
                    className={cn(
                      "transition-opacity",
                      !tierActive || activeSet.has(tier)
                        ? "opacity-100"
                        : "opacity-35",
                    )}
                    aria-pressed={!tierActive || activeSet.has(tier)}
                  >
                    <TierPill tier={tier} withCount={tierCounts[tier]} size="sm" />
                  </button>
                ))}
                <span className="grow" />
                <span className="text-[11px] text-muted mr-2">
                  {pins.length.toLocaleString()} on map
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
        <aside
          className={cn(
            mobileView === "list" ? "flex" : "hidden",
            "lg:flex flex-col h-[calc(100vh-220px)] lg:h-[calc(100vh-140px)] min-h-[480px]",
          )}
        >
          <div className="rounded-3xl bg-card border border-line soft-shadow flex flex-col h-full overflow-hidden">
            <div className="px-5 py-4 border-b border-line bg-cream/40">
              <div className="flex items-center justify-between gap-2">
                <h2 className="font-semibold tracking-tight text-[15px]">
                  {hasQuery
                    ? `Matching "${query}"`
                    : sort === "name"
                      ? "All establishments · A–Z"
                      : "Highest risk"}
                </h2>
                {/* Sort toggle — A–Z surfaces every tier alphabetically, so the
                    list is no longer just the highest-risk (all-High) slice. */}
                <div
                  className="flex items-center rounded-lg border border-line overflow-hidden text-[11px]"
                  role="group"
                  aria-label="Sort order"
                >
                  <button
                    onClick={() => setSort("risk")}
                    aria-pressed={sort === "risk"}
                    className={cn(
                      "px-2 py-1 transition-colors",
                      sort === "risk"
                        ? "bg-ink text-cream"
                        : "text-muted hover:bg-cream/60",
                    )}
                  >
                    Risk
                  </button>
                  <button
                    onClick={() => setSort("name")}
                    aria-pressed={sort === "name"}
                    className={cn(
                      "px-2 py-1 transition-colors border-l border-line",
                      sort === "name"
                        ? "bg-ink text-cream"
                        : "text-muted hover:bg-cream/60",
                    )}
                  >
                    A–Z
                  </button>
                </div>
              </div>
              <p className="text-[11px] text-muted mt-0.5">
                {hasQuery ? (
                  <>
                    {capped
                      ? `First ${listRows.length.toLocaleString()} of ${matchCount.toLocaleString()} matches`
                      : `${matchCount.toLocaleString()} ${matchCount === 1 ? "match" : "matches"}`}
                  </>
                ) : sort === "name" ? (
                  <>
                    Showing {listRows.length.toLocaleString()} of{" "}
                    {total.toLocaleString()} — type to find any establishment
                  </>
                ) : (
                  <>
                    Top {listRows.length.toLocaleString()} by risk ·{" "}
                    {total.toLocaleString()} indexed (search or sort A–Z for the
                    rest)
                  </>
                )}
              </p>
            </div>

            <ul className="flex-1 overflow-y-auto divide-y divide-line">
              {listRows.length === 0 && (
                <li className="px-5 py-8 text-[13px] text-muted text-center">
                  No food establishments match these filters.
                </li>
              )}
              {visibleRows.map((r) => (
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
                      {r.top_driver && (
                        <div className="mt-1.5">
                          <PinDriverLine driver={r.top_driver} />
                        </div>
                      )}
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
              {moreInList > 0 && (
                <li className="p-3">
                  <button
                    onClick={() =>
                      setVisibleCount((c) => c + LIST_PAGE)
                    }
                    className="w-full rounded-xl border border-line py-2 text-[13px] text-teal hover:bg-cream/50 transition-colors"
                  >
                    Show {Math.min(LIST_PAGE, moreInList)} more
                    <span className="text-muted">
                      {" "}
                      ({visibleRows.length.toLocaleString()} of{" "}
                      {listRows.length.toLocaleString()})
                    </span>
                  </button>
                </li>
              )}
            </ul>
          </div>
        </aside>
      </div>
    </div>
  );
}
