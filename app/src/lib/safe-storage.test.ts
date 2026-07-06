import { afterEach, describe, expect, it, vi } from "vitest";

import { safeGet, safeRemove, safeSet } from "@/lib/safe-storage";

afterEach(() => {
  vi.unstubAllGlobals();
});

/** A minimal in-memory Storage stand-in. */
function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => void map.set(k, v),
    removeItem: (k) => void map.delete(k),
    clear: () => map.clear(),
    key: (i) => [...map.keys()][i] ?? null,
    get length() {
      return map.size;
    },
  } as Storage;
}

describe("safe-storage", () => {
  it("reads and writes through when storage works", () => {
    vi.stubGlobal("window", { localStorage: memoryStorage(), sessionStorage: memoryStorage() });
    safeSet("local", "k", "v");
    expect(safeGet("local", "k")).toBe("v");
    safeRemove("local", "k");
    expect(safeGet("local", "k")).toBeNull();
  });

  it("keeps local and session separate", () => {
    vi.stubGlobal("window", { localStorage: memoryStorage(), sessionStorage: memoryStorage() });
    safeSet("local", "k", "L");
    safeSet("session", "k", "S");
    expect(safeGet("local", "k")).toBe("L");
    expect(safeGet("session", "k")).toBe("S");
  });

  it("does not throw when the property access itself throws (private mode)", () => {
    // Safari Private / Chrome-with-site-data-blocked throw on ANY access to the
    // storage property — the failure this whole module exists to absorb.
    vi.stubGlobal("window", {
      get localStorage(): Storage {
        throw new DOMException("The operation is insecure.", "SecurityError");
      },
      get sessionStorage(): Storage {
        throw new DOMException("The operation is insecure.", "SecurityError");
      },
    });
    expect(() => safeSet("local", "k", "v")).not.toThrow();
    expect(safeGet("local", "k")).toBeNull();
    expect(() => safeRemove("local", "k")).not.toThrow();
    expect(() => safeGet("session", "k")).not.toThrow();
  });

  it("does not throw when a method call throws (quota / disabled)", () => {
    const thrower = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    } as unknown as Storage;
    vi.stubGlobal("window", { localStorage: thrower, sessionStorage: thrower });
    expect(() => safeSet("local", "k", "v")).not.toThrow();
    expect(safeGet("local", "k")).toBeNull();
    expect(() => safeRemove("local", "k")).not.toThrow();
  });
});
