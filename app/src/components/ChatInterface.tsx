"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, RotateCcw, AlertCircle, MapPin, Store, X } from "lucide-react";
import { queryAgent, scopedInputBudget } from "@/lib/agent-api";
import type { ChatEstablishment } from "@/components/ChatScopeContext";
import { CITY_CONFIG, type City } from "@/lib/city";
import { useCity } from "@/components/CityContext";
import { Tooltip } from "@/components/Tooltip";

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

// True only when this page load is a browser reload (F5 / Cmd-R). The popup ->
// /chat expand is a <Link> click (a soft navigation, type "navigate"), so the
// Navigation Timing type tells the two apart: a reload should start a fresh
// conversation, the soft navigation should carry the transcript over.
function wasPageReloaded(): boolean {
  if (typeof window === "undefined" || !window.performance) return false;
  const [nav] = performance.getEntriesByType(
    "navigation",
  ) as PerformanceNavigationTiming[];
  return nav?.type === "reload";
}

// The transcript is persisted to sessionStorage so it survives the floating
// popup -> /chat expand (a <Link> navigation that remounts ChatInterface) within
// the same tab session. Without this the new mount starts empty and the
// conversation — and the history sent to the agent — is lost. A browser reload
// deliberately does NOT carry it over (see wasPageReloaded): a refresh starts a
// fresh chat.
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
// Handles **bold**, [label](url) links, numbered lists, and newlines without
// adding a dependency. The agent cites sources as markdown links, so without
// link support those render as raw "[CDC ...](https://...)" text.

// Inline tokens we recognise: **bold** and [label](url). Split on a capturing
// group so the delimiters survive the split and each token can be rendered.
const INLINE_TOKEN = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g;
const LINK_TOKEN = /^\[([^\]]+)\]\(([^)]+)\)$/;

function renderInline(line: string): React.ReactNode[] {
  return line.split(INLINE_TOKEN).map((seg, j) => {
    if (seg.startsWith("**") && seg.endsWith("**")) {
      return <strong key={j}>{seg.slice(2, -2)}</strong>;
    }
    const link = LINK_TOKEN.exec(seg);
    if (link) {
      const [, label, href] = link;
      // Only http(s) links become clickable; any other scheme (javascript:,
      // data:) renders as plain text so a model reply can't inject a live
      // attack vector into the page.
      if (/^https?:\/\//i.test(href)) {
        return (
          <a
            key={j}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            // sage-strong (not sage) clears AA contrast for text; the underline
            // is a non-colour cue so the link reads as a link without relying
            // on colour alone.
            className="text-sage-strong underline underline-offset-2 hover:text-ink break-words"
          >
            {label}
          </a>
        );
      }
      return label;
    }
    return seg;
  });
}

