"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { type Dispatch, type SetStateAction, useEffect, useState } from "react";
import type { InspectionEvent } from "@/lib/scores";
import {
  compareInspectionsNewestFirst,
  INSPECTION_JUMP_EVENT,
  inspectionAnchorId,
  parseInspectionAnchor,
} from "@/lib/scores";
import { CITY_CONFIG, type City } from "@/lib/city";
import { useCity } from "@/components/CityContext";
import { formatInspectionDate } from "@/lib/utils";

// Dot colour + badge for an inspection outcome, per city (Pass/Fail for Chicago,
// letter grade A/B/C for NYC — from CITY_CONFIG.historyResults).
function styleFor(result: string, city: City) {
  const cat = CITY_CONFIG[city].historyResults.find((c) => c.match(result));
  return cat
    ? { bg: cat.bg, label: cat.badge }
    : { bg: "bg-muted", label: "·" };
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
  const { city } = useCity();
  // Whether the older inspections (past maxVisible) are revealed.
  const [expanded, setExpanded] = useState(false);
  // Layer 1: which inspection rows are expanded to show their violation list,
  // keyed by the row's stable key.
  const [open, setOpen] = useState<Set<string>>(new Set());
  // Layer 2: which individual violations are expanded to show their comment,
  // keyed by `${rowKey}-${violationIndex}`.
  const [openViolations, setOpenViolations] = useState<Set<string>>(new Set());
  // The row a trend-chart dot linked to (null = none), held as a fresh object per
  // jump — re-clicking the SAME dot makes a new reference so React re-runs the
  // scroll/highlight effect instead of bailing on an unchanged value. `n` is the
  // newest-first index. Cleared after the flash.
  const [highlight, setHighlight] = useState<{ n: number } | null>(null);

  // React to a hardlink from the trend chart: the URL hash (a fresh deep link or
  // the enlarged chart's new tab) or the in-tab jump event (the inline chart).
  // Expand the collapsed tail if the target is hidden; the effect below then
  // scrolls to and highlights the row.
  useEffect(() => {
    function jumpTo(n: number | null) {
      if (n === null || n < 0 || n >= events.length) return;
      if (n >= maxVisible) setExpanded(true);
      setHighlight({ n });
    }
    jumpTo(parseInspectionAnchor(window.location.hash));
    const onHash = () => jumpTo(parseInspectionAnchor(window.location.hash));
    const onJump = (e: Event) =>
      jumpTo(parseInspectionAnchor((e as CustomEvent<string>).detail ?? ""));
    window.addEventListener("hashchange", onHash);
    window.addEventListener(INSPECTION_JUMP_EVENT, onJump as EventListener);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener(INSPECTION_JUMP_EVENT, onJump as EventListener);
    };
  }, [events.length, maxVisible]);

  // Once the target row is in the DOM (after any auto-expand), scroll it into
  // view, move focus to it (keyboard + screen-reader cue), and clear the
  // highlight after a moment so it reads as a brief flash.
  useEffect(() => {
    if (highlight === null) return;
    const el = document.getElementById(inspectionAnchorId(highlight.n));
    const raf = requestAnimationFrame(() => {
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
      // Focus the row itself (tabIndex -1, outline-none) rather than its button,
      // so screen-reader/keyboard users land here without drawing a focus box.
      el?.focus({ preventScroll: true });
    });
    // Hold long enough to stay visible after the ~1s smooth scroll settles.
    const timer = setTimeout(() => setHighlight(null), 3600);
    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(timer);
    };
    // Depends on `highlight` only: an auto-expand is batched with the highlight
    // (same render), so the row is present on first run; keeping `expanded` out
    // avoids re-scrolling if the user manually expands while the flash is up.
  }, [highlight]);

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

  // Most recent first, and stable on equal dates (a license can have two
  // inspections in one day). This is the SAME comparator the trend-chart dots
  // index their anchors by, so `inspection-<n>` lands on the matching row.
  const sorted = events.slice().sort(compareInspectionsNewestFirst);
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
          const s = styleFor(e.result, city);
          const isFail = CITY_CONFIG[city].isBadOutcome(e.result);
          const key = `${e.date}-${i}`;
          const isOpen = open.has(key);
          const panelId = `inspection-comments-${key}`;
          // `i` is the newest-first index (visible is a prefix of sorted), so
          // this matches the anchor the trend-chart dots link to.
          const anchorId = inspectionAnchorId(i);
          const isHighlighted = highlight?.n === i;
          // Count of cited violations for this inspection. Derived from the same
          // parse the expanded panel uses, so the collapsed "N violations" label
          // always matches the number of items revealed on expand.
          const violations = e.comments ? parseViolations(e.comments) : [];
          const hasViolations = violations.length > 0;
          // Cities without a full comment sidecar (NYC, LA) never populate
          // `comments`, but each event carries its top cited violation in
          // `headline`. Show that so those rows read the real violation rather
          // than a misleading "No violations". There's no fuller text to expand
          // into, so headline-only rows stay non-expandable; an empty headline
          // means the inspection genuinely recorded no violations.
          const headlineText = (e.headline ?? "").trim();
          // The row leads with the violation status so it lines up down the
          // column; the inspection type follows. Only comment-backed rows are
          // expandable (the chevron reveals the full violation list).
          const violationLabel = hasViolations
            ? `${violations.length} violation${violations.length === 1 ? "" : "s"}`
            : headlineText || "No violations";
          // Row body is identical whether or not the row expands; only the
          // wrapper (interactive button vs. static div) differs. The expand
          // chevron sits on the LEFT of the text — its column is reserved on
          // every row (rendered empty when a row isn't expandable) so the
          // right-aligned dates line up in a clean column throughout.
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
                <span className="flex items-start justify-between gap-3">
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
                  {/* Expand chevron under the date (right), so the right-aligned
                      dates stay a clean column and only expandable rows show it. */}
                  {hasViolations && (
                    <ChevronDown
                      className={`shrink-0 w-4 h-4 mt-0.5 text-muted group-hover:text-ink transition-transform ${
                        isOpen ? "rotate-180" : ""
                      }`}
                      strokeWidth={2}
                      aria-hidden="true"
                    />
                  )}
                </span>
              </span>
            </>
          );
          return (
            <li
              key={key}
              id={anchorId}
              // Focusable (programmatically only) so a hardlink can move focus
              // here for screen-reader users; outline-none keeps it from drawing
              // a box — the pale-yellow wash is the visual cue instead. No
              // scroll-margin: the jump uses scrollIntoView(block:"center") and a
              // margin would shift that centred target off-centre.
              tabIndex={-1}
              data-highlighted={isHighlighted || undefined}
              className={`rounded-xl outline-none transition-colors duration-500 ${
                isHighlighted ? "bg-highlight" : ""
              }`}
            >
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
