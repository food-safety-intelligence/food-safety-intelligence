"use client";

import { useEffect, useRef, useState } from "react";
import { MessageCircle, Send, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
}

const WELCOME: ChatMessage = {
  role: "assistant",
  text: 'Hi — ask about food-safety risk for Chicago restaurants. Try "safest tacos" or "is Subway risky?".',
};

/**
 * Floating chat button + panel, mounted site-wide from the root layout.
 * Talks to the stub `/api/agent` route (data-backed answers from scores.json);
 * the same UI works unchanged once that route proxies to the real agent.
 */
export function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const listEndRef = useRef<HTMLDivElement>(null);

  // Focus the input when the panel opens.
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  // Keep the newest message in view.
  useEffect(() => {
    listEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Esc closes the panel.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  async function send() {
    const text = input.trim();
    if (!text || pending) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setPending(true);
    try {
      const res = await fetch("/api/agent", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      const data = (await res.json()) as { reply?: string };
      setMessages((m) => [
        ...m,
        { role: "assistant", text: data.reply ?? "Sorry — something went wrong." },
      ]);
    } catch {
      setMessages((m) => [
        ...m,
        { role: "assistant", text: "Sorry — I couldn't reach the assistant." },
      ]);
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      {open && (
        <div
          role="dialog"
          aria-label="Food safety assistant"
          className="fixed bottom-24 right-6 z-50 flex h-[28rem] w-[22rem] max-w-[calc(100vw-3rem)] flex-col overflow-hidden rounded-3xl border border-line bg-card soft-shadow-lg"
        >
          <header className="flex items-center justify-between border-b border-line px-4 py-3">
            <span className="font-medium text-ink">Food safety assistant</span>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="Close assistant"
              className="grid h-11 w-11 place-items-center rounded-full text-muted transition-colors hover:bg-cream hover:text-ink"
            >
              <X className="h-5 w-5" strokeWidth={2} />
            </button>
          </header>

          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {messages.map((m, i) => (
              <div
                key={i}
                className={cn(
                  "max-w-[85%] whitespace-pre-line rounded-2xl px-3 py-2 text-[15px] leading-relaxed",
                  m.role === "user"
                    ? "ml-auto bg-ink text-cream"
                    : "bg-cream text-ink",
                )}
              >
                {m.text}
              </div>
            ))}
            {pending && (
              <div className="max-w-[85%] rounded-2xl bg-cream px-3 py-2 text-[15px] text-muted">
                Thinking…
              </div>
            )}
            <div ref={listEndRef} />
          </div>

          <div className="border-t border-line px-3 py-3">
            <div className="flex items-center gap-2 rounded-full bg-cream px-3 py-1.5">
              <input
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void send();
                  }
                }}
                placeholder="Ask about a restaurant…"
                aria-label="Message"
                className="min-w-0 flex-1 bg-transparent px-2 text-[15px] text-ink placeholder:text-muted/70 focus:outline-none"
              />
              <button
                type="button"
                onClick={() => void send()}
                disabled={!input.trim() || pending}
                aria-label="Send message"
                className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-ink text-cream transition-colors hover:bg-teal disabled:opacity-40"
              >
                <Send className="h-4 w-4" strokeWidth={2} />
              </button>
            </div>
            <p className="mt-2 px-1 text-[11px] leading-snug text-muted">
              Preliminary demo — answers come from precomputed risk scores, not a
              live model.
            </p>
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Close assistant" : "Open food safety assistant"}
        aria-expanded={open}
        className="fixed bottom-6 right-6 z-50 grid h-14 w-14 place-items-center rounded-full bg-ink text-cream transition-colors hover:bg-teal soft-shadow-lg"
      >
        {open ? (
          <X className="h-6 w-6" strokeWidth={2} />
        ) : (
          <MessageCircle className="h-6 w-6" strokeWidth={2} />
        )}
      </button>
    </>
  );
}
