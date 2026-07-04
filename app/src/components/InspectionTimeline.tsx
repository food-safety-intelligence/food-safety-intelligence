"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { type Dispatch, type SetStateAction, useState } from "react";
import type { InspectionEvent } from "@/lib/scores";
import { formatInspectionDate } from "@/lib/utils";

const RESULT_STYLES = {
  Pass: { bg: "bg-sage", label: "P", text: "" },
  "Pass w/ Conditions": { bg: "bg-amber", label: "!", text: "" },
  Fail: { bg: "bg-terra", label: "×", text: "text-terra" },
} as const;

type ResultKey = keyof typeof RESULT_STYLES;

function styleFor(result: string) {
  return RESULT_STYLES[result as ResultKey] ?? {
    bg: "bg-muted",
    label: "·",
    text: "",
  };
}

/** One cited violation: the code + name, and the inspector's free-text note. */
type Violation = { title: string; note: string };

const COMMENTS_MARKER = " - Comments:";

// Chicago's records often omit the space after a period/comma
// ("CERTIFICATE.MUST PROVIDE", "TOMATO,ETC"). Insert one for readability when
// punctuation is immediately followed by a letter or an opening paren. The
// lookahead skips cases that already have a space and leaves digits alone (so
// codes like 7-38-012 and any decimals are untouched). Display-only — the
// stored text stays verbatim.
function tidySpacing(s: string): string {
  return s.replace(/([.,;:)])(?=[A-Za-z(])/g, "$1 ");
}

// Split the rejoined violation text (one violation per line) into its code/name
// and the inspector's comment. Lines without the marker show as a bare title.
function parseViolations(comments: string): Violation[] {
  return comments
    .split("\n")
    .map((line) => {
      const i = line.indexOf(COMMENTS_MARKER);
      if (i === -1) return { title: tidySpacing(line.trim()), note: "" };
      return {
        title: tidySpacing(line.slice(0, i).trim()),
        note: tidySpacing(line.slice(i + COMMENTS_MARKER.length).trim()),
      };
    })
    .filter((v) => v.title || v.note);
}

/**
 * Vertical timeline of inspection events. The leftmost rail is implied by
 * absolute-positioning a 2px line behind the colored dots. Renders the most
 * recent event first. Two nested expand layers: a row expands to list that
 * inspection's cited violations (titles only), and each violation expands to
 * show the inspector's comment for it.
 */
