"use client";

import { useEffect, useRef, useState } from "react";
import { BarChart3, Check, Code2, Copy, Download, Minus, Plus, RotateCcw, X } from "lucide-react";
import { ModalOverlay } from "@/components/ModalOverlay";
import { useChartAttachment } from "@/components/use-chart-attachment";
import { clampFrac } from "@/lib/utils";
import type { ChartAttachment } from "@/lib/chart-attachments";

const MAX_SCALE = 8;

type Transform = { scale: number; x: number; y: number };
const IDENTITY: Transform = { scale: 1, x: 0, y: 0 };

// Zoom toward a point (cx, cy given as offsets from the container centre), keeping
// that point fixed on screen. Snapping back to scale 1 recentres the image.
function zoomAt(prev: Transform, factor: number, cx: number, cy: number): Transform {
  const scale = clampFrac(prev.scale * factor, 1, MAX_SCALE);
  if (scale === 1) return IDENTITY;
  const k = scale / prev.scale;
  return { scale, x: cx - (cx - prev.x) * k, y: cy - (cy - prev.y) * k };
}

/**
 * Enlarged, zoomable view of a generated chart image. The inline `ChartCard`
 * stays the at-a-glance widget; expanding opens this overlay with the same
 * image/script toggle and download/copy controls, plus wheel / pinch zoom and
 * drag-to-pan for reading a dense chart. Composes the shared `ModalOverlay`
 * (backdrop, Esc, scroll-lock, focus) and the shared `useChartAttachment` state.
 */