function renderContent(text: string): React.ReactNode[] {
  return text.split("\n").map((line, i) => (
    <span key={i} className="block">
      {renderInline(line)}
    </span>
  ));
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

// "Find" prompts name real neighborhoods, so they're per-city (DR 0016).
const FIND_QUERIES_BY_CITY: Record<City, string[]> = {
  chicago: [
    "Safest sushi near Wicker Park",
    "Best options for someone with a compromised immune system near River North",
    "Any High-risk restaurants in Logan Square?",
    "Low-risk pizza in Lincoln Park",
    "Taquerias in Pilsen with a Low risk tier",
    "Safest Thai food near the Loop",
  ],
  nyc: [
    "Safest sushi near the Lower East Side",
    "Best options for someone with a compromised immune system near Harlem",
    "Any High-risk restaurants in Williamsburg?",
    "Low-risk pizza in Astoria",
    "Dumplings in Flushing with a Low risk tier",
    "Safest Thai food near Midtown",
  ],
  la: [
    "Safest sushi near Silver Lake",
    "Best options for someone with a compromised immune system near Koreatown",
    "Any High-risk restaurants in Downtown LA?",
    "Low-risk pizza in Santa Monica",
    "Taquerias in Boyle Heights with a Low risk tier",
    "Safest Thai food near Hollywood",
  ],
};

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
function pickSuggestions(seed: number, city: City): string[] {
  const rng = mulberry32(seed);
  const find = seededSample(FIND_QUERIES_BY_CITY[city], 3, rng);
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

export function ChatInterface({
  compact = false,
  establishment,
}: {
  compact?: boolean;
  /** Establishment whose detail page is in view; scopes "this restaurant". */
  establishment?: ChatEstablishment | null;
} = {}) {
  const { city } = useCity();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  // The establishment the user dismissed the scope chip for. Scoping is on while
  // an establishment is in view AND the user hasn't dismissed this one.
  const [dismissedId, setDismissedId] = useState<string | null>(null);

  // Reset the dismissal whenever the in-view establishment changes — including
  // leaving a detail page (undefined) and returning — so each fresh arrival
  // shows the chip again rather than staying hidden from a stale dismiss. This
  // is the "adjust state during render on prop change" pattern (React docs),
  // which avoids an extra effect + render.
  const lastScopeRef = useRef<string | null | undefined>(establishment?.licenseId);
  if (lastScopeRef.current !== establishment?.licenseId) {
    lastScopeRef.current = establishment?.licenseId;
    if (dismissedId !== null) setDismissedId(null);
  }
  const scoped =
    establishment && establishment.licenseId !== dismissedId
      ? establishment
      : null;
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
    // A browser refresh starts a fresh conversation. The transcript is meant to
    // survive the popup -> /chat expand (a <Link> soft navigation), not a reload,
    // so on a reload we drop the saved transcript and start a new session.
    if (wasPageReloaded()) {
      clearMessages();
      sessionIdRef.current = resetSession();
    } else {
      sessionIdRef.current = getOrCreateSessionId();
    }
    const saved = loadMessages();
    /* eslint-disable react-hooks/set-state-in-effect */
    setSuggestions(pickSuggestions(getOrCreateSuggestSeed(), city));
    if (saved.length) setMessages(saved);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  // Re-pick the starter chips when the city changes — the "find" prompts name
  // real neighborhoods, so they're city-specific (same seed → stable per session).
  // The seed comes from sessionStorage (browser-only), so this can't be derived
  // during render; the setState here mirrors the mount effect above.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSuggestions(pickSuggestions(getOrCreateSuggestSeed(), city));
  }, [city]);

  // Persist the transcript so it survives the popup -> /chat expand. Skip the
  // first run so the initial empty render can't overwrite a saved transcript
  // before the mount effect loads it.
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
      // Pass the in-view establishment (when not dismissed) so the agent
      // resolves "this restaurant". The stored user turn above keeps the clean
      // typed text; only the wire query carries the context tag.
      const result = await queryAgent(
        trimmed,
        sessionIdRef.current,
        history,
        scoped ?? undefined,
        city,
      );
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
    setSuggestions(pickSuggestions(rotateSuggestSeed(), city));
    setInput("");
    inputRef.current?.focus();
  }

  const isEmpty = messages.length === 0;

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* ── Scope chip ─────────────────────────────────────────────────────────
          Shown while a detail page is in view: the chat scopes "this restaurant"
          to it. The icon + "Asking about" label carry the meaning without relying
          on colour; ✕ drops the scope for a general question (re-armed on the
          next establishment). */}
      {scoped && (
        <div className="flex-none flex items-center gap-2 px-4 md:px-8 py-2 border-b border-line bg-sage/5">
          <Store
            className="w-4 h-4 text-sage-strong flex-none"
            strokeWidth={2}
            aria-hidden
          />
          {/* Whole line is ink (AA: 10.35:1 on the tint) — hierarchy comes from
              weight, not a faint colour, so the label clears AA for small text.
              truncate keeps it to one line; the Tooltip reveals the full name on
              hover when it overflows (the name is also in the placeholder and the
              ✕'s aria-label, and screen readers read the untruncated text). */}
          <Tooltip content={scoped.name} onlyWhenTruncated className="flex-1 min-w-0">
            <p className="min-w-0 flex-1 text-sm text-ink truncate">
              Asking about <span className="font-medium">{scoped.name}</span>
            </p>
          </Tooltip>
          <Tooltip content="Ask about anything instead" align="end" className="flex-none">
            <button
              type="button"
              onClick={() => setDismissedId(scoped.licenseId)}
              aria-label={`Stop scoping the chat to ${scoped.name}`}
              className="p-1 rounded-full text-muted hover:text-terra hover:bg-terra/10 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal"
            >
              <X className="w-4 h-4" strokeWidth={2} />
            </button>
          </Tooltip>
        </div>
      )}

      {/* NYC notice — the agent backend only has Chicago data (DR 0016). Be
          honest: general food-safety questions work, establishment lookups don't. */}
      {!CITY_CONFIG[city].chatSupported && (
        <div className="flex-none flex items-start gap-2 px-4 md:px-8 py-2.5 border-b border-line bg-amber/10 text-xs text-ink/80">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5 text-amber" aria-hidden />
          <span>
            You&apos;re viewing <strong>{CITY_CONFIG[city].label}</strong>. The
            assistant currently has data for <strong>Chicago</strong> establishments
            only — general food-safety questions work, but it can&apos;t look up a
            specific {CITY_CONFIG[city].label} place yet.
          </span>
        </div>
      )}

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
                  {/* "Eatelligence" = Eat + intelligence; sage "Eat" stem
                      (sage-strong clears AA) plays up the pun. */}
                  <h2 className="text-2xl font-semibold tracking-tight mb-2">
                    <span className="text-sage-strong">Eat</span>elligence
                  </h2>
                </>
              )}
              <p className={`text-base text-muted max-w-[42ch] leading-relaxed ${compact ? "mb-5" : "mb-8"}`}>
                Ask about a specific place, a neighborhood or cuisine, or food
                safety in general.
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
              placeholder={
                scoped
                  ? `Ask about ${scoped.name}…`
                  : "Ask about a neighborhood, cuisine, or risk level…"
              }
              disabled={loading}
              aria-label="Chat input"
              // When scoped, the context tag is prepended to the wire query;
              // cap the user's text so tag + text stay within the proxy's limit.
              maxLength={scoped ? scopedInputBudget(scoped) : undefined}
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
            {city === "nyc"
              ? "Next-inspection model predictions from public New York City data"
              : city === "la"
                ? "Next-inspection model predictions from public Los Angeles County data"
                : "180-day model predictions from public Chicago data"}
            , not a safety verdict or city inspection{" "}
            (
            <a
              href="/how-it-works#reading-the-score"
              className="text-teal underline underline-offset-2 hover:text-ink transition-colors"
            >
              how the score works
            </a>
            ) · any diner reviews shown are unverified
          </p>
        </div>
      </div>
    </div>
  );
}