export function InspectionTimeline({
  events,
  maxVisible = 9,
}: {
  events: InspectionEvent[];
  maxVisible?: number;
}) {
  // Whether the older inspections (past maxVisible) are revealed.
  const [expanded, setExpanded] = useState(false);
  // Layer 1: which inspection rows are expanded to show their violation list,
  // keyed by the row's stable key.
  const [open, setOpen] = useState<Set<string>>(new Set());
  // Layer 2: which individual violations are expanded to show their comment,
  // keyed by `${rowKey}-${violationIndex}`.
  const [openViolations, setOpenViolations] = useState<Set<string>>(new Set());

  if (events.length === 0) {
    return (
      <div className="rounded-3xl bg-card border border-line p-6 text-muted text-base">
        No inspection history on record for this license.
      </div>
    );
  }

  // Add/remove a key from a Set-valued toggle state. Shared by both layers.
  const makeToggle =
    (setter: Dispatch<SetStateAction<Set<string>>>) => (key: string) =>
      setter((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        return next;
      });
  const toggle = makeToggle(setOpen);
  const toggleViolation = makeToggle(setOpenViolations);

  // Most recent first. localeCompare returns 0 on equal dates, so the sort stays
  // stable — same-date inspections keep their input order instead of an
  // engine-defined one (a license can have two inspections on one day).
  const sorted = events.slice().sort((a, b) => b.date.localeCompare(a.date));
  const visible = expanded ? sorted : sorted.slice(0, maxVisible);
  const hidden = sorted.length - visible.length;

  return (
    <div className="rounded-3xl bg-card border border-line soft-shadow p-6 relative">
      {/* Vertical line behind the dots */}
      <div
        className="absolute top-6 bottom-6 w-[2px] bg-line"
        style={{ left: 35 }}
      />
      <ul className="space-y-3 relative">
        {visible.map((e, i) => {
          const s = styleFor(e.result);
          const isFail = e.result === "Fail";
          const key = `${e.date}-${i}`;
          const isOpen = open.has(key);
          const panelId = `inspection-comments-${key}`;
          // Count of cited violations for this inspection. Derived from the same
          // parse the expanded panel uses, so the collapsed "N violations" label
          // always matches the number of items revealed on expand.
          const violations = e.comments ? parseViolations(e.comments) : [];
          const hasViolations = violations.length > 0;
          // The row leads with the violation status so the counts line up down
          // the column; the inspection type follows. Zero-violation rows read
          // "No violations" and aren't expandable — there's nothing to reveal.
          const violationLabel = hasViolations
            ? `${violations.length} violation${violations.length === 1 ? "" : "s"}`
            : "No violations";
          // Row body is identical whether or not the row expands; only the
          // wrapper (interactive button vs. static div) and the chevron differ.
          const rowInner = (
            <>
              <span
                className={`shrink-0 inline-flex w-6 h-6 rounded-full items-center justify-center text-2xs font-semibold text-white ${s.bg}`}
              >
                {s.label}
              </span>
              {/* Spans (not divs) so this is valid inside the row <button>. */}
              <span className="block flex-1 min-w-0">
                <span className="flex items-baseline justify-between gap-3">
                  <span className={`font-semibold ${isFail ? "text-terra" : ""}`}>
                    {e.result}
                  </span>
                  <span className="num text-xs text-muted shrink-0">
                    {formatInspectionDate(e.date)}
                  </span>
                </span>
                <span
                  className={`block text-sm mt-0.5 ${
                    isFail ? "text-ink/90" : "text-muted"
                  }`}
                >
                  <span className={hasViolations && isFail ? "font-medium" : ""}>
                    {violationLabel}
                  </span>
                  {" · "}
                  {e.type}
                </span>
              </span>
              {hasViolations && (
                <ChevronDown
                  className={`shrink-0 w-4 h-4 mt-1 text-muted group-hover:text-ink transition-transform ${
                    isOpen ? "rotate-180" : ""
                  }`}
                  strokeWidth={2}
                  aria-hidden="true"
                />
              )}
            </>
          );
          return (
            <li key={key}>
              {hasViolations ? (
                <button
                  type="button"
                  onClick={() => toggle(key)}
                  aria-expanded={isOpen}
                  // Only reference the panel while it's mounted (open); otherwise
                  // aria-controls would point at a non-existent id.
                  aria-controls={isOpen ? panelId : undefined}
                  className="group flex items-start gap-4 w-full text-left rounded-xl px-2 py-2 -mx-2 cursor-pointer focus-visible:outline-2 focus-visible:outline-teal"
                >
                  {rowInner}
                </button>
              ) : (
                <div className="flex items-start gap-4 w-full px-2 py-2 -mx-2">
                  {rowInner}
                </div>
              )}

              {hasViolations && isOpen && (
                <div
                  id={panelId}
                  className="ml-10 mr-2 mt-1 mb-2 rounded-xl bg-tint border border-line p-4 text-sm leading-relaxed"
                >
                  <ul className="divide-y divide-line/60">
                    {violations.map((v, vi) => {
                      const vKey = `${key}-${vi}`;
                      const vOpen = openViolations.has(vKey);
                      const vPanelId = `violation-note-${vKey}`;
                      const hasNote = Boolean(v.note);
                      return (
                        <li key={vi} className="py-2 first:pt-0 last:pb-0">
                          {hasNote ? (
                            <button
                              type="button"
                              onClick={() => toggleViolation(vKey)}
                              aria-expanded={vOpen}
                              aria-controls={vOpen ? vPanelId : undefined}
                              className="group/v flex items-start gap-2 w-full text-left rounded cursor-pointer focus-visible:outline-2 focus-visible:outline-teal"
                            >
                              <ChevronRight
                                className={`shrink-0 w-4 h-4 mt-0.5 text-muted group-hover/v:text-ink transition-transform ${
                                  vOpen ? "rotate-90" : ""
                                }`}
                                strokeWidth={2}
                                aria-hidden="true"
                              />
                              <span className="font-medium text-ink/90">
                                {v.title}
                              </span>
                            </button>
                          ) : (
                            <div className="flex items-start gap-2">
                              <span
                                className="shrink-0 w-4 h-4 mt-0.5"
                                aria-hidden="true"
                              />
                              <span className="font-medium text-ink/90">
                                {v.title}
                              </span>
                            </div>
                          )}
                          {hasNote && vOpen && (
                            <p id={vPanelId} className="text-ink/80 mt-1 ml-6">
                              {v.note}
                            </p>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="block w-full text-center text-sm mt-6 text-teal hover:underline"
        >
          Show {hidden} older inspection{hidden === 1 ? "" : "s"}
        </button>
      )}
      {expanded && sorted.length > maxVisible && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          className="block w-full text-center text-sm mt-6 text-teal hover:underline"
        >
          Show fewer
        </button>
      )}
    </div>
  );
}
