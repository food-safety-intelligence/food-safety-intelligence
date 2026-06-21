import { describe, expect, it } from "vitest";

import type { Driver } from "@/lib/scores";
import { toPinDriver, trendDirection } from "@/lib/scores";

const driver = (over: Partial<Driver> = {}): Driver => ({
  feature: "prior_fails",
  value: "3",
  shap: 0.4,
  label: "3 failed inspections previously",
  ...over,
});

describe("toPinDriver", () => {
  it("keeps the feature key and label, dropping value + shap magnitude", () => {
    const pin = toPinDriver(driver());
    expect(pin).toEqual({
      feature: "prior_fails",
      label: "3 failed inspections previously",
      up: true,
    });
  });

  it("marks a positive shap as raising risk (up=true)", () => {
    expect(toPinDriver(driver({ shap: 0.01 })).up).toBe(true);
  });

  it("marks a negative shap as lowering risk (up=false)", () => {
    expect(toPinDriver(driver({ shap: -0.5 })).up).toBe(false);
  });

  it("treats a zero shap as not-raising (up=false)", () => {
    expect(toPinDriver(driver({ shap: 0 })).up).toBe(false);
  });
});

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
