import { describe, expect, it } from "vitest";
import {
  bitsForSlugs,
  matchesViolations,
  parseViol,
  VIOLATION_CATEGORIES,
} from "./violations";

describe("VIOLATION_CATEGORIES", () => {
  it("has six categories with unique slugs and ids matching array order", () => {
    expect(VIOLATION_CATEGORIES).toHaveLength(6);
    const slugs = VIOLATION_CATEGORIES.map((c) => c.slug);
    expect(new Set(slugs).size).toBe(6);
    VIOLATION_CATEGORIES.forEach((c, i) => expect(c.id).toBe(i));
  });
});

describe("parseViol", () => {
  it("returns [] for absent or empty input", () => {
    expect(parseViol(null)).toEqual([]);
    expect(parseViol(undefined)).toEqual([]);
    expect(parseViol("")).toEqual([]);
  });

  it("keeps only known slugs, in canonical taxonomy order", () => {
    expect(parseViol("temp,pests")).toEqual(["pests", "temp"]);
    expect(parseViol("bogus,temp")).toEqual(["temp"]);
    expect(parseViol("bogus")).toEqual([]);
  });

  it("dedupes repeated slugs", () => {
    expect(parseViol("pests,pests")).toEqual(["pests"]);
  });
});

describe("bitsForSlugs / matchesViolations", () => {
  it("round-trips slugs to a bitmask", () => {
    expect(bitsForSlugs([])).toBe(0);
    expect(bitsForSlugs(["pests"])).toBe(0b1);
    expect(bitsForSlugs(["pests", "temp"])).toBe(0b11);
  });

  it("matches everything when no filter is active", () => {
    expect(matchesViolations(undefined, 0)).toBe(true);
    expect(matchesViolations(0, 0)).toBe(true);
    expect(matchesViolations(0b100, 0)).toBe(true);
  });

  it("never matches rows without vc when a filter is active", () => {
    expect(matchesViolations(undefined, 0b1)).toBe(false);
    expect(matchesViolations(0, 0b1)).toBe(false);
  });

  it("ORs across selected categories", () => {
    expect(matchesViolations(0b100, 0b101)).toBe(true);
    expect(matchesViolations(0b010, 0b101)).toBe(false);
  });

  it("all six selected still excludes clean rows (spec: not a no-op)", () => {
    const all = bitsForSlugs(VIOLATION_CATEGORIES.map((c) => c.slug));
    expect(matchesViolations(0, all)).toBe(false);
    expect(matchesViolations(undefined, all)).toBe(false);
    expect(matchesViolations(1 << 5, all)).toBe(true);
  });
});
