"use client";

import { useRef, useState } from "react";
import { Info, Maximize2, Minus, TrendingDown, TrendingUp } from "lucide-react";
import type { InspectionEvent } from "@/lib/scores";
import { trendDirection } from "@/lib/scores";
import { CITY_CONFIG } from "@/lib/city";
import { useCity } from "@/components/CityContext";
import { Tooltip } from "@/components/Tooltip";
import { TrendChart } from "@/components/TrendChart";
import { TrendChartModal } from "@/components/TrendChartModal";

const TREND_META = {
  worsening: { label: "Worsening", Icon: TrendingUp, fg: "text-terra" },
  improving: { label: "Improving", Icon: TrendingDown, fg: "text-sage" },
  stable: { label: "Stable", Icon: Minus, fg: "text-muted" },
} as const;

// How many of the most-recent scored visits the slope is fit over (DR 0011);
// the chart shades these as the trend window.
const TREND_POINTS = 5;

/**
 * The "Recent trend" section of the ScoreCard: header + direction badge, the
 * inline trajectory chart, and an "Enlarge" control that opens the zoomable
 * modal for dense histories. Client component because it owns the modal's
 * open state; the rest of the ScoreCard stays a server component.
 */
export function TrendPanel({
  slope,
  history,
}: {
  slope: number | null;
  /** Inspection history (newest-first); the scored events become chart points. */
  history: InspectionEvent[];
}) {
  const { city } = useCity();
  const [open, setOpen] = useState(false);
  const enlargeRef = useRef<HTMLButtonElement>(null);

  const dir = trendDirection(slope, CITY_CONFIG[city].trendStableBand);
  const trend = TREND_META[dir];
  const TrendIcon = trend.Icon;

  // Plot the full forecast trajectory — every inspection carrying a forecast
  // score — oldest -> newest (history is newest-first).
  const scoredPoints = history
    .filter((e): e is InspectionEvent & { score: number } => e.score != null)
    .map((e) => ({ date: e.date, score: e.score, result: e.result }))
    .reverse();
  const trendWindow = Math.min(TREND_POINTS, scoredPoints.length);

  // One gate for the header label and the chart so they never disagree: a trend
  // needs a (forward-looking) slope AND at least two points to draw.
  const hasTrend = slope !== null && scoredPoints.length >= 2;

  const badge = (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${trend.fg}`}>
      <TrendIcon className="w-3.5 h-3.5" strokeWidth={2.5} />
      {hasTrend ? trend.label : "Insufficient history"}
    </span>
  );

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <span className="text-2xs tracking-widest uppercase text-muted">Recent trend</span>
          <Tooltip content="How the recent trend is calculated">
            <a
              href="/how-it-works#recent-trend"
              aria-label="How the recent trend is calculated"
              className="text-muted/70 hover:text-ink transition-colors"
            >
              <Info className="w-3.5 h-3.5" strokeWidth={2} />
            </a>
          </Tooltip>
        </div>
        {badge}
      </div>

      <div className="flex justify-center">
        <TrendChart points={hasTrend ? scoredPoints : []} slope={slope} windowSize={trendWindow} />
      </div>

      {hasTrend && (
        <div className="mt-2 flex justify-center">
          <button
            ref={enlargeRef}
            onClick={() => setOpen(true)}
            aria-haspopup="dialog"
            className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-2xs font-medium text-muted hover:text-ink hover:bg-ink/5 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
          >
            <Maximize2 className="w-3.5 h-3.5" strokeWidth={2} />
            Enlarge
          </button>
        </div>
      )}

      <p className="text-2xs text-muted mt-2 text-center leading-snug">
        Predicted risk across all scored inspections; the shaded band is the recent window that sets
        the trend.
      </p>

      {hasTrend && open && (
        <TrendChartModal
          onClose={() => {
            setOpen(false);
            // Return focus to the trigger so keyboard users aren't dropped.
            enlargeRef.current?.focus();
          }}
          points={scoredPoints}
          slope={slope}
          windowSize={trendWindow}
          trendBadge={badge}
        />
      )}
    </div>
  );
}
