/**
 * Fetch and parse a JSON file, retrying a few times on a transient failure.
 *
 * The home search / tier filter / sort and the inspector worklist can't produce
 * results until the client search index lands, and that payload is several
 * megabytes. On a cold first visit (no browser cache) a single dropped
 * connection during that download would otherwise leave those controls silently
 * dead for the whole session — the reason new visitors sometimes found search
 * and filter unresponsive while returning visitors (served from cache) did not.
 * A bounded retry with backoff turns a transient blip into a short delay rather
 * than a permanent break.
 *
 * Pass a caller `signal` (e.g. an AbortController tied to unmount / city switch)
 * so a stale in-flight load stops retrying instead of racing a newer one.
 */
export async function fetchJson<T>(
  url: string,
  { retries = 3, signal }: { retries?: number; signal?: AbortSignal } = {},
): Promise<T> {
  let lastErr: unknown;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await fetch(url, { signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return (await res.json()) as T;
    } catch (err) {
      // A caller-initiated abort is intentional, not a transient failure — stop
      // immediately and propagate so the caller can ignore the stale load.
      if (signal?.aborted) throw err;
      lastErr = err;
      // Back off before the next attempt (250ms, 500ms, 1s, …); skip the wait
      // after the final try.
      if (attempt < retries) {
        await new Promise((resolve) => setTimeout(resolve, 250 * 2 ** attempt));
      }
    }
  }
  throw lastErr;
}
