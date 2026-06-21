"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import type { InspectionEvent } from "@/lib/scores";
import { formatInspectionDate } from "@/lib/utils";
import { cn } from "@/lib/utils";

const RESULTS = ["Pass", "Pass w/ Conditions", "Fail"] as const;
type ResultKey = (typeof RESULTS)[number];

const STYLE: Record<ResultKey, { bg: string; label: string }> = {
  Pass: { bg: "bg-sage", label: "P" },
  "Pass w/ Conditions": { bg: "bg-amber", label: "!" },
  Fail: { bg: "bg-terra", label: "×" },
};

/**
 * Tally card for the result counts. Each row is clickable: selecting a result
 * expands the inspections of that type (most recent first) inline, so a reader
 * can see *which* visits passed or failed without scanning the whole timeline.
 */
export function ResultTally({ events }: { events: InspectionEvent[] }) {
  const [open, setOpen] = useState<ResultKey | null>(null);

  const byResult: Record<ResultKey, InspectionEvent[]> = {
    Pass: [],
    "Pass w/ Conditions": [],
    Fail: [],
  };
  for (const e of events) {
    if (e.result in byResult) byResult[e.result as ResultKey].push(e);
  }
  // Most recent first within each result group.
  for (const r of RESULTS) {
    byResult[r].sort((a, b) => (a.date < b.date ? 1 : -1));
  }

  return (
    <div className="rounded-3xl bg-card border border-line soft-shadow p-6">
      <div className="text-[11px] tracking-widest uppercase text-muted mb-3">
        Result tally
      </div>
      <div className="space-y-1.5">
        {RESULTS.map((r) => {
          const s = STYLE[r];
          const list = byResult[r];
          const count = list.length;
          const isOpen = open === r;
          const disabled = count === 0;
          return (
            <div key={r}>
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : r)}
                disabled={disabled}
                aria-expanded={isOpen}
                className={cn(
                  "w-full flex items-center gap-3 rounded-xl px-2 py-2 text-left transition-colors",
                  disabled
                    ? "cursor-default opacity-60"
                    : "hover:bg-cream/50 cursor-pointer",
                )}
              >
                <span
                  className={`inline-flex w-6 h-6 rounded-full items-center justify-center text-[10px] font-semibold text-white ${s.bg}`}
                >
                  {s.label}
                </span>
                <span className="flex-1 text-[14.5px]">{r}</span>
                <span className="num font-medium">{count}</span>
                {!disabled && (
                  <ChevronDown
                    className={cn(
                      "w-4 h-4 text-muted transition-transform",
                      isOpen && "rotate-180",
                    )}
                    strokeWidth={2}
                  />
                )}
              </button>

              {isOpen && (
                <ul className="mt-1 mb-2 ml-9 pl-3 border-l border-line space-y-2 max-h-64 overflow-y-auto">
                  {list.map((e, i) => (
                    <li key={`${e.date}-${i}`} className="text-[12.5px]">
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="text-ink/90">{e.type || "Inspection"}</span>
                        <span className="num text-[11.5px] text-muted shrink-0">
                          {formatInspectionDate(e.date)}
                        </span>
                      </div>
                      {e.headline && (
                        <div className="text-muted mt-0.5 leading-snug">
                          {e.headline}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
