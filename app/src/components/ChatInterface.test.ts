import { beforeEach, describe, expect, it } from "vitest";
import {
  resetReloadLatchForTests,
  shouldStartFreshChat,
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
