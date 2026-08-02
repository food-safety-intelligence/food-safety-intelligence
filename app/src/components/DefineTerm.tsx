"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Info } from "lucide-react";
import { glossaryEntry, type GlossaryEntry, type GlossaryKey } from "@/lib/glossary";
import { useCity } from "@/components/CityContext";
import { cn } from "@/lib/utils";

// Popover ideal width; clamped to the viewport on open.
const POPOVER_W = 288;

/**
 * An in-context definition: a small info button that opens a popover with the
 * term's short definition and a link to the full entry on the how-it-works
 * page. Hand-rolled (no Radix in this project) but accessible — labelled
 * trigger, `aria-expanded`/`aria-haspopup`, Esc + outside-click to close.
 *
 * The popover is `position: fixed` with viewport-clamped coordinates computed
 * from the trigger on open. Fixed positioning escapes the driver card's
 * `overflow-hidden` (so it's never clipped), and clamping the left edge keeps
 * it from overflowing the viewport on narrow screens. It closes on scroll
 * (fixed coords would otherwise drift) and resize.
 */
export function DefineTerm({
  termKey,
  className,
}: {
  termKey: GlossaryKey;
  className?: string;
}) {
  // City-aware: the definition names the outcome this city predicts, and its
  // anchor exists in that city's Definitions section, so "Full definition"
  // never lands on a missing anchor.
  const { city } = useCity();
  const entry: GlossaryEntry = glossaryEntry(termKey, city);
  const btnRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(
    null,
  );
  const open = pos !== null;

  const toggle = () => {
    if (open) {
      setPos(null);
      return;
    }
    const el = btnRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const margin = 8;
    const width = Math.min(POPOVER_W, window.innerWidth - margin * 2);
    // Clamp so the popover never runs off either edge of the viewport.
    const left = Math.max(
      margin,
      Math.min(r.left, window.innerWidth - width - margin),
    );
    setPos({ top: r.bottom + 6, left, width });
  };

  useEffect(() => {
    if (!open) return;
    const close = () => setPos(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPos(null);
    };
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (btnRef.current?.contains(t) || popRef.current?.contains(t)) return;
      setPos(null);
    };
    // capture scroll on any ancestor (the side panels scroll internally).
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  return (
    <span className={cn("inline-flex align-middle", className)}>
      <button
        ref={btnRef}
        type="button"
        onClick={(e) => {
          // Inside a Link/clickable row? Don't navigate when defining a term.
          e.preventDefault();
          e.stopPropagation();
          toggle();
        }}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={`What does "${entry.term}" mean?`}
        className="text-muted hover:text-ink transition-colors"
      >
        <Info className="w-3.5 h-3.5" strokeWidth={2} />
      </button>

      {pos && (
        <div
          ref={popRef}
          role="dialog"
          aria-label={entry.term}
          style={{ position: "fixed", top: pos.top, left: pos.left, width: pos.width }}
          className="z-50 rounded-xl border border-line bg-card p-3 text-left soft-shadow"
        >
          <span className="block font-semibold text-sm text-ink">
            {entry.term}
          </span>
          <span className="block text-xs text-muted leading-snug mt-1">
            {entry.short}
          </span>
          <Link
            href={entry.href ?? `/how-it-works#${entry.id}`}
            className="inline-block text-xs text-teal hover:underline mt-2"
          >
            Full definition →
          </Link>
        </div>
      )}
    </span>
  );
}
