import { describe, expect, it } from "vitest";

import type {
  Driver,
  RestaurantScore,
  RiskTier,
  SearchIndex,
  SearchIndexRow,
} from "@/lib/scores";
import {
  ALL_TIERS,
  computeHomeView,
  computeWaterfall,
  isAllTiers,
  matchesQuery,
  parseSort,
  parseTiers,
  toPinDriver,
  trendDirection,
} from "@/lib/scores";

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
    trend_slope: null,
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
    expect(trendDirection(0.0004)).toBe("worsening");
  });

  it("reports 'improving' for a clearly falling slope", () => {
    expect(trendDirection(-0.01)).toBe("improving");
    expect(trendDirection(-0.0004)).toBe("improving");
  });

  it("treats slopes inside the ±0.0003 dead band as 'stable'", () => {
    expect(trendDirection(0)).toBe("stable");
    expect(trendDirection(0.0002)).toBe("stable");
    expect(trendDirection(-0.0002)).toBe("stable");
  });

  it("treats the exact ±0.0003 boundary as 'stable' (strict comparison)", () => {
    expect(trendDirection(0.0003)).toBe("stable");
    expect(trendDirection(-0.0003)).toBe("stable");
  });

  it("falls back to 'stable' for a NaN slope", () => {
    expect(trendDirection(Number.NaN)).toBe("stable");
  });
});

describe("parseTiers", () => {
  it("returns all tiers when the param is absent", () => {
    expect(parseTiers(undefined)).toEqual(ALL_TIERS);
  });

  it("returns all tiers for an empty string", () => {
    expect(parseTiers("")).toEqual(ALL_TIERS);
  });

  it("keeps only the valid tiers, in canonical order", () => {
    // Input order is ignored — the result follows ALL_TIERS order.
    expect(parseTiers("High,Low")).toEqual(["Low", "High"]);
  });

  it("drops unknown values", () => {
    expect(parseTiers("Low,Bogus,High")).toEqual(["Low", "High"]);
  });

  it("falls back to all tiers when every value is invalid", () => {
    expect(parseTiers("Bogus,Nope")).toEqual(ALL_TIERS);
  });

  it("de-duplicates repeated tiers", () => {
    expect(parseTiers("Low,Low")).toEqual(["Low"]);
  });
});

describe("isAllTiers", () => {
  it("is true when every tier is selected", () => {
    expect(isAllTiers([...ALL_TIERS])).toBe(true);
  });

  it("is false for a strict subset", () => {
    expect(isAllTiers(["Low", "High"] as RiskTier[])).toBe(false);
  });

  it("is false for the empty selection", () => {
    expect(isAllTiers([])).toBe(false);
  });
});

describe("matchesQuery", () => {
  const row = { dba_name: "Pizza Palace", address: "123 Main St" };

  it("matches everything when the query is empty or whitespace", () => {
    expect(matchesQuery(row, "")).toBe(true);
    expect(matchesQuery(row, "   ")).toBe(true);
  });

  it("matches a case-insensitive substring of the name", () => {
    expect(matchesQuery(row, "PIZZA")).toBe(true);
    expect(matchesQuery(row, "palace")).toBe(true);
  });

  it("matches against the address too", () => {
    expect(matchesQuery(row, "main st")).toBe(true);
  });

  it("trims surrounding whitespace before matching", () => {
    expect(matchesQuery(row, "  pizza  ")).toBe(true);
  });

  it("returns false when neither name nor address contains the query", () => {
    expect(matchesQuery(row, "sushi")).toBe(false);
  });
});

describe("parseSort", () => {
  it("accepts the two non-default sorts", () => {
    expect(parseSort("name")).toBe("name");
    expect(parseSort("low")).toBe("low");
  });

  it("defaults to risk for missing or unknown values", () => {
    expect(parseSort("risk")).toBe("risk");
    expect(parseSort(null)).toBe("risk");
    expect(parseSort(undefined)).toBe("risk");
    expect(parseSort("garbage")).toBe("risk");
  });
});

describe("computeHomeView", () => {
  const mk = (
    license_id: string,
    dba_name: string,
    risk_score: number,
    risk_tier: RiskTier,
    coords: boolean,
  ): SearchIndexRow => ({
    license_id,
    dba_name,
    address: `${license_id} Main St`,
    lat: coords ? 41.9 : null,
    lon: coords ? -87.6 : null,
    risk_score,
    risk_tier,
    trend_slope: null,
    top_driver: null,
  });

  const INDEX: SearchIndex = {
    schema_version: "1",
    generated_at: null,
    total: 4,
    tier_counts: { Low: 1, Moderate: 1, Elevated: 1, High: 1 },
    rows: [
      mk("1", "Zeta Pizza", 0.9, "High", true),
      mk("2", "Bravo Tacos", 0.5, "Elevated", true),
      mk("3", "Alpha Pizza", 0.2, "Moderate", false), // no coords
      mk("4", "Delta Diner", 0.1, "Low", true),
    ],
  };

  const opts = (o: Partial<Parameters<typeof computeHomeView>[1]> = {}) => ({
    q: "",
    tiers: [...ALL_TIERS],
    sort: "risk" as const,
    listLimit: 100,
    ...o,
  });

  const ids = (rows: { license_id: string }[]) => rows.map((r) => r.license_id);

  it("defaults to all rows, highest-risk first, with full counts", () => {
    const v = computeHomeView(INDEX, opts());
    expect(ids(v.listRows)).toEqual(["1", "2", "3", "4"]);
    expect(v.matchCount).toBe(4);
    expect(v.total).toBe(4);
    expect(v.tierCounts).toEqual(INDEX.tier_counts);
  });

  it("filters by case-insensitive query over name + address", () => {
    const v = computeHomeView(INDEX, opts({ q: "PIZZA" }));
    expect(ids(v.listRows)).toEqual(["1", "3"]);
    expect(v.matchCount).toBe(2);
  });

  it("filters by tier", () => {
    const v = computeHomeView(INDEX, opts({ tiers: ["High"] }));
    expect(ids(v.listRows)).toEqual(["1"]);
  });

  it("sorts lowest-risk first", () => {
    expect(ids(computeHomeView(INDEX, opts({ sort: "low" })).listRows)).toEqual([
      "4",
      "3",
      "2",
      "1",
    ]);
  });

  it("sorts alphabetically by name", () => {
    expect(ids(computeHomeView(INDEX, opts({ sort: "name" })).listRows)).toEqual([
      "3",
      "2",
      "4",
      "1",
    ]);
  });

  it("caps the list but keeps the true match count", () => {
    const v = computeHomeView(INDEX, opts({ listLimit: 2 }));
    expect(v.listRows).toHaveLength(2);
    expect(v.matchCount).toBe(4);
  });

  it("drops rows without coordinates from the map pins", () => {
    const v = computeHomeView(INDEX, opts());
    expect(ids(v.pins)).toEqual(["1", "2", "4"]); // "3" has null lat/lon
  });
});
