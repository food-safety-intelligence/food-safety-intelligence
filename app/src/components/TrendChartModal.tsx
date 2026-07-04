"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Minus, Plus, RotateCcw, X } from "lucide-react";
import { TrendChart, type TrendPoint } from "@/components/TrendChart";
import { applyTrendPan, applyTrendZoom, clampFrac } from "@/lib/utils";

/**
 * Enlarged, zoomable view of the detail-page trend chart. The inline ScoreCard
 * chart stays the at-a-glance widget; clicking "Enlarge" opens this overlay with
 * the same trajectory at a readable size, where dense histories (long-running
 * establishments hit the export's per-license event cap) can be inspected.
 *
 * It renders the SAME `TrendChart` — so the last-window trend band, the
 * result-on-hover tooltip, and the neutral-line / header-direction coupling
 * (DR 0011) are identical to the inline chart, never a divergent second view.
 * Zoom only narrows the visible time range; it never changes which points the
 * slope is fit over.
 *
 * Interaction: scroll wheel / pinch zooms (toward the pointer); dragging pans;
 * clicking a dot opens that inspection's record in a new tab; the +/- and reset
 * buttons are the keyboard-and-touch-friendly zoom equivalent. Pointer/wheel
 * handlers are attached natively so the wheel listener can be non-passive
 * (preventDefault the page scroll). A press only becomes a pan once it moves
 * past a small threshold, so a plain click still reaches a dot; the trailing
 * click after a real drag is swallowed so panning never navigates.
 */

// A press must move this many pixels before it counts as a pan (below it, the
// press is treated as a click so dots stay clickable).
const DRAG_THRESHOLD = 5;

