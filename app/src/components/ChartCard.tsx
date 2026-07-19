"use client";

import { useState } from "react";
import { BarChart3, Code2, Copy, Check, Download, Maximize2, AlertCircle } from "lucide-react";
import { Tooltip } from "@/components/Tooltip";
import { ChartImageModal } from "@/components/ChartImageModal";
import { useChartAttachment } from "@/components/use-chart-attachment";
import type { ChartAttachment } from "@/lib/chart-attachments";

/**
 * One generated chart inside an agent message: the rendered image, with a bottom
 * toggle to flip to the script that produced it. In the image view a download
 * control sits beside the toggle; in the script view a copy-to-clipboard control
 * sits beside the code. The expand control opens the same chart in a zoomable
 * modal (the enlarge pattern the trend chart uses). Shared state/actions come
 * from `useChartAttachment`.
 */
export function ChartCard({
  attachment,
  compact = false,
}: {
  attachment: ChartAttachment;
  /** Rendered in the fixed-width floating widget, where action labels don't fit
      regardless of viewport — so the button labels stay icon-only. */
  compact?: boolean;
}) {
  // A container-width concern, not a viewport one: `sm:` keys off the viewport,
  // but the widget is ~384px on any screen. `labelCls` hides the button text in
  // the widget, and only shows it at >=sm on the roomy /chat surface.
  const labelCls = compact ? "hidden" : "hidden sm:inline";
  const { title, imageUrl } = attachment;
  const { view, showImage, showScript, script, scriptError, loadingScript, copied, handleDownload, handleCopy } =
    useChartAttachment(attachment);
  const [expanded, setExpanded] = useState(false);

  const panelId = `chart-panel-${attachment.id}`;

  return (
    <div className="w-full rounded-2xl border border-line bg-card soft-shadow overflow-hidden">
      {/* Title — only in the script view. The chart image carries its own title
          (a downloaded PNG needs one), so repeating it above the image is
          redundant; the script view has no visible title, so it shows one here. */}
      {view === "script" && (
        <div className="px-3 pt-2.5 pb-1.5">
          <p className="text-sm font-medium text-ink leading-snug">{title}</p>
        </div>
      )}

      {/* Body: image or script */}
      <div id={panelId} className={view === "image" ? "px-3 pt-3" : "px-3"}>
        {view === "image" ? (
          // eslint-disable-next-line @next/next/no-img-element -- data/presigned URL, not a static asset Next can optimize
          <img
            src={imageUrl}
            alt={title}
            className="w-full h-auto max-h-[60vh] object-contain rounded-lg border border-line bg-white"
          />
        ) : (
          <div className="relative">
            {/* Copy sits next to the script, per spec. */}
            <div className="absolute right-2 top-2 z-10">
              <Tooltip content={copied ? "Copied" : "Copy script"} align="end">
                <button
                  type="button"
                  onClick={handleCopy}
                  aria-label={copied ? "Script copied to clipboard" : "Copy script to clipboard"}
                  className="inline-flex items-center justify-center h-8 w-8 rounded-lg bg-card/90 border border-line text-muted hover:text-ink hover:border-teal transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
                >
                  {copied ? (
                    <Check className="w-4 h-4 text-sage-strong" strokeWidth={2} />
                  ) : (
                    <Copy className="w-4 h-4" strokeWidth={2} />
                  )}
                </button>
              </Tooltip>
            </div>
            {scriptError ? (
              <p className="flex items-center gap-2 text-sm text-terra px-3 py-6">
                <AlertCircle className="w-4 h-4 flex-none" strokeWidth={2} aria-hidden />
                Could not load the script for this chart.
              </p>
            ) : (
              <pre
                className="overflow-x-auto rounded-lg border border-line bg-ink/[0.03] text-2xs leading-relaxed text-ink p-3 pr-12"
                aria-busy={loadingScript}
              >
                <code>{script ?? (loadingScript ? "Loading script…" : "")}</code>
              </pre>
            )}
          </div>
        )}
      </div>

      {/* Bottom bar: the tab toggle + the contextual actions. */}
      <div className="flex items-center justify-between gap-2 px-3 py-2 mt-1">
        {/* Toggle group (the "tab") */}
        <div
          role="group"
          aria-label="Show chart image or its script"
          className="inline-flex flex-none rounded-lg border border-line overflow-hidden text-xs"
        >
          <button
            type="button"
            onClick={showImage}
            aria-pressed={view === "image"}
            aria-controls={panelId}
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
            aria-controls={panelId}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 border-l border-line transition-colors ${
              view === "script" ? "bg-sage/15 text-ink font-medium" : "bg-card text-muted hover:text-ink"
            }`}
          >
            <Code2 className="w-3.5 h-3.5" strokeWidth={2} aria-hidden />
            Script
          </button>
        </div>

        {/* Right cluster: expand + the contextual action (download / copy). */}
        <div className="flex items-center gap-1.5">
          <Tooltip content="Enlarge" align="end">
            <button
              type="button"
              onClick={() => setExpanded(true)}
              aria-label="Enlarge chart"
              className="inline-flex items-center justify-center h-8 w-8 rounded-lg border border-line text-muted hover:text-ink hover:border-teal transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              <Maximize2 className="w-3.5 h-3.5" strokeWidth={2} />
            </button>
          </Tooltip>
          {view === "image" ? (
            <button
              type="button"
              onClick={handleDownload}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-line text-xs text-muted hover:text-ink hover:border-teal transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              <Download className="w-3.5 h-3.5" strokeWidth={2} aria-hidden />
              <span className={labelCls}>Download</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={handleCopy}
              aria-label={copied ? "Script copied to clipboard" : "Copy script to clipboard"}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-line text-xs text-muted hover:text-ink hover:border-teal transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              {copied ? (
                <Check className="w-3.5 h-3.5 text-sage-strong" strokeWidth={2} aria-hidden />
              ) : (
                <Copy className="w-3.5 h-3.5" strokeWidth={2} aria-hidden />
              )}
              <span className={labelCls}>{copied ? "Copied" : "Copy"}</span>
            </button>
          )}
        </div>
      </div>

      {expanded && <ChartImageModal attachment={attachment} onClose={() => setExpanded(false)} />}
    </div>
  );
}
