import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  resetReloadLatchForTests,
  shouldStartFreshChat,
  wasPageReloaded,
} from "./ChatInterface";

// The bug this guards against: the Navigation Timing reload flag describes the
// DOCUMENT load and never changes, but ChatInterface remounts on every soft
// navigation. Consuming the flag at every mount wiped the transcript on each
// return to chat whenever the document had been loaded via a refresh.
describe("shouldStartFreshChat (once-per-document reload latch)", () => {
  beforeEach(() => {
    resetReloadLatchForTests();
  });

  it("starts fresh on the first mount after a real reload", () => {
    expect(shouldStartFreshChat(true)).toBe(true);
  });

  it("does NOT wipe again on later mounts of a reloaded document (tab switches)", () => {
    shouldStartFreshChat(true); // first mount after F5 — wipes once
    expect(shouldStartFreshChat(true)).toBe(false); // back to Chat tab
    expect(shouldStartFreshChat(true)).toBe(false); // and again
  });

  it("never wipes when the document was a normal navigation", () => {
    expect(shouldStartFreshChat(false)).toBe(false);
    expect(shouldStartFreshChat(false)).toBe(false);
  });
});

// Pin the Navigation Timing entry the browser would report for a given load, so
// the flag reader can be exercised in the node env (no DOM). The guard needs a
// window with a truthy .performance before it reaches the entry lookup.
function stubNavigationType(type: PerformanceNavigationTiming["type"]): void {
  vi.stubGlobal("window", { performance: globalThis.performance });
  vi.spyOn(performance, "getEntriesByType").mockReturnValue([
    { type } as unknown as PerformanceNavigationTiming,
  ]);
}

describe("wasPageReloaded (reads the Navigation Timing type)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("is true for a browser reload (F5 / Cmd-R)", () => {
    stubNavigationType("reload");
    expect(wasPageReloaded()).toBe(true);
  });

  it("is false for a soft <Link> navigation", () => {
    stubNavigationType("navigate");
    expect(wasPageReloaded()).toBe(false);
  });

  it("is false for a back/forward cache restore", () => {
    stubNavigationType("back_forward");
    expect(wasPageReloaded()).toBe(false);
  });

  it("is false during SSR, when there is no window", () => {
    // No stub: window is undefined in the node env, exactly as on the server.
    expect(wasPageReloaded()).toBe(false);
  });
});

// The regression itself, reproduced end-to-end through both functions (the React
// effect that wires them can't render in the node env, but this pins the logic
// the effect runs). The document was loaded via a refresh, so wasPageReloaded()
// reports true on EVERY mount for the document's life; before the latch that
// reset the chat on every return to the Chat tab. It must reset exactly once.
describe("reload flag + latch together (the June regression)", () => {
  beforeEach(() => {
    resetReloadLatchForTests();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("resets the chat once, though the reload flag stays true across remounts", () => {
    stubNavigationType("reload");
    expect(wasPageReloaded()).toBe(true); // sticky flag...
    expect(shouldStartFreshChat(wasPageReloaded())).toBe(true); // first mount wipes
    expect(wasPageReloaded()).toBe(true); // ...still true on later mounts...
    expect(shouldStartFreshChat(wasPageReloaded())).toBe(false); // tab switch: kept
    expect(shouldStartFreshChat(wasPageReloaded())).toBe(false); // and again: kept
  });

  it("never resets when the document arrived via a normal navigation", () => {
    stubNavigationType("navigate");
    expect(shouldStartFreshChat(wasPageReloaded())).toBe(false);
    expect(shouldStartFreshChat(wasPageReloaded())).toBe(false);
  });
});
