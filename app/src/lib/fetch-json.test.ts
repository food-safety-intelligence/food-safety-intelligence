import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchJson } from "@/lib/fetch-json";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/** A fetch Response stand-in carrying a JSON body. */
function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as Response;
}

describe("fetchJson", () => {
  it("returns parsed JSON without retrying on first success", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ total: 3 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchJson<{ total: number }>("/x.json")).resolves.toEqual({ total: 3 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("retries a transient failure and then succeeds", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("network"))
      .mockResolvedValueOnce(jsonResponse({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    const promise = fetchJson("/x.json", { retries: 2 });
    await vi.runAllTimersAsync();

    await expect(promise).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("retries a non-ok response, then throws after exhausting retries", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(null, false, 503));
    vi.stubGlobal("fetch", fetchMock);

    const promise = fetchJson("/x.json", { retries: 2 });
    // Attach a rejection handler up-front so the eventual throw isn't unhandled.
    const settled = expect(promise).rejects.toThrow(/503/);
    await vi.runAllTimersAsync();
    await settled;
    // 1 initial attempt + 2 retries.
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not retry once the caller's signal has aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    const fetchMock = vi.fn().mockImplementation(() => {
      throw new DOMException("Aborted", "AbortError");
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchJson("/x.json", { signal: controller.signal })).rejects.toThrow();
    // The abort short-circuits the retry loop after the first attempt.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
