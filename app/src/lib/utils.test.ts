import { describe, expect, it } from "vitest";

import { cn, formatDelta, formatInspectionDate, formatScore } from "@/lib/utils";

describe("formatScore", () => {
  it("renders two decimal places", () => {
    expect(formatScore(0.5)).toBe("0.50");
    expect(formatScore(1)).toBe("1.00");
  });

  it("rounds to two places (half-up at the boundary)", () => {
    expect(formatScore(0.125)).toBe("0.13");
    expect(formatScore(0.1234)).toBe("0.12");
  });

  it("keeps a leading zero for sub-1 values and renders 0", () => {
    expect(formatScore(0)).toBe("0.00");
    expect(formatScore(0.07)).toBe("0.07");
  });
});

describe("formatDelta", () => {
  // The negative sign is a Unicode minus (U+2212), NOT an ASCII hyphen — it
  // pairs visually with the "+" and renders evenly in the UI. Pin it exactly so
  // a copy-paste back to a hyphen is caught.
  const MINUS = "−";

  it("prefixes a positive delta with '+' and four decimals", () => {
    expect(formatDelta(0.0123)).toBe("+0.0123");
  });

  it("prefixes a negative delta with a Unicode minus over its magnitude", () => {
    expect(formatDelta(-0.0123)).toBe(`${MINUS}0.0123`);
  });

  it("uses the Unicode minus, not an ASCII hyphen", () => {
    expect(formatDelta(-0.5).startsWith("-")).toBe(false);
    expect(formatDelta(-0.5).startsWith(MINUS)).toBe(true);
  });

  it("renders zero with no sign", () => {
    expect(formatDelta(0)).toBe("0.0000");
  });

  it("rounds the magnitude to four places", () => {
    expect(formatDelta(0.00005)).toBe("+0.0001");
    expect(formatDelta(-0.123456)).toBe(`${MINUS}0.1235`);
  });
});

describe("formatInspectionDate", () => {
  it("formats an ISO date as 'DD Mon YYYY'", () => {
    expect(formatInspectionDate("2026-05-22")).toBe("22 May 2026");
  });

  it("zero-pads a single-digit day", () => {
    expect(formatInspectionDate("2026-01-07")).toBe("07 Jan 2026");
  });

  it("maps each month index correctly (December is not off-by-one)", () => {
    expect(formatInspectionDate("2026-12-31")).toBe("31 Dec 2026");
  });

  it("returns the input unchanged when a part is missing or non-numeric", () => {
    expect(formatInspectionDate("not-a-date")).toBe("not-a-date");
    expect(formatInspectionDate("2026-05")).toBe("2026-05");
  });

  it("returns the input unchanged for a zero month or day (guarded as falsy)", () => {
    expect(formatInspectionDate("2026-00-10")).toBe("2026-00-10");
    expect(formatInspectionDate("2026-05-00")).toBe("2026-05-00");
  });
});

describe("cn", () => {
  it("joins truthy class names with a space", () => {
    expect(cn("a", "b")).toBe("a b");
  });

  it("drops falsy values (conditional classes)", () => {
    expect(cn("a", false, null, undefined, "", "b")).toBe("a b");
    expect(cn("base", true && "on", false && "off")).toBe("base on");
  });

  it("returns an empty string when nothing is truthy", () => {
    expect(cn(false, null, undefined)).toBe("");
  });
});
