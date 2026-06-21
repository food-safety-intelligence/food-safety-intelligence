import { describe, expect, it } from "vitest";

import type { Driver, RestaurantScore } from "@/lib/scores";
import { computeWaterfall, toPinDriver, trendDirection } from "@/lib/scores";

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

describe("computeWaterfall", () => {
  // A toy calibrated logreg: intercept + contributions = raw logit L;
  // Platt maps it to p = sigmoid(-(a*L + b)).
  const cal = { a: -1.2, b: 0.3, intercept: -2.0 };
  const sigmoid = (x: number) => 1 / (1 + Math.exp(-x));

  const restaurant = (shaps: number[], p: number): RestaurantScore => ({
    license_id: "1",
    dba_name: "Test",
    address: "1 St",
    neighborhood: "",
    zip: "",
    facility_type: "",
    lat: 41,
    lon: -87,
    risk_score: p,
    risk_tier: "High",
    trend_slope_90d: null,
    top_drivers: shaps.map((s, i) => ({
      feature: `f${i}`,
      value: "",
      shap: s,
      label: `driver ${i}`,
    })),
  });

  it("scales each driver by -a and signs by raw shap direction", () => {
    const wf = computeWaterfall(restaurant([0.5, -0.4], 0.6), cal);
    expect(wf.steps[0].contribution).toBeCloseTo(1.2 * 0.5, 10); // -a * shap
    expect(wf.steps[0].up).toBe(true);
    expect(wf.steps[1].contribution).toBeCloseTo(1.2 * -0.4, 10);
    expect(wf.steps[1].up).toBe(false);
  });

  it("derives base = -a*intercept - b", () => {
    const wf = computeWaterfall(restaurant([], 0.5), cal);
    expect(wf.base).toBeCloseTo(1.2 * -2.0 - 0.3, 10);
  });

  it("recovers a total whose sigmoid is exactly the risk_score (reconciles)", () => {
    const wf = computeWaterfall(restaurant([0.5], 0.73), cal);
    expect(sigmoid(wf.total)).toBeCloseTo(0.73, 10);
  });

  it("clamps p=1 so the total stays finite", () => {
    const wf = computeWaterfall(restaurant([1.0], 1.0), cal);
    expect(Number.isFinite(wf.total)).toBe(true);
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
