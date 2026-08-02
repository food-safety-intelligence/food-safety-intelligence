"use client";

import { useState } from "react";
import { Check, Copy, Download } from "lucide-react";
import { Tooltip } from "@/components/Tooltip";
import { ChartImageModal } from "@/components/ChartImageModal";
import { useChartAttachment } from "@/components/use-chart-attachment";
import type { ChartAttachment } from "@/lib/chart-attachments";

export interface ChartItem {
  /** Unique across the whole conversation (message index + attachment id). */
  key: string;
  attachment: ChartAttachment;
}

/**
 * The `/chat` page's left rail listing every chart generated in the conversation,
 * newest first, as they are created. Each row opens the chart in the enlarge
 * modal (view) and offers copy-script and download-image actions. Hidden on the
 * floating widget (too narrow) and on small screens; the inline cards remain the
 * mobile path.
 */
export function ChartAttachmentsPanel({ items }: { items: ChartItem[] }) {
  const [active, setActive] = useState<ChartAttachment | null>(null);

  return (
    <aside
      aria-label="Generated charts"
      className="hidden md:flex flex-col w-56 flex-none border-r border-line bg-cream/40"
    >
      <div className="flex-none px-3 py-3 border-b border-line">
        <p className="text-2xs tracking-widest uppercase text-muted">Charts</p>
      </div>
      <ul className="flex-1 overflow-y-auto p-2 flex flex-col gap-2">
        {items.map(({ key, attachment }) => (
          <ChartAttachmentRow key={key} attachment={attachment} onOpen={() => setActive(attachment)} />
        ))}
      </ul>
      {active && <ChartImageModal attachment={active} onClose={() => setActive(null)} />}
    </aside>
  );
}

function ChartAttachmentRow({
  attachment,
  onOpen,
}: {
  attachment: ChartAttachment;
  onOpen: () => void;
}) {
  const { title, imageUrl } = attachment;
  const { copied, handleCopy, handleDownload } = useChartAttachment(attachment);

  return (
    <li className="rounded-xl border border-line bg-card soft-shadow overflow-hidden">
      {/* Thumbnail opens the enlarge modal (view). */}
      <button
        type="button"
        onClick={onOpen}
        aria-label={`Open ${title}`}
        className="block w-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- data/presigned URL, not a static asset */}
        <img
          src={imageUrl}
          alt=""
          className="w-full h-20 object-contain bg-white border-b border-line"
        />
      </button>
      <div className="px-2 py-1.5">
        <p className="text-2xs text-ink leading-snug line-clamp-2 mb-1.5">{title}</p>
        <div className="flex items-center gap-1">
          <Tooltip content={copied ? "Copied" : "Copy script"}>
            <button
              type="button"
              onClick={handleCopy}
              aria-label={copied ? "Script copied to clipboard" : "Copy script to clipboard"}
              className="inline-flex items-center justify-center h-7 w-7 rounded-lg border border-line text-muted hover:text-ink hover:border-teal transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              {copied ? (
                <Check className="w-3.5 h-3.5 text-sage-strong" strokeWidth={2} />
              ) : (
                <Copy className="w-3.5 h-3.5" strokeWidth={2} />
              )}
            </button>
          </Tooltip>
          <Tooltip content="Download image">
            <button
              type="button"
              onClick={handleDownload}
              aria-label="Download chart image"
              className="inline-flex items-center justify-center h-7 w-7 rounded-lg border border-line text-muted hover:text-ink hover:border-teal transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              <Download className="w-3.5 h-3.5" strokeWidth={2} />
            </button>
          </Tooltip>
        </div>
      </div>
    </li>
  );
}