export function TrendChartModal({
  onClose,
  points,
  slope,
  windowSize,
  trendBadge,
  referenceScore,
}: {
  onClose: () => void;
  points: TrendPoint[];
  slope: number | null;
  windowSize?: number;
  /** The header Improving/Worsening/Stable badge, reused so direction matches. */
  trendBadge: ReactNode;
  /** Headline production risk_score (Model 1) — the chart's reference line. */
  referenceScore?: number;
}) {
  const measureRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  // Set true when a drag happens so the trailing click (which the browser fires
  // on pointerup) is swallowed instead of navigating from whatever dot it lands on.
  const suppressClickRef = useRef(false);

  const [chartW, setChartW] = useState(640);
  // Visible window as [start, end] fractions of the full time span. [0,1] = all.
  const [frac, setFrac] = useState<[number, number]>([0, 1]);

  // Full data time range (epoch ms) → maps the window fractions to a `view`.
  const sorted = [...points].sort((a, b) => a.date.localeCompare(b.date));
  const t0 = sorted.length ? Date.parse(sorted[0].date) : 0;
  const t1 = sorted.length ? Date.parse(sorted[sorted.length - 1].date) : 1;
  const fullSpan = t1 - t0 || 1;
  const view = { start: t0 + frac[0] * fullSpan, end: t0 + frac[1] * fullSpan };

  const isZoomed = frac[1] - frac[0] < 0.999;
  const visibleCount = sorted.filter((p) => {
    const t = Date.parse(p.date);
    return t >= view.start - 1 && t <= view.end + 1;
  }).length;

  const chartH = Math.round(clampFrac(chartW * 0.52, 240, 380));

  // Open a clicked dot's inspection record in a NEW tab (deep-linked to the row
  // via the URL hash; the detail page scrolls + highlights it on load).
  const openRecord = (p: TrendPoint) => {
    if (!p.anchorId || typeof window === "undefined") return;
    const url = `${window.location.pathname}${window.location.search}#${p.anchorId}`;
    window.open(url, "_blank", "noopener,noreferrer");
  };

  // Move focus to the close button on open (the modal is only mounted while open).
  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  // Esc closes; lock background scroll while open.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  // Track the available width so the chart fills the panel responsively.
  useEffect(() => {
    const el = measureRef.current;
    if (!el) return;
    const measure = () => setChartW(Math.max(280, Math.floor(el.clientWidth)));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Native wheel / pointer wiring for zoom + pan (non-passive wheel; no JSX
  // interaction handlers on the chart surface).
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;

    const pointers = new Map<number, { x: number; y: number }>();
    let startX = 0;
    let startY = 0;
    let dragging = false;
    let lastPanX = 0;
    let lastDist = 0;

    const dist = () => {
      const [a, b] = [...pointers.values()];
      return Math.hypot(a.x - b.x, a.y - b.y);
    };
    const midX = () => {
      const [a, b] = [...pointers.values()];
      return (a.x + b.x) / 2;
    };

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const focus = clampFrac((e.clientX - rect.left) / rect.width, 0, 1);
      const factor = e.deltaY < 0 ? 0.85 : 1 / 0.85;
      setFrac(([s, end]) => applyTrendZoom(s, end, focus, factor));
    };
    const onDown = (e: PointerEvent) => {
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size === 1) {
        // Don't capture yet — a plain click must still reach a dot. Capture only
        // once the press crosses the drag threshold (in onMove).
        startX = e.clientX;
        startY = e.clientY;
        lastPanX = e.clientX;
        dragging = false;
        suppressClickRef.current = false;
      } else if (pointers.size === 2) {
        // A pinch is a gesture, not a tap — swallow any trailing click so a
        // finger lifting over a dot doesn't open its record.
        dragging = true;
        suppressClickRef.current = true;
        lastDist = dist();
        el.setPointerCapture(e.pointerId);
      }
    };
    const onMove = (e: PointerEvent) => {
      if (!pointers.has(e.pointerId)) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      const rect = el.getBoundingClientRect();
      if (pointers.size >= 2) {
        const d = dist();
        if (lastDist > 0) {
          const focus = clampFrac((midX() - rect.left) / rect.width, 0, 1);
          setFrac(([s, end]) => applyTrendZoom(s, end, focus, lastDist / d));
        }
        lastDist = d;
        return;
      }
      // Single pointer: promote to a pan only past the threshold, so short
      // presses stay clicks. Once panning, suppress the trailing click.
      if (!dragging) {
        if (Math.hypot(e.clientX - startX, e.clientY - startY) < DRAG_THRESHOLD) return;
        dragging = true;
        suppressClickRef.current = true;
        el.setPointerCapture(e.pointerId);
        lastPanX = e.clientX;
      }
      const dx = e.clientX - lastPanX;
      lastPanX = e.clientX;
      setFrac(([s, end]) => applyTrendPan(s, end, dx, rect.width));
    };
    const onUp = (e: PointerEvent) => {
      pointers.delete(e.pointerId);
      if (pointers.size < 2) lastDist = 0;
      if (pointers.size === 1) lastPanX = [...pointers.values()][0].x;
      if (pointers.size === 0) dragging = false;
    };

    el.addEventListener("wheel", onWheel, { passive: false });
    el.addEventListener("pointerdown", onDown);
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerup", onUp);
    el.addEventListener("pointercancel", onUp);
    return () => {
      el.removeEventListener("wheel", onWheel);
      el.removeEventListener("pointerdown", onDown);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerup", onUp);
      el.removeEventListener("pointercancel", onUp);
    };
  }, []);

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      {/* Backdrop — click to dismiss. */}
      <button
        aria-label="Close enlarged trend chart"
        onClick={onClose}
        className="absolute inset-0 bg-ink/40 cursor-default"
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Risk trend, enlarged"
        className="relative z-10 w-full max-w-3xl rounded-2xl border border-line bg-card soft-shadow-lg p-5 sm:p-6"
      >
        <div className="flex items-center justify-between gap-3 mb-4">
          <div className="flex items-center gap-3 min-w-0">
            <span className="text-2xs tracking-widest uppercase text-muted">Recent trend</span>
            {trendBadge}
          </div>
          <button
            ref={closeRef}
            onClick={onClose}
            aria-label="Close enlarged trend chart"
            className="inline-flex items-center justify-center w-9 h-9 rounded-full text-muted hover:bg-ink/5 hover:text-ink transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
          >
            <X className="w-5 h-5" strokeWidth={2} />
          </button>
        </div>

        <div ref={measureRef} className="w-full">
          <div
            ref={wrapRef}
            className="mx-auto select-none"
            style={{ width: chartW, touchAction: "none", cursor: "grab" }}
            // Swallow the click the browser fires at the end of a drag so panning
            // over a dot never navigates. Capture phase → runs before the dot.
            onClickCapture={(e) => {
              if (suppressClickRef.current) {
                suppressClickRef.current = false;
                e.preventDefault();
                e.stopPropagation();
              }
            }}
          >
            <TrendChart
              points={points}
              slope={slope}
              windowSize={windowSize}
              view={view}
              width={chartW}
              height={chartH}
              onPointActivate={openRecord}
              activateHint="opens this inspection in a new tab"
              referenceScore={referenceScore}
            />
          </div>
        </div>

        {/* Controls + caption. */}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setFrac(([s, e]) => applyTrendZoom(s, e, 0.5, 1 / 0.7))}
              aria-label="Zoom out"
              className="inline-flex items-center justify-center w-9 h-9 rounded-lg border border-line text-ink hover:bg-ink/5 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              <Minus className="w-4 h-4" strokeWidth={2} />
            </button>
            <button
              onClick={() => setFrac(([s, e]) => applyTrendZoom(s, e, 0.5, 0.7))}
              aria-label="Zoom in"
              className="inline-flex items-center justify-center w-9 h-9 rounded-lg border border-line text-ink hover:bg-ink/5 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              <Plus className="w-4 h-4" strokeWidth={2} />
            </button>
            <button
              onClick={() => setFrac([0, 1])}
              disabled={!isZoomed}
              aria-label="Reset zoom"
              className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg border border-line text-xs font-medium text-ink hover:bg-ink/5 transition-colors disabled:opacity-40 disabled:hover:bg-transparent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              <RotateCcw className="w-3.5 h-3.5" strokeWidth={2} />
              Reset
            </button>
          </div>
          <p className="text-2xs text-muted">
            {isZoomed
              ? `Showing ${visibleCount} of ${sorted.length} scored inspections`
              : "Scroll or pinch to zoom · drag to pan"}
          </p>
        </div>

        <p className="text-2xs text-muted mt-3 leading-snug">
          Each point is the trend estimate — the model&apos;s risk read with that inspection&apos;s
          own result removed, so the line shows direction, not a second risk number. The dashed line
          marks the headline risk score, which does count the latest result and can differ. The
          shaded band is the recent window that sets the trend; zooming changes only what you see.
          Select a point to open that inspection&apos;s record in a new tab.
        </p>
      </div>
    </div>
  );
}
