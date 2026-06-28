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

// The transcript is persisted to sessionStorage so it survives the floating
// popup -> /chat expand (a full-page navigation that remounts ChatInterface) and
// a reload, within the same tab session. Without this the new mount starts empty
// and the conversation — and the history sent to the agent — is lost.
const MESSAGES_KEY = "fsi_chat_messages";

function loadMessages(): Message[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(sessionStorage.getItem(MESSAGES_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    // Validate shape before these reach render and the agent-history payload —
    // sessionStorage is user-writable and the stored schema could drift.
    return parsed.filter(
      (m): m is Message =>
        !!m &&
        (m.role === "user" || m.role === "agent") &&
        typeof m.content === "string",
    );
  } catch {
    return [];
  }
}

function saveMessages(messages: Message[]): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(MESSAGES_KEY, JSON.stringify(messages));
  } catch {
    // Best-effort: ignore quota / serialization failures.
  }
}

function clearMessages(): void {
  if (typeof window !== "undefined") sessionStorage.removeItem(MESSAGES_KEY);
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
// Two pools so both of the agent's jobs are always represented: finding a Chicago
// place, and general food-safety questions answered with cited sources. We pick 6
// (3 + 3) per chat session (see the seed helpers) so repeat visits get fresh
// prompts. The roomy /chat page shows all 6; the compact floating popup shows the
// first 4 (a stable 2 + 2 prefix) — a launcher stays small, and six wrapping chips
// overflow the short corner panel. Expanding the popup ADDS the last two rather
// than reshuffling. Each "learn" entry maps to a topic the agent's food_safety_info
// tool covers; each "find" to real neighborhoods.

const FIND_QUERIES = [
  "Safest sushi near Wicker Park",
  "Best options for someone with a compromised immune system near River North",
  "Any High-risk restaurants in Logan Square?",
  "Low-risk pizza in Lincoln Park",
  "Taquerias in Pilsen with a Low risk tier",
  "Safest Thai food near the Loop",
];

const LEARN_QUERIES = [
  "How common is food poisoning in the US?",
  "Which foods carry the highest Listeria risk?",
  "What are safe cooking temperatures?",
  "Who's most at risk from foodborne illness?",
  "What is Salmonella and how do you avoid it?",
  "How does norovirus spread?",
];

const SUGGEST_SEED_KEY = "fsi_chat_suggest_seed";

// Small seeded RNG (mulberry32): a given seed always yields the same picks, so
// the floating popup and the /chat page render IDENTICAL chips within one session
// (the expand must not swap them) while a new session rotates.
function mulberry32(seed: number): () => number {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function seededSample(pool: readonly string[], n: number, rng: () => number): string[] {
  const copy = [...pool];
  for (let i = copy.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [copy[i], copy[j]] = [copy[j], copy[i]];
  }
  return copy.slice(0, n);
}

// 3 "find a place" + 3 "learn", interleaved so both jobs show at a glance.
function pickSuggestions(seed: number): string[] {
  const rng = mulberry32(seed);
  const find = seededSample(FIND_QUERIES, 3, rng);
  const learn = seededSample(LEARN_QUERIES, 3, rng);
  return [find[0], learn[0], find[1], learn[1], find[2], learn[2]];
}

// One rotation seed per chat session, stored next to the session id so the popup
// and the full /chat page (same session) agree, and a brand-new chat rotates.
function getOrCreateSuggestSeed(): number {
  if (typeof window === "undefined") return 0;
  const stored = sessionStorage.getItem(SUGGEST_SEED_KEY);
  if (stored !== null) return Number(stored);
  const seed = Math.floor(Math.random() * 2 ** 31);
  sessionStorage.setItem(SUGGEST_SEED_KEY, String(seed));
  return seed;
}

function rotateSuggestSeed(): number {
  const seed = Math.floor(Math.random() * 2 ** 31);
  if (typeof window !== "undefined") sessionStorage.setItem(SUGGEST_SEED_KEY, String(seed));
  return seed;
}

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

export function ChatInterface({ compact = false }: { compact?: boolean } = {}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  // Picked client-side after mount (depends on sessionStorage), so it stays []
  // during SSR/first paint to avoid a hydration mismatch; chips appear a tick later.
  const [suggestions, setSuggestions] = useState<string[]>([]);
  // Session id is read only when sending a request, never during render, so it
  // lives in a ref. A ref also keeps the client-only localStorage read out of an
  // effect setState (which would trigger a cascading render).
  const sessionIdRef = useRef<string>("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // Guards the persist effect from clobbering a saved transcript with the initial
  // empty state before the load below applies.
  const hydratedRef = useRef(false);

  // Client-only init from sessionStorage (avoids SSR hydration mismatch): the
  // rotation seed and any saved transcript can't be read during SSR, so we set
  // them once post-mount.
  useEffect(() => {
    sessionIdRef.current = getOrCreateSessionId();
    const saved = loadMessages();
    /* eslint-disable react-hooks/set-state-in-effect */
    setSuggestions(pickSuggestions(getOrCreateSuggestSeed()));
    if (saved.length) setMessages(saved);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  // Persist the transcript so it survives the popup -> /chat expand and reloads.
  // Skip the first run so the initial empty render can't overwrite a saved
  // transcript before the mount effect loads it.
  useEffect(() => {
    if (!hydratedRef.current) {
      hydratedRef.current = true;
      return;
    }
    saveMessages(messages);
  }, [messages]);

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
    clearMessages();
    sessionIdRef.current = resetSession();
    // A new chat rotates the starter chips to a fresh set.
    setSuggestions(pickSuggestions(rotateSuggestSeed()));
    setInput("");
    inputRef.current?.focus();
  }

  const isEmpty = messages.length === 0;

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* ── Message area ───────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-4 md:px-8">
        <div className="max-w-2xl mx-auto py-6 flex flex-col gap-4">

          {/* Empty state — welcome + suggestions. In compact (floating-widget)
              mode the big icon + heading are dropped: the panel header already
              says "Ask about food safety", so repeating it here is redundant. */}
          {isEmpty && (
            <div className={`flex flex-col items-center text-center pb-4 ${compact ? "pt-2" : "pt-8"}`}>
              {!compact && (
                <>
                  <span className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-sage/15 mb-4">
                    <MapPin className="w-5 h-5 text-sage" strokeWidth={2} />
                  </span>
                  <h2 className="text-2xl font-semibold tracking-tight mb-2">
                    Ask about food safety
                  </h2>
                </>
              )}
              <p className={`text-base text-muted max-w-[42ch] leading-relaxed ${compact ? "mb-5" : "mb-8"}`}>
                Search by neighborhood, cuisine, or risk level. Ask follow-up
                questions — the agent remembers your session.
              </p>
              <div className="flex flex-wrap gap-2 justify-center">
                {(compact ? suggestions.slice(0, 4) : suggestions).map((s) => (
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
