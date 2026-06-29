"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Small accessible tooltip — the replacement for native `title=`.
 *
 * Native `title` only shows on mouse hover: it's invisible to keyboard and touch
 * users, can't be styled, and can't be captured in a screenshot/test. This shows
 * on hover AND keyboard focus (via `group-focus-within`), is styled to match, and
 * is real DOM (so it renders in tests/screenshots).
 *
 * Hand-rolled — there is no Radix in this project (see DefineTerm.tsx). The bubble
 * is `aria-hidden`: every caller already exposes the same text to assistive tech
 * another way (an `aria-label` on the focusable trigger, or — for truncated text —
 * the untruncated text node, which CSS truncation doesn't hide from screen
 * readers), so announcing it again here would just double up.
 *
 * Usage:
 *  - Wrapping an already-focusable control (icon button / link): the control is
 *    the focus target, so leave `focusable` off.
 *  - Wrapping non-interactive text that should still reveal on keyboard focus: set
 *    `focusable` so the wrapper itself takes a tab stop.
 *  - `onlyWhenTruncated`: reveal only when the trigger's content actually overflows
 *    (for a truncated label, where there's nothing to reveal if it already fits).
 */
interface TooltipProps {
  /** Text revealed on hover / focus. */
  content: string;
  /** The trigger — an icon button, link, or a piece of (possibly truncated) text. */
  children: ReactNode;
  /** Add a tab stop to the wrapper so keyboard users can reveal the tooltip when
   *  the trigger isn't itself focusable. Omit for buttons/links/inputs. */
  focusable?: boolean;
  /** Only reveal when the trigger's first child overflows its box (truncation). */
  onlyWhenTruncated?: boolean;
  /** Which side of the trigger the bubble sits on. */
  side?: "top" | "bottom";
  /** Horizontal anchor: `start` extends right from the trigger's left edge,
   *  `end` extends left from its right edge. Use `end` for triggers near a
   *  container's right edge so the bubble doesn't overflow/clip. */
  align?: "start" | "end";
  /** Extra classes for the wrapper (e.g. layout: `inline-flex`, `flex-1 min-w-0`). */
  className?: string;
}

export function Tooltip({
  content,
  children,
  focusable = false,
  onlyWhenTruncated = false,
  side = "bottom",
  align = "start",
  className,
}: TooltipProps) {
  const wrapRef = useRef<HTMLSpanElement>(null);
  const [overflowing, setOverflowing] = useState(false);

  // Overflow can only be read from layout after render. Measure the trigger and
  // re-measure on resize so the tooltip appears exactly when text is clipped.
  useEffect(() => {
    if (!onlyWhenTruncated) return;
    const el = wrapRef.current?.firstElementChild as HTMLElement | null;
    if (!el) return;
    const measure = () => {
      const truncated = el.scrollWidth > el.clientWidth;
      setOverflowing((prev) => (prev === truncated ? prev : truncated));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [onlyWhenTruncated, content]);

  const reveal = !onlyWhenTruncated || overflowing;

  return (
    <span
      ref={wrapRef}
      tabIndex={focusable ? 0 : undefined}
      className={cn("group relative inline-flex", className)}
    >
      {children}
      {reveal && (
        <span
          aria-hidden
          className={cn(
            // w-max sizes the bubble to its content (capped by max-w) rather than
            // shrink-to-fit of the trigger's box — an icon trigger is only ~20px
            // wide, which would otherwise wrap the text one word per line.
            "pointer-events-none absolute z-20 inline-block w-max max-w-[16rem] whitespace-normal break-words rounded-md bg-ink px-2 py-1 text-xs text-cream opacity-0 shadow-md transition-opacity duration-100 group-hover:opacity-100 group-focus-within:opacity-100",
            side === "bottom" ? "top-full mt-1" : "bottom-full mb-1",
            align === "end" ? "right-0" : "left-0",
          )}
        >
          {content}
        </span>
      )}
    </span>
  );
}
