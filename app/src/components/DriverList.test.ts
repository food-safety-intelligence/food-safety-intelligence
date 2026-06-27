import { describe, expect, it } from "vitest";

import { driverBarGeometry } from "@/components/DriverList";

describe("driverBarGeometry", () => {
  it("extends right (positive) for a risk-raising factor", () => {
    const g = driverBarGeometry(2, 4);
    expect(g.isPositive).toBe(true);
    expect(g.sign).toBe("+");
    expect(g.halfPct).toBe(25); // 2/4 · 50
  });

  it("extends left (negative) for a risk-lowering factor", () => {
    const g = driverBarGeometry(-2, 4);
    expect(g.isPositive).toBe(false);
    expect(g.sign).toBe("−"); // U+2212 minus, not hyphen
    expect(g.halfPct).toBe(25); // magnitude only
  });

  it("fills the half-track for the largest-magnitude factor", () => {
    expect(driverBarGeometry(4, 4).halfPct).toBe(50);
    expect(driverBarGeometry(-4, 4).halfPct).toBe(50);
  });

  it("renders a zero contribution as a neutral, empty-sign, zero-width bar", () => {
    const g = driverBarGeometry(0, 4);
    expect(g.isPositive).toBe(false);
    expect(g.sign).toBe("");
    expect(g.halfPct).toBe(0);
  });

  it("guards the all-zero list so width is 0, never NaN", () => {
    // maxMagnitude is 0 when every driver's shap is 0 — the divide that used to
    // produce `NaN%` and break the inline style.
    const g = driverBarGeometry(0, 0);
    expect(Number.isNaN(g.halfPct)).toBe(false);
    expect(g.halfPct).toBe(0);
  });

  it("treats a non-positive maxMagnitude defensively (denominator falls back to 1)", () => {
    const g = driverBarGeometry(0.5, -1);
    expect(Number.isFinite(g.halfPct)).toBe(true);
    expect(g.halfPct).toBe(25); // 0.5/1 · 50
  });
});
