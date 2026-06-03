import Link from "next/link";
import type { RestaurantScore } from "@/lib/scores";
import { TIER_HEX, TIER_TEXT_CLASS } from "@/lib/scores";
import { TierPill } from "@/components/TierPill";
import { TrendIndicator } from "@/components/TrendIndicator";

/**
 * Mocked Chicago map. Pins are positioned by % rather than projected from
 * (lat, lon), so the visual is illustrative — fine for Phase 1. Phase 2
 * swaps this for `react-map-gl` + maplibre tiles in a client component.
 */

// Hand-picked positions that read as a sparse, varied map. Tied to mock data
// for now; production will compute from lat/lon.
const PIN_POSITIONS = [
  "left-[48%] top-[30%]",
  "left-[55%] top-[64%]",
  "left-[52%] top-[42%]",
  "left-[38%] top-[51%]",
  "left-[32%] top-[73%]",
  "left-[62%] top-[18%]",
  "left-[46%] top-[24%]",
  "left-[70%] top-[38%]",
  "left-[28%] top-[32%]",
  "left-[42%] top-[68%]",
  "left-[58%] top-[50%]",
  "left-[36%] top-[39%]",
  "left-[64%] top-[60%]",
  "left-[51%] top-[80%]",
];

export function MapPlaceholder({
  restaurants,
  featuredLicenseId,
}: {
  restaurants: RestaurantScore[];
  featuredLicenseId?: string;
}) {
  const featured = featuredLicenseId
    ? restaurants.find((r) => r.license_id === featuredLicenseId) ??
      restaurants[0]
    : restaurants[0];
  const pins = restaurants.slice(0, PIN_POSITIONS.length);

  return (
    <div className="rounded-3xl bg-card border border-line soft-shadow p-3">
      <div
        className="rounded-2xl relative h-[440px] overflow-hidden"
        style={{
          background:
            "radial-gradient(120% 80% at 30% 20%, #EAE3D2 0%, #E2DAC4 60%, #D8CEB4 100%)",
        }}
      >
        {/* compass card */}
        <div className="absolute top-4 left-4 rounded-xl bg-white/85 backdrop-blur px-3 py-2 text-[11px] text-muted soft-shadow">
          <div className="font-medium text-ink">Chicago</div>
          <div className="num">41.88, −87.63</div>
        </div>

        {/* dotted grid texture */}
        <svg
          className="absolute inset-0 w-full h-full opacity-25"
          viewBox="0 0 800 440"
          preserveAspectRatio="none"
          aria-hidden
        >
          <defs>
            <pattern
              id="map-dots"
              width="22"
              height="22"
              patternUnits="userSpaceOnUse"
            >
              <circle cx="2" cy="2" r="1.2" fill="#6B7280" />
            </pattern>
          </defs>
          <rect width="800" height="440" fill="url(#map-dots)" />
        </svg>

        {/* river */}
        <svg
          className="absolute inset-0 w-full h-full"
          viewBox="0 0 800 440"
          preserveAspectRatio="none"
          aria-hidden
        >
          <path
            d="M 100 0 C 180 90, 90 180, 200 240 S 320 340, 380 440"
            stroke="#9CB6C8"
            strokeOpacity="0.55"
            strokeWidth="14"
            fill="none"
            strokeLinecap="round"
          />
        </svg>

        {/* park blobs */}
        <div
          className="absolute rounded-full bg-sage/25"
          style={{ left: "42%", top: "46%", width: 120, height: 80 }}
        />
        <div
          className="absolute rounded-full bg-sage/20"
          style={{ left: "72%", top: "18%", width: 90, height: 70 }}
        />

        {/* pins */}
        {pins.map((r, i) => (
          <div key={r.license_id} className={`absolute ${PIN_POSITIONS[i]}`}>
            <div
              className="w-[14px] h-[14px] rounded-full border-2 border-white"
              style={{
                background: TIER_HEX[r.risk_tier],
                boxShadow: "0 2px 6px rgba(43,50,57,0.18)",
              }}
            />
          </div>
        ))}

        {/* featured callout */}
        {featured && (
          <div className="absolute" style={{ left: "50%", top: "32%" }}>
            <div className="rounded-2xl bg-card soft-shadow-lg px-4 py-3 -translate-x-1/2 translate-y-3 w-[240px] border border-line">
              <div className="flex items-center gap-2 mb-1">
                <TierPill tier={featured.risk_tier} size="sm" />
                <span className="num text-[14px] font-medium">
                  {featured.risk_score.toFixed(2)}
                </span>
              </div>
              <div className="font-semibold text-[14px] leading-tight">
                {featured.dba_name}
              </div>
              <div className="text-[11.5px] text-muted">
                {featured.address}
              </div>
              <Link
                href={`/restaurant/${featured.license_id}`}
                className="text-[12px] text-teal underline mt-1.5 inline-block"
              >
                Open profile →
              </Link>
            </div>
          </div>
        )}

        {/* legend */}
        <div className="absolute bottom-4 right-4 rounded-xl bg-white/85 backdrop-blur px-3 py-2 text-[11px] soft-shadow space-y-1">
          <div className="text-muted text-[10px] tracking-widest uppercase mb-1">
            Tier
          </div>
          {(
            [
              { tier: "Low", hex: "#7A8F6A" },
              { tier: "Moderate", hex: "#D4A571" },
              { tier: "Elevated", hex: "#DA8A6C" },
              { tier: "High", hex: "#B8634A" },
            ] as const
          ).map((t) => (
            <div key={t.tier} className="flex items-center gap-2">
              <span
                className="rounded-full border border-white"
                style={{
                  background: t.hex,
                  width: 8,
                  height: 8,
                  boxShadow: "0 0 0 1.5px white",
                }}
              />
              {t.tier}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

/**
 * Sidebar variant used on the Home page — same restaurants, presented as a
 * scrollable card list. Renders to the right of the map.
 */
export function NearbyList({ restaurants }: { restaurants: RestaurantScore[] }) {
  const top = restaurants.slice(0, 5);
  return (
    <aside className="rounded-3xl bg-card border border-line soft-shadow p-5 h-full">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-semibold tracking-tight">Nearby &amp; noteworthy</h2>
        <span className="text-[11px] text-muted">
          {top.length} of 28,047
        </span>
      </div>
      <ul className="space-y-3">
        {top.map((r) => (
          <li
            key={r.license_id}
            className="rounded-2xl border border-line hover:bg-cream/60 transition-colors"
          >
            <Link
              href={`/restaurant/${r.license_id}`}
              className="flex items-start gap-3 p-3"
            >
              <div
                className={`num text-[24px] font-medium leading-none mt-0.5 ${TIER_TEXT_CLASS[r.risk_tier]}`}
              >
                {r.risk_score.toFixed(2)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold leading-tight truncate">
                  {r.dba_name}
                </div>
                <div className="text-[12px] text-muted mt-0.5 truncate">
                  {r.address}
                </div>
                <div className="flex items-center gap-2 mt-2">
                  <TierPill tier={r.risk_tier} size="sm" />
                  <TrendIndicator slope={r.trend_slope_90d} />
                </div>
              </div>
            </Link>
          </li>
        ))}
      </ul>
      <Link
        href="/all"
        className="block text-center text-[13px] mt-4 text-teal hover:underline"
      >
        See all restaurants →
      </Link>
    </aside>
  );
}
