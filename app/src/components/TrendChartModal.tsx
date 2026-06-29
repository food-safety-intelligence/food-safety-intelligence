"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Minus, Plus, RotateCcw, X } from "lucide-react";
import { TrendChart, type TrendPoint } from "@/components/TrendChart";

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
 * the +/- and reset buttons are the keyboard-and-touch-friendly equivalent.
 * Pointer/wheel handlers are attached natively so the wheel listener can be
 * non-passive (preventDefault the page scroll) and so the interaction surface
 * carries no JSX click handlers.
 */

// Floor on the visible fraction of the full time span — caps zoom at ~25x so a
// dense history can be opened up without zooming past a couple of points.
const MIN_WIDTH = 0.04;

function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v;
}

// Narrow the [start,end] window (fractions of the full span) toward `focus`
// (0..1 across the plot), keeping the focused instant fixed under the pointer.
function applyZoom(
  start: number,
  end: number,
  focus: number,
  factor: number,
): [number, number] {
  const width = end - start;
  const domainFrac = start + focus * width;
  const nw = clamp(width * factor, MIN_WIDTH, 1);
  const ns = clamp(domainFrac - focus * nw, 0, 1 - nw);
  return [ns, ns + nw];
}

// Slide the window by a pixel delta, holding its width.
function applyPan(
  start: number,
  end: number,
  dxPx: number,
  rectW: number,
): [number, number] {
  const width = end - start;
  const dFrac = (dxPx / rectW) * width;
  const ns = clamp(start - dFrac, 0, 1 - width);
  return [ns, ns + width];
}

export function TrendChartModal({
  onClose,
  points,
  slope,
  windowSize,
  trendBadge,
}: {
  onClose: () => void;
  points: TrendPoint[];
  slope: number | null;
  windowSize?: number;
  /** The header Improving/Worsening/Stable badge, reused so direction matches. */
  trendBadge: ReactNode;
}) {
  const measureRef = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

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

  const chartH = Math.round(clamp(chartW * 0.52, 240, 380));

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
      const focus = clamp((e.clientX - rect.left) / rect.width, 0, 1);
      const factor = e.deltaY < 0 ? 0.85 : 1 / 0.85;
      setFrac(([s, end]) => applyZoom(s, end, focus, factor));
    };
    const onDown = (e: PointerEvent) => {
      el.setPointerCapture(e.pointerId);
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size === 1) lastPanX = e.clientX;
      else if (pointers.size === 2) lastDist = dist();
    };
    const onMove = (e: PointerEvent) => {
      if (!pointers.has(e.pointerId)) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      const rect = el.getBoundingClientRect();
      if (pointers.size >= 2) {
        const d = dist();
        if (lastDist > 0) {
          const focus = clamp((midX() - rect.left) / rect.width, 0, 1);
          setFrac(([s, end]) => applyZoom(s, end, focus, lastDist / d));
        }
        lastDist = d;
      } else if (pointers.size === 1) {
        const dx = e.clientX - lastPanX;
        lastPanX = e.clientX;
        setFrac(([s, end]) => applyPan(s, end, dx, rect.width));
      }
    };
    const onUp = (e: PointerEvent) => {
      pointers.delete(e.pointerId);
      if (pointers.size < 2) lastDist = 0;
      if (pointers.size === 1) lastPanX = [...pointers.values()][0].x;
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
          >
            <TrendChart
              points={points}
              slope={slope}
              windowSize={windowSize}
              view={view}
              width={chartW}
              height={chartH}
            />
          </div>
        </div>

        {/* Controls + caption. */}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setFrac(([s, e]) => applyZoom(s, e, 0.5, 1 / 0.7))}
              aria-label="Zoom out"
              className="inline-flex items-center justify-center w-9 h-9 rounded-lg border border-line text-ink hover:bg-ink/5 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              <Minus className="w-4 h-4" strokeWidth={2} />
            </button>
            <button
              onClick={() => setFrac(([s, e]) => applyZoom(s, e, 0.5, 0.7))}
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
          Predicted risk across all scored inspections; the shaded band is the recent window that
          sets the trend. Zooming changes only what you see — not which visits set the direction.
        </p>
      </div>
    </div>
  );
}
