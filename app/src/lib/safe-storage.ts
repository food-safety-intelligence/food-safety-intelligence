/**
 * Guarded Web Storage access.
 *
 * Private-browsing and locked-down modes (Safari Private, Chrome with "block
 * site data" / third-party cookies off) throw a SecurityError on ANY access to
 * `localStorage` / `sessionStorage` — even reading the property, before you call
 * a method. An unguarded access inside a mount effect throws during commit and
 * tears down the whole client tree, which is what made the home search bar (and
 * the chat) dead in an incognito tab.
 *
 * These helpers swallow that failure: a read returns null, a write is a no-op.
 * The only cost is that the value doesn't persist across the session — the
 * correct, invisible degradation in a mode that wipes storage anyway.
 */

type Kind = "local" | "session";

/** The backing Storage, or null if the browser refuses access (or during SSR). */
function backing(kind: Kind): Storage | null {
  try {
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

export function safeGet(kind: Kind, key: string): string | null {
  try {
    return backing(kind)?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

export function safeSet(kind: Kind, key: string, value: string): void {
  try {
    backing(kind)?.setItem(key, value);
  } catch {
    /* private mode or quota exceeded — persistence is best-effort. */
  }
}

export function safeRemove(kind: Kind, key: string): void {
  try {
    backing(kind)?.removeItem(key);
  } catch {
    /* nothing to clear if storage is unavailable. */
  }
}
