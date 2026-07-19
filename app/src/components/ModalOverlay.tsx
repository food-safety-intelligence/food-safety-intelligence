"use client";

import { useEffect, useRef, type ReactNode, type RefObject } from "react";

/**
 * Generic centered modal overlay: a dimmed backdrop (click to close), a
 * `role="dialog"` card, Escape-to-close, background-scroll lock, and focus
 * management (focus moves into the dialog on open and returns to the opener on
 * close). The caller composes the dialog's own header / close button / body as
 * children. Shared by `TrendChartModal` and `ChartImageModal` so the overlay
 * behaviour is defined once.
 *
 * Note: this manages initial + return focus but does NOT trap Tab inside the
 * dialog (matching the app's existing modal behaviour).
 */
export function ModalOverlay({
  onClose,
  label,
  backdropLabel = "Close",
  maxWidthClass = "max-w-3xl",
  initialFocusRef,
  className = "",
  children,
}: {
  onClose: () => void;
  /** Accessible name for the dialog (aria-label). */
  label: string;
  /** Accessible name for the backdrop close button. */
  backdropLabel?: string;
  /** Tailwind max-width class for the dialog card. */
  maxWidthClass?: string;
  /** Element to focus on open; defaults to the dialog card itself. */
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** Extra classes for the dialog card. */
  className?: string;
  children: ReactNode;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);

  // Focus into the dialog on open; restore focus to the opener on close.
  useEffect(() => {
    const prevActive = document.activeElement as HTMLElement | null;
    (initialFocusRef?.current ?? dialogRef.current)?.focus();
    return () => prevActive?.focus?.();
  }, [initialFocusRef]);

  // Esc closes; lock background scroll while open. The listener is in the CAPTURE
  // phase and stops propagation, so Escape closes THIS overlay and nothing else —
  // e.g. when the overlay is opened from inside the floating chat widget (which
  // has its own document-level Escape-to-close), one Esc dismisses only the
  // overlay, not the whole chat.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    document.addEventListener("keydown", onKey, true);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4">
      {/* Backdrop — click to dismiss. */}
      <button
        aria-label={backdropLabel}
        onClick={onClose}
        className="absolute inset-0 bg-ink/40 cursor-default"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        className={`relative z-10 w-full ${maxWidthClass} rounded-2xl border border-line bg-card soft-shadow-lg p-5 sm:p-6 outline-none ${className}`}
      >
        {children}
      </div>
    </div>
  );
}
