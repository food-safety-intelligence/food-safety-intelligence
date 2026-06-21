import { describe, expect, it } from "vitest";

import { trendDirection } from "@/lib/scores";

describe("trendDirection", () => {
  it("reports 'stable' when there is no slope (null)", () => {
    expect(trendDirection(null)).toBe("stable");
  });

  it("reports 'worsening' for a clearly rising slope", () => {
    expect(trendDirection(0.01)).toBe("worsening");
    expect(trendDirection(0.0011)).toBe("worsening");
  });

  it("reports 'improving' for a clearly falling slope", () => {
    expect(trendDirection(-0.01)).toBe("improving");
    expect(trendDirection(-0.0011)).toBe("improving");
  });

  it("treats slopes inside the ±0.001 dead band as 'stable'", () => {
    expect(trendDirection(0)).toBe("stable");
    expect(trendDirection(0.0009)).toBe("stable");
    expect(trendDirection(-0.0009)).toBe("stable");
  });

  it("treats the exact ±0.001 boundary as 'stable' (strict comparison)", () => {
    expect(trendDirection(0.001)).toBe("stable");
    expect(trendDirection(-0.001)).toBe("stable");
  });

  it("falls back to 'stable' for a NaN slope", () => {
    expect(trendDirection(Number.NaN)).toBe("stable");
  });
});
