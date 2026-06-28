"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, RotateCcw, AlertCircle, MapPin } from "lucide-react";
import { queryAgent } from "@/lib/agent-api";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Message {
  role: "user" | "agent";
  content: string;
  error?: boolean;
}

// ─── Session helpers ──────────────────────────────────────────────────────────

const SESSION_KEY = "fsi_chat_session";

function getOrCreateSessionId(): string {
  if (typeof window === "undefined") return crypto.randomUUID();
  const stored = sessionStorage.getItem(SESSION_KEY);
  if (stored && stored.length >= 33) return stored;
  const id = crypto.randomUUID(); // 36 chars, satisfies AgentCore min-33 requirement
  sessionStorage.setItem(SESSION_KEY, id);
  return id;
}

function resetSession(): string {
  const id = crypto.randomUUID();
  sessionStorage.setItem(SESSION_KEY, id);
  return id;
}

// ─── Markdown-lite renderer ───────────────────────────────────────────────────
// Handles **bold**, numbered lists, and newlines without adding a dependency.

function renderContent(text: string): React.ReactNode[] {
  return text.split("\n").map((line, i) => {
    const parts = line.split(/(\*\*[^*]+\*\*)/g).map((seg, j) => {
      if (seg.startsWith("**") && seg.endsWith("**")) {
        return <strong key={j}>{seg.slice(2, -2)}</strong>;
      }
      return seg;
    });
    return (
      <span key={i} className="block">
        {parts}
      </span>
    );
  });
}

// ─── Suggested queries ────────────────────────────────────────────────────────

const SUGGESTIONS = [
  "Safest sushi near Wicker Park",
  "Any High-risk restaurants in Logan Square?",
  "Best options for someone with a compromised immune system near River North",
  "Pizza places in Lincoln Park with Low risk tier",
];

// ─── Sub-components ───────────────────────────────────────────────────────────

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[75%] px-4 py-2.5 rounded-2xl rounded-br-sm bg-ink text-cream text-base leading-relaxed">
        {content}
      </div>
    </div>
  );
}

function AgentBubble({ content, error }: { content: string; error?: boolean }) {
  return (
    <div className="flex gap-3 items-start">
      {/* Avatar */}
      <span className="flex-shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-full bg-sage/15 mt-0.5">
        {error ? (
          <AlertCircle className="w-3.5 h-3.5 text-terra" strokeWidth={2} />
        ) : (
          <MapPin className="w-3.5 h-3.5 text-sage" strokeWidth={2} />
        )}
      </span>
      <div
        className={`max-w-[85%] px-4 py-3 rounded-2xl rounded-tl-sm text-base leading-relaxed soft-shadow border ${
          error
            ? "bg-card border-terra/20 text-terra"
            : "bg-card border-line text-ink"
        }`}
      >
        {renderContent(content)}
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div className="flex gap-3 items-start">
      <span className="flex-shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-full bg-sage/15 mt-0.5">
        <MapPin className="w-3.5 h-3.5 text-sage" strokeWidth={2} />
      </span>
      <div className="px-4 py-3 rounded-2xl rounded-tl-sm bg-card border border-line soft-shadow">
        <span className="flex gap-1 items-center h-4">
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              className="w-1.5 h-1.5 rounded-full bg-muted animate-bounce"
              style={{ animationDelay: `${i * 0.15}s` }}
            />
          ))}
        </span>
      </div>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  // Session id is read only when sending a request, never during render, so it
  // lives in a ref. A ref also keeps the client-only localStorage read out of an
  // effect setState (which would trigger a cascading render).
  const sessionIdRef = useRef<string>("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Initialise session on client only (avoids SSR mismatch).
  useEffect(() => {
    sessionIdRef.current = getOrCreateSessionId();
  }, []);

  // Scroll to latest message whenever messages update.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || loading) return;

    setInput("");
    // Prior turns of this conversation, replayed so the agent has context for
    // follow-ups. Captured BEFORE appending the new user turn; error bubbles are
    // dropped (they're client-side failures, not real agent output).
    const history = messages
      .filter((m) => !m.error)
      .map((m) => ({ role: m.role, content: m.content }));
    setMessages((prev) => [...prev, { role: "user", content: trimmed }]);
    setLoading(true);

    try {
      const result = await queryAgent(trimmed, sessionIdRef.current, history);
      setMessages((prev) => [...prev, { role: "agent", content: result }]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Something went wrong.";
      setMessages((prev) => [
        ...prev,
        { role: "agent", content: msg, error: true },
      ]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(input);
    }
  }

  function handleClear() {
    setMessages([]);
    sessionIdRef.current = resetSession();
    setInput("");
    inputRef.current?.focus();
  }

  const isEmpty = messages.length === 0;

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* ── Message area ───────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-4 md:px-8">
        <div className="max-w-2xl mx-auto py-6 flex flex-col gap-4">

          {/* Empty state — welcome + suggestions */}
          {isEmpty && (
            <div className="flex flex-col items-center text-center pt-8 pb-4">
              <span className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-sage/15 mb-4">
                <MapPin className="w-5 h-5 text-sage" strokeWidth={2} />
              </span>
              <h2 className="text-2xl font-semibold tracking-tight mb-2">
                Ask about food safety
              </h2>
              <p className="text-base text-muted max-w-[42ch] leading-relaxed mb-8">
                Search by neighborhood, cuisine, or risk level. Ask follow-up
                questions — the agent remembers your session.
              </p>
              <div className="flex flex-wrap gap-2 justify-center">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => void send(s)}
                    className="px-3.5 py-1.5 rounded-full bg-card border border-line text-sm hover:border-teal hover:text-teal transition-colors soft-shadow"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Message list */}
          {messages.map((m, i) =>
            m.role === "user" ? (
              <UserBubble key={i} content={m.content} />
            ) : (
              <AgentBubble key={i} content={m.content} error={m.error} />
            ),
          )}

          {loading && <TypingIndicator />}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* ── Input bar ──────────────────────────────────────────────────────── */}
      <div className="border-t border-line bg-cream/80 backdrop-blur-sm px-4 md:px-8 py-4">
        <div className="max-w-2xl mx-auto">
          <div className="flex items-end gap-2 bg-card rounded-2xl border border-line soft-shadow px-3 py-2">
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about a neighborhood, cuisine, or risk level…"
              disabled={loading}
              aria-label="Chat input"
              className="flex-1 resize-none bg-transparent text-base placeholder:text-muted/60 outline-none leading-relaxed py-1 max-h-32 overflow-y-auto disabled:opacity-50"
              style={{ fieldSizing: "content" } as React.CSSProperties}
            />
            <div className="flex items-center gap-1 flex-shrink-0 pb-0.5">
              {!isEmpty && (
                <button
                  onClick={handleClear}
                  aria-label="Clear conversation"
                  className="p-1.5 rounded-full text-muted hover:text-terra hover:bg-terra/10 transition-colors"
                >
                  <RotateCcw className="w-3.5 h-3.5" strokeWidth={2} />
                </button>
              )}
              <button
                onClick={() => void send(input)}
                disabled={!input.trim() || loading}
                aria-label="Send message"
                className="w-8 h-8 rounded-full bg-ink text-cream flex items-center justify-center hover:bg-teal transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <ArrowUp className="w-4 h-4" strokeWidth={2.5} />
              </button>
            </div>
          </div>
          <p className="text-2xs text-muted/70 text-center mt-2">
            Scores are 180-day predictions from public Chicago data · Not a
            health department inspection
          </p>
        </div>
      </div>
    </div>
  );
}
