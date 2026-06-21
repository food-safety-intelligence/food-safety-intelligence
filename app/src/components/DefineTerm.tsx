"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Info } from "lucide-react";
import { GLOSSARY, type GlossaryKey } from "@/lib/glossary";
import { cn } from "@/lib/utils";

/**
 * An in-context definition: a small info button that opens a popover with the
 * term's short definition and a link to the full entry on the how-it-works
 * page. Hand-rolled (no Radix in this project) but accessible — labelled
 * trigger, `aria-expanded`, Esc + outside-click to close.
 *
 * Use it next to a controlled term (a driver label, a tier). Definitions come
 * from the shared glossary so the popover and the how-it-works section agree.
 */
export function DefineTerm({
  termKey,
  className,
}: {
  termKey: GlossaryKey;
  className?: string;
}) {
  const entry = GLOSSARY[termKey];
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <span ref={rootRef} className={cn("relative inline-flex align-middle", className)}>
      <button
        type="button"
        onClick={(e) => {
          // Inside a Link/clickable row? Don't navigate when defining a term.
          e.preventDefault();
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        aria-expanded={open}
        aria-label={`What does "${entry.term}" mean?`}
        className="text-muted hover:text-ink transition-colors"
      >
        <Info className="w-3.5 h-3.5" strokeWidth={2} />
      </button>

      {open && (
        <span
          role="dialog"
          aria-label={entry.term}
          className="absolute left-0 top-full z-30 mt-1 w-72 rounded-xl border border-line bg-card p-3 text-left soft-shadow"
        >
          <span className="block font-semibold text-[13px] text-ink">
            {entry.term}
          </span>
          <span className="block text-[12.5px] text-muted leading-snug mt-1">
            {entry.short}
          </span>
          <Link
            href={`/how-it-works#${entry.id}`}
            className="inline-block text-[12px] text-teal hover:underline mt-2"
          >
            Full definition →
          </Link>
        </span>
      )}
    </span>
  );
}
