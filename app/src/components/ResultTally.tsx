"use client";

import { useState } from "react";
import { ChevronDown } from "lucide-react";
import type { InspectionEvent } from "@/lib/scores";
import { CITY_CONFIG } from "@/lib/city";
import { useCity } from "@/components/CityContext";
import { formatInspectionDate } from "@/lib/utils";
import { cn } from "@/lib/utils";

/**
 * Tally card for the inspection-outcome counts. Categories are city-specific —
 * Pass / Pass w/ Conditions / Fail for Chicago, letter grades A / B / C for NYC
 * (from CITY_CONFIG.historyResults). Each row expands its inspections inline.
 */
export function ResultTally({ events }: { events: InspectionEvent[] }) {
  const { city } = useCity();
  const categories = CITY_CONFIG[city].historyResults;
  const [open, setOpen] = useState<string | null>(null);

  const byResult: Record<string, InspectionEvent[]> = {};
  for (const c of categories) byResult[c.key] = [];
  for (const e of events) {
    const cat = categories.find((c) => c.match(e.result));
    if (cat) byResult[cat.key].push(e);
  }
  for (const c of categories) {
    byResult[c.key].sort((a, b) => (a.date < b.date ? 1 : -1));
  }

  return (
    <div className="rounded-3xl bg-card border border-line soft-shadow p-6">
      <div className="text-2xs tracking-widest uppercase text-muted mb-3">
        Result tally
      </div>
      <div className="space-y-1.5">
        {categories.map((c) => {
          const list = byResult[c.key];
          const count = list.length;
          const isOpen = open === c.key;
          const disabled = count === 0;
          return (
            <div key={c.key}>
              <button
                type="button"
                onClick={() => setOpen(isOpen ? null : c.key)}
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
                  className={`inline-flex w-6 h-6 rounded-full items-center justify-center text-2xs font-semibold text-white ${c.bg}`}
                >
                  {c.badge}
                </span>
                <span className="flex-1 text-base">{c.label}</span>
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
                    <li key={`${e.date}-${i}`} className="text-xs">
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="text-ink/90">{e.type || "Inspection"}</span>
                        <span className="num text-xs text-muted shrink-0">
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
