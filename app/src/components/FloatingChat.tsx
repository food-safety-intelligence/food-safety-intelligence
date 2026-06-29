"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { MessageCircle, X, Maximize2 } from "lucide-react";
import { ChatInterface } from "@/components/ChatInterface";
import { useChatScope } from "@/components/ChatScopeContext";

/**
 * Site-wide chat launcher. Mounted once in the root layout, so it floats over
 * every page. Clicking the corner button opens a compact panel that reuses the
 * full <ChatInterface /> (same agent, same session); the expand control routes
 * to the dedicated /chat page for the roomier experience.
 *
 * Hidden on /chat itself — the full page already is the chat, so a launcher
 * there would be redundant.
 */
export function FloatingChat() {
  const pathname = usePathname();
  const { current: establishment } = useChatScope();
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const launcherRef = useRef<HTMLButtonElement>(null);
  // Skip focus management on the initial mount — the effect below runs once with
  // open=false, and without this it would focus the launcher on every page load
  // (it's mounted site-wide in the root layout), stealing focus from the page.
  const firstRun = useRef(true);

  // Esc closes the panel.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  // On open, move focus to the message input so the user can type straight
  // away; on close, return focus to the launcher so keyboard users aren't
  // dropped back at the top of the page.
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false;
      return;
    }
    if (open) {
      panelRef.current?.querySelector<HTMLElement>("textarea")?.focus();
    } else {
      launcherRef.current?.focus();
    }
  }, [open]);

  // The full chat page is its own surface — don't stack a launcher on it.
  // trailingSlash is on (next.config), so usePathname() returns "/chat/";
  // match both forms so the guard holds however the route is normalised.
  if (pathname === "/chat" || pathname === "/chat/") return null;

  return (
    <>
      {/* ── Launcher ─────────────────────────────────────────────────────────
          Hidden while the panel is open (the panel carries its own close). */}
      {!open && (
        <button
          ref={launcherRef}
          onClick={() => setOpen(true)}
          aria-label="Open the food-safety chat"
          aria-expanded={open}
          aria-controls="floating-chat-panel"
          className="fixed bottom-4 right-4 z-50 inline-flex items-center gap-2 rounded-full bg-ink text-cream pl-4 pr-5 py-3 soft-shadow hover:bg-teal transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
        >
          <MessageCircle className="w-5 h-5" strokeWidth={2} />
          <span className="text-sm font-medium">Ask</span>
        </button>
      )}

      {/* ── Panel ────────────────────────────────────────────────────────────
          Near-fullscreen on mobile; a fixed corner card on sm+. */}
      {open && (
        <div
          ref={panelRef}
          id="floating-chat-panel"
          role="dialog"
          aria-modal="false"
          aria-label="Food-safety chat"
          className="fixed z-50 flex flex-col overflow-hidden rounded-2xl border border-line bg-cream soft-shadow inset-x-3 bottom-3 top-16 sm:inset-auto sm:bottom-4 sm:right-4 sm:top-auto sm:w-[384px] sm:h-[576px] sm:max-h-[calc(100vh-2rem)]"
        >
          {/* Header */}
          <div className="flex items-center justify-between gap-2 flex-none px-4 py-3 border-b border-line bg-card">
            <span className="inline-flex items-center gap-2 min-w-0">
              <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-sage/15 flex-none">
                <MessageCircle className="w-4 h-4 text-sage" strokeWidth={2} />
              </span>
              {/* "Eatelligence" = Eat + intelligence; the sage "Eat" stem
                  (sage-strong clears AA) plays up the pun. */}
              <span className="text-sm font-semibold tracking-tight truncate">
                <span className="text-sage-strong">Eat</span>elligence
              </span>
            </span>
            <span className="flex items-center gap-1 flex-none">
              <Link
                href="/chat"
                aria-label="Open the full chat page"
                title="Open the full chat page"
                className="p-1.5 rounded-full text-muted hover:text-teal hover:bg-tint transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
              >
                <Maximize2 className="w-4 h-4" strokeWidth={2} />
              </Link>
              <button
                onClick={() => setOpen(false)}
                aria-label="Close chat"
                className="p-1.5 rounded-full text-muted hover:text-terra hover:bg-terra/10 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
              >
                <X className="w-4 h-4" strokeWidth={2} />
              </button>
            </span>
          </div>

          {/* Chat — fills the rest; ChatInterface is flex-1 min-h-0 internally.
              compact drops the big empty-state heading (the panel header has it).
              establishment scopes "this restaurant" to the detail page in view. */}
          <ChatInterface compact establishment={establishment} />
        </div>
      )}
    </>
  );
}
