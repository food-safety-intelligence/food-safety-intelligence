import { describe, expect, it } from "vitest";
import { latestScoredEvent, tagViolations } from "./violation-tagging.mjs";

describe("tagViolations", () => {
  it("returns 0 for empty or violation-free text", () => {
    expect(tagViolations("")).toBe(0);
    expect(tagViolations(null)).toBe(0);
    expect(tagViolations(undefined)).toBe(0);
    expect(tagViolations("license renewal paperwork on file")).toBe(0);
  });

  // Real headline shapes from the three cities (bit 0 = pests, 1 = temp,
  // 2 = contamination, 3 = hygiene, 4 = sanitizing, 5 = facility).
  it("tags Chicago violation names", () => {
    expect(tagViolations("38. INSECTS, RODENTS, & ANIMALS NOT PRESENT")).toBe(0b1);
    expect(
      tagViolations("5. PROCEDURES FOR RESPONDING TO VOMITING AND DIARRHEAL EVENTS"),
    ).toBe(0);
  });

  it("tags NYC free-text violations", () => {
    expect(
      tagViolations(
        "Evidence of mice or live mice in establishment's food or non-food areas.",
      ),
    ).toBe(0b1);
    expect(tagViolations("Food not cooled by an approved method.")).toBe(0b10);
  });

  it("tags LA requirement-style headlines", () => {
    expect(tagViolations("# 44. FLOORS, WALLS AND CEILINGS: PROPERLY BUILT")).toBe(1 << 5);
    expect(tagViolations("FOOD CONTACT SURFACES: CLEAN AND SANITIZED")).toBe(1 << 4);
  });

  it("sets multiple bits for multi-violation text", () => {
    const text = [
      "38. INSECTS, RODENTS, & ANIMALS NOT PRESENT",
      "21. COLD HOLDING temperature above 41F",
    ].join("\n");
    expect(tagViolations(text)).toBe(0b11);
  });
});

describe("latestScoredEvent", () => {
  const events = [
    { date: "2026-05-01", headline: "newest" },
    { date: "2026-01-15", headline: "scored" },
    { date: "2025-11-02", headline: "old" },
  ];

  it("prefers the event matching as_of_date", () => {
    expect(latestScoredEvent(events, "2026-01-15")).toEqual({
      event: events[1],
      index: 1,
    });
  });

  it("falls back to the newest event when no date matches", () => {
    expect(latestScoredEvent(events, "2020-01-01")).toEqual({
      event: events[0],
      index: 0,
    });
    expect(latestScoredEvent(events, null)).toEqual({
      event: events[0],
      index: 0,
    });
  });

  it("returns null for missing or empty history", () => {
    expect(latestScoredEvent(undefined, "2026-01-01")).toBeNull();
    expect(latestScoredEvent([], null)).toBeNull();
  });
});
