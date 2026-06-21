import { ArrowDown, ArrowUp, Minus, TrendingDown, TrendingUp } from "lucide-react";
import type { PopulationStats, RestaurantScore } from "@/lib/scores";
import { trendDirection } from "@/lib/scores";
import { iconForFeature } from "@/lib/driver-icons";
import { cn } from "@/lib/utils";
import { ArcGauge } from "@/components/ArcGauge";
import { TierPill } from "@/components/TierPill";
import { TrendChart } from "@/components/TrendChart";

const TREND_META = {
  worsening: {
    label: "Worsening",
    Icon: TrendingUp,
    bg: "bg-terra/15",
    fg: "text-terra",
  },
  improving: {
    label: "Improving",
    Icon: TrendingDown,
    bg: "bg-sage/15",
    fg: "text-sage",
  },
  stable: {
    label: "Stable",
    Icon: Minus,
    bg: "bg-muted/10",
    fg: "text-muted",
  },
} as const;

/**
 * Centerpiece score panel on the detail page. The arc gauge is the design's
 * primary visual; below it sits a minimal 90-day trend chart reconstructed
 * from the linear slope (we don't ship per-restaurant history in scores.json).
 */
export function ScoreCard({
  restaurant,
  populationStats,
}: {
  restaurant: RestaurantScore;
  populationStats?: PopulationStats;
}) {
  const slope = restaurant.trend_slope_90d;
  const dir = trendDirection(slope);
  const trend = TREND_META[dir];
  const TrendIcon = trend.Icon;
  const sign = slope === null ? "" : slope > 0 ? "+" : slope < 0 ? "−" : "";

  // Percentile rank reads honestly across every tier. "Top X%" alone gets
  // misleading at the extremes (e.g. "top 0.00%" for the highest-scoring
  // restaurant, "top 78%" for a low-risk place where "top" misframes it).
  // "Ranks higher than X%" works for both directions.
  const percentile = restaurant.percentile_rank ?? null;
  const medianScore = populationStats?.median ?? null;

  // Quick-glance summary of the single biggest driver, beside the gauge — so
  // the dominant reason is visible without scrolling to the full driver panel.
  const topDriver = restaurant.top_drivers[0] ?? null;
  const topRaises = topDriver ? topDriver.shap > 0 : false;
  const TopIcon = topDriver ? iconForFeature(topDriver.feature) : null;

  return (
    <div className="rounded-3xl bg-card border border-line soft-shadow-lg p-7">
      <div className="text-[11px] tracking-widest uppercase text-muted">
        Predicted 180-day risk
      </div>

      {/* Arc gauge centerpiece */}
      <div className="flex justify-center mt-3">
        <ArcGauge
          score={restaurant.risk_score}
          tier={restaurant.risk_tier}
          size={240}
        />
      </div>

      <div className="flex justify-center mt-1">
        <TierPill tier={restaurant.risk_tier} />
      </div>

      {topDriver && TopIcon && (
        <div className="flex flex-col items-center gap-1 mt-3">
          <span className="text-[10.5px] tracking-widest uppercase text-muted">
            Top factor
          </span>
          <span
            title={topDriver.label}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 max-w-full text-[12.5px] font-medium",
              topRaises ? "bg-terra/10 text-terra" : "bg-sage/15 text-sage",
            )}
          >
            <TopIcon className="w-3.5 h-3.5 shrink-0" strokeWidth={2} />
            <span className="truncate">{topDriver.label}</span>
            {topRaises ? (
              <ArrowUp className="w-3.5 h-3.5 shrink-0" strokeWidth={2.5} />
            ) : (
              <ArrowDown className="w-3.5 h-3.5 shrink-0" strokeWidth={2.5} />
            )}
          </span>
        </div>
      )}

      <p className="text-[14px] text-muted leading-relaxed mt-4 text-center">
        {medianScore !== null ? (
          <>
            A typical Chicago restaurant scores{" "}
            <span className="num font-medium text-ink">
              {medianScore.toFixed(2)}
            </span>
            .{" "}
          </>
        ) : null}
        {percentile !== null ? (
          <>
            This restaurant ranks higher than{" "}
            <span
              className="serif italic text-terra"
              style={{ fontSize: "1.15em" }}
            >
              {/* Floor instead of round — for the top-scoring restaurant the
                  raw value is ~99.996, which .toFixed(1) rounds to "100.0%"
                  and reads as a bug ("higher than 100%" is paradoxical). */}
              {(Math.floor(percentile * 10) / 10).toFixed(1)}%
            </span>{" "}
            of currently active food licenses.
          </>
        ) : (
          <>Compared against all currently active food licenses in Chicago.</>
        )}
      </p>

      {/* Trend block */}
      <div className="mt-6 pt-5 border-t border-line">
        <div className="flex items-center justify-between mb-2">
          <div className="text-[11px] tracking-widest uppercase text-muted">
            90-day trend
          </div>
          <span
            className={`inline-flex items-center gap-1.5 text-[12px] font-medium ${trend.fg}`}
          >
            <TrendIcon className="w-3.5 h-3.5" strokeWidth={2.5} />
            {slope === null ? "Insufficient history" : trend.label}
          </span>
        </div>

        <div className="flex justify-center">
          <TrendChart
            score={restaurant.risk_score}
            slope={slope}
            typicalScore={medianScore}
          />
        </div>

        {slope !== null && (
          <div className="num text-[12px] text-muted mt-2 text-center">
            {sign}
            {Math.abs(slope).toFixed(4)} / day
            {restaurant.trend_ci_low != null && restaurant.trend_ci_high != null
              ? ` · 95% CI [${restaurant.trend_ci_low.toFixed(4)}, ${restaurant.trend_ci_high.toFixed(4)}]`
              : ""}
          </div>
        )}
      </div>
    </div>
  );
}
