"use client";

import { useMemo, useRef, useState } from "react";
import { Info, Maximize2, Minus, Plus, RotateCcw, TrendingDown, TrendingUp } from "lucide-react";
import type { InspectionEvent } from "@/lib/scores";
import {
  compareInspectionsNewestFirst,
  INSPECTION_JUMP_EVENT,
  inspectionAnchorId,
  trendDirection,
} from "@/lib/scores";
import { applyTrendZoom } from "@/lib/utils";
import { Tooltip } from "@/components/Tooltip";
import { TrendCaptionLead, TrendChart, type TrendPoint } from "@/components/TrendChart";
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
  riskScore,
}: {
  slope: number | null;
  /** Inspection history (newest-first); the scored events become chart points. */
  history: InspectionEvent[];
  /** Headline production risk_score (Model 1) — drawn as the chart's reference line. */
  riskScore: number;
}) {
  const [open, setOpen] = useState(false);
  const enlargeRef = useRef<HTMLButtonElement>(null);
  // Inline zoom window as [start, end] fractions of the full time span; [0,1] is
  // the full range (the unchanged default). Buttons only — the enlarge modal
  // keeps the wheel/pinch/drag gestures.
  const [frac, setFrac] = useState<[number, number]>([0, 1]);

  const dir = trendDirection(slope);
  const trend = TREND_META[dir];
  const TrendIcon = trend.Icon;

  // Plot the full forecast trajectory — every inspection carrying a forecast
  // score — oldest -> newest (history is newest-first). Each point carries its
  // history-row anchor so clicking a dot can jump to that inspection. Memoised on
  // `history` so the per-render zoom-button clicks don't rebuild the sort + Map.
  const scoredPoints = useMemo<TrendPoint[]>(() => {
    // Newest-first index of every inspection → its timeline anchor, on the same
    // order the timeline sorts by, so a dot's `inspection-<n>` id lands on the
    // matching history row even when dates repeat.
    const anchorIndex = new Map<InspectionEvent, number>();
    [...history].sort(compareInspectionsNewestFirst).forEach((e, i) => anchorIndex.set(e, i));
    return history
      .filter((e): e is InspectionEvent & { score: number } => e.score != null)
      .map((e) => ({
        date: e.date,
        score: e.score,
        result: e.result,
        anchorId: inspectionAnchorId(anchorIndex.get(e) ?? 0),
      }))
      .reverse();
  }, [history]);
  const trendWindow = Math.min(TREND_POINTS, scoredPoints.length);

  // One gate for the header label and the chart so they never disagree: a trend
  // needs a (forward-looking) slope AND at least two points to draw.
  const hasTrend = slope !== null && scoredPoints.length >= 2;

  // Full time range of the trajectory → the zoom window's fractions map onto this
  // to a `view` for the chart. Use min/max of the dates (not the array ends) so
  // this matches TrendChart's own domain regardless of input ordering.
  const times = scoredPoints.map((p) => Date.parse(p.date));
  const t0 = times.length ? Math.min(...times) : 0;
  const t1 = times.length ? Math.max(...times) : 1;
  const fullSpan = t1 - t0 || 1;
  const view = { start: t0 + frac[0] * fullSpan, end: t0 + frac[1] * fullSpan };
  const isZoomed = frac[1] - frac[0] < 0.999;

  // Anchor zoom at the right edge (focus = 1) so zooming keeps the most-recent
  // inspections in view — the part of the trajectory that matters most.
  const zoomIn = () => setFrac(([s, e]) => applyTrendZoom(s, e, 1, 0.7));
  const zoomOut = () => setFrac(([s, e]) => applyTrendZoom(s, e, 1, 1 / 0.7));
  const resetZoom = () => setFrac([0, 1]);

  // Clicking a dot on the inline chart jumps to that inspection in the history
  // timeline on THIS tab: reflect it in the URL (shareable) and fire the in-tab
  // signal the timeline listens for (a same-value hash wouldn't re-fire).
  const jumpToRecord = (p: TrendPoint) => {
    if (!p.anchorId || typeof window === "undefined") return;
    window.history.replaceState(null, "", `#${p.anchorId}`);
    window.dispatchEvent(new CustomEvent(INSPECTION_JUMP_EVENT, { detail: p.anchorId }));
  };

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
        <TrendChart
          points={hasTrend ? scoredPoints : []}
          slope={slope}
          windowSize={trendWindow}
          view={hasTrend && isZoomed ? view : undefined}
          onPointActivate={jumpToRecord}
          activateHint="opens this inspection in the history below"
          referenceScore={riskScore}
        />
      </div>

      {hasTrend && (
        <div className="mt-2 flex items-center justify-center gap-2">
          <div
            className="inline-flex items-center gap-1"
            role="group"
            aria-label="Zoom the trend chart"
          >
            <button
              onClick={zoomOut}
              disabled={!isZoomed}
              aria-label="Zoom out"
              className="inline-flex items-center justify-center w-8 h-8 rounded-md border border-line text-muted hover:text-ink hover:bg-ink/5 transition-colors disabled:opacity-40 disabled:hover:bg-transparent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              <Minus className="w-3.5 h-3.5" strokeWidth={2} />
            </button>
            <button
              onClick={zoomIn}
              aria-label="Zoom in"
              className="inline-flex items-center justify-center w-8 h-8 rounded-md border border-line text-muted hover:text-ink hover:bg-ink/5 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              <Plus className="w-3.5 h-3.5" strokeWidth={2} />
            </button>
            {isZoomed && (
              <button
                onClick={resetZoom}
                aria-label="Reset zoom"
                className="inline-flex items-center justify-center w-8 h-8 rounded-md border border-line text-muted hover:text-ink hover:bg-ink/5 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
              >
                <RotateCcw className="w-3.5 h-3.5" strokeWidth={2} />
              </button>
            )}
          </div>
          <button
            ref={enlargeRef}
            onClick={() => setOpen(true)}
            aria-haspopup="dialog"
            className="inline-flex items-center gap-1.5 rounded-full px-3 h-8 text-2xs font-medium text-muted hover:text-ink hover:bg-ink/5 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
          >
            <Maximize2 className="w-3.5 h-3.5" strokeWidth={2} />
            Enlarge
          </button>
        </div>
      )}

      {/* Only describe the dots + dashed line when they're actually drawn; the
          chart renders its own "not enough history" message otherwise. */}
      {hasTrend && (
        <p className="text-2xs text-muted mt-2 text-center leading-snug">
          <TrendCaptionLead /> Click a point to jump to it below.
        </p>
      )}

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
          referenceScore={riskScore}
        />
      )}
    </div>
  );
}