export function ChartImageModal({
  attachment,
  onClose,
}: {
  attachment: ChartAttachment;
  onClose: () => void;
}) {
  const { title, imageUrl } = attachment;
  const chart = useChartAttachment(attachment);
  const { view, showImage, showScript, script, scriptError, loadingScript, copied } = chart;

  const closeRef = useRef<HTMLButtonElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [t, setT] = useState<Transform>(IDENTITY);
  const isZoomed = t.scale > 1;

  // Reset the pan/zoom whenever we leave the image view, so returning to it starts clean.
  const resetZoom = () => setT(IDENTITY);

  // Native wheel / pointer wiring for zoom + pan (non-passive wheel so it can
  // preventDefault the page scroll). Only active in the image view.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el || view !== "image") return;

    const pointers = new Map<number, { x: number; y: number }>();
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    let lastDist = 0;

    const centreOffset = (clientX: number, clientY: number) => {
      const rect = el.getBoundingClientRect();
      return { cx: clientX - rect.left - rect.width / 2, cy: clientY - rect.top - rect.height / 2 };
    };
    const dist = () => {
      const [a, b] = [...pointers.values()];
      return Math.hypot(a.x - b.x, a.y - b.y);
    };
    const mid = () => {
      const [a, b] = [...pointers.values()];
      return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    };

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const { cx, cy } = centreOffset(e.clientX, e.clientY);
      const factor = e.deltaY < 0 ? 1 / 0.85 : 0.85;
      setT((prev) => zoomAt(prev, factor, cx, cy));
    };
    const onDown = (e: PointerEvent) => {
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size === 2) {
        lastDist = dist();
      }
      lastX = e.clientX;
      lastY = e.clientY;
      dragging = true;
      el.setPointerCapture(e.pointerId);
    };
    const onMove = (e: PointerEvent) => {
      if (!pointers.has(e.pointerId)) return;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size >= 2) {
        const d = dist();
        if (lastDist > 0) {
          const m = mid();
          const { cx, cy } = centreOffset(m.x, m.y);
          setT((prev) => zoomAt(prev, d / lastDist, cx, cy));
        }
        lastDist = d;
        return;
      }
      if (!dragging) return;
      const dx = e.clientX - lastX;
      const dy = e.clientY - lastY;
      lastX = e.clientX;
      lastY = e.clientY;
      // Only pan when zoomed in (at 1x the image fills the frame, nothing to pan to).
      setT((prev) => (prev.scale > 1 ? { ...prev, x: prev.x + dx, y: prev.y + dy } : prev));
    };
    const onUp = (e: PointerEvent) => {
      pointers.delete(e.pointerId);
      if (pointers.size < 2) lastDist = 0;
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
  }, [view]);

  return (
    <ModalOverlay
      onClose={onClose}
      label={`${title}, enlarged`}
      backdropLabel="Close enlarged chart"
      maxWidthClass="max-w-4xl"
      initialFocusRef={closeRef}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-3 mb-4">
        <p className="text-sm font-medium text-ink truncate min-w-0">{title}</p>
        <button
          ref={closeRef}
          onClick={onClose}
          aria-label="Close enlarged chart"
          className="inline-flex flex-none items-center justify-center w-9 h-9 rounded-full text-muted hover:bg-ink/5 hover:text-ink transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
        >
          <X className="w-5 h-5" strokeWidth={2} />
        </button>
      </div>

      {/* Body */}
      {view === "image" ? (
        <div
          ref={wrapRef}
          className="w-full h-[60vh] overflow-hidden rounded-lg border border-line bg-white select-none flex items-center justify-center"
          style={{ touchAction: "none", cursor: isZoomed ? "grab" : "default" }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element -- data/presigned URL, not a static asset */}
          <img
            src={imageUrl}
            alt={title}
            draggable={false}
            className="max-w-full max-h-full object-contain"
            style={{
              transform: `translate(${t.x}px, ${t.y}px) scale(${t.scale})`,
              transformOrigin: "center",
            }}
          />
        </div>
      ) : (
        <div className="relative">
          <div className="absolute right-2 top-2 z-10">
            <button
              type="button"
              onClick={chart.handleCopy}
              aria-label={copied ? "Script copied to clipboard" : "Copy script to clipboard"}
              className="inline-flex items-center justify-center h-8 w-8 rounded-lg bg-card/90 border border-line text-muted hover:text-ink hover:border-teal transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              {copied ? (
                <Check className="w-4 h-4 text-sage-strong" strokeWidth={2} />
              ) : (
                <Copy className="w-4 h-4" strokeWidth={2} />
              )}
            </button>
          </div>
          {scriptError ? (
            <p className="text-sm text-terra px-3 py-6">Could not load the script for this chart.</p>
          ) : (
            <pre
              className="h-[60vh] overflow-auto rounded-lg border border-line bg-ink/[0.03] text-xs leading-relaxed text-ink p-3 pr-12"
              aria-busy={loadingScript}
            >
              <code>{script ?? (loadingScript ? "Loading script…" : "")}</code>
            </pre>
          )}
        </div>
      )}

      {/* Controls */}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        {/* Toggle group */}
        <div
          role="group"
          aria-label="Show chart image or its script"
          className="inline-flex rounded-lg border border-line overflow-hidden text-xs"
        >
          <button
            type="button"
            onClick={() => {
              resetZoom();
              showImage();
            }}
            aria-pressed={view === "image"}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 transition-colors ${
              view === "image" ? "bg-sage/15 text-ink font-medium" : "bg-card text-muted hover:text-ink"
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5" strokeWidth={2} aria-hidden />
            Chart
          </button>
          <button
            type="button"
            onClick={showScript}
            aria-pressed={view === "script"}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 border-l border-line transition-colors ${
              view === "script" ? "bg-sage/15 text-ink font-medium" : "bg-card text-muted hover:text-ink"
            }`}
          >
            <Code2 className="w-3.5 h-3.5" strokeWidth={2} aria-hidden />
            Script
          </button>
        </div>

        {view === "image" ? (
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setT((prev) => zoomAt(prev, 0.7, 0, 0))}
              aria-label="Zoom out"
              className="inline-flex items-center justify-center w-9 h-9 rounded-lg border border-line text-ink hover:bg-ink/5 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              <Minus className="w-4 h-4" strokeWidth={2} />
            </button>
            <button
              onClick={() => setT((prev) => zoomAt(prev, 1 / 0.7, 0, 0))}
              aria-label="Zoom in"
              className="inline-flex items-center justify-center w-9 h-9 rounded-lg border border-line text-ink hover:bg-ink/5 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              <Plus className="w-4 h-4" strokeWidth={2} />
            </button>
            <button
              onClick={resetZoom}
              disabled={!isZoomed}
              aria-label="Reset zoom"
              className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg border border-line text-xs font-medium text-ink hover:bg-ink/5 transition-colors disabled:opacity-40 disabled:hover:bg-transparent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              <RotateCcw className="w-3.5 h-3.5" strokeWidth={2} />
              Reset
            </button>
            <button
              onClick={chart.handleDownload}
              className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg border border-line text-xs text-ink hover:bg-ink/5 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              <Download className="w-3.5 h-3.5" strokeWidth={2} aria-hidden />
              Download
            </button>
          </div>
        ) : (
          <button
            onClick={chart.handleCopy}
            aria-label={copied ? "Script copied to clipboard" : "Copy script to clipboard"}
            className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg border border-line text-xs text-ink hover:bg-ink/5 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
          >
            {copied ? (
              <Check className="w-3.5 h-3.5 text-sage-strong" strokeWidth={2} aria-hidden />
            ) : (
              <Copy className="w-3.5 h-3.5" strokeWidth={2} aria-hidden />
            )}
            {copied ? "Copied" : "Copy"}
          </button>
        )}
      </div>

      {view === "image" && (
        <p className="text-2xs text-muted mt-3">
          {isZoomed ? "Drag to pan · scroll or pinch to zoom" : "Scroll or pinch to zoom"}
        </p>
      )}
    </ModalOverlay>
  );
}
