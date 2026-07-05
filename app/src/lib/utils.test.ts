import { describe, expect, it } from "vitest";

import {
  applyTrendPan,
  applyTrendZoom,
  cn,
  dateAxisTicks,
  formatDelta,
  formatInspectionDate,
  formatScore,
  TREND_MIN_WIDTH,
} from "@/lib/utils";

const utc = (iso: string) => Date.parse(`${iso}T00:00:00Z`);

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

describe("applyTrendZoom", () => {
  it("narrows the window toward the focus point, keeping it fixed", () => {
    // Zoom in at the right edge (focus = 1): the end stays pinned, start moves in.
    const [s, e] = applyTrendZoom(0, 1, 1, 0.5);
    expect(e).toBeCloseTo(1, 10);
    expect(s).toBeCloseTo(0.5, 10);
  });

  it("keeps a centre focus centred", () => {
    const [s, e] = applyTrendZoom(0, 1, 0.5, 0.5);
    expect(s).toBeCloseTo(0.25, 10);
    expect(e).toBeCloseTo(0.75, 10);
  });

  it("floors the visible width at TREND_MIN_WIDTH", () => {
    const [s, e] = applyTrendZoom(0, 1, 0.5, 0.001);
    expect(e - s).toBeCloseTo(TREND_MIN_WIDTH, 10);
  });

  it("never zooms out past the full [0,1] range", () => {
    const [s, e] = applyTrendZoom(0.4, 0.6, 0.5, 100);
    expect(s).toBe(0);
    expect(e).toBe(1);
  });
});

describe("applyTrendPan", () => {
  it("slides the window by the pixel delta, preserving its width", () => {
    // Window [0.25,0.75] (width 0.5) over a 100px plot; drag left 20px → +0.1.
    const [s, e] = applyTrendPan(0.25, 0.75, -20, 100);
    expect(e - s).toBeCloseTo(0.5, 10);
    expect(s).toBeCloseTo(0.35, 10);
  });

  it("clamps at the edges without shrinking the window", () => {
    const [s, e] = applyTrendPan(0, 0.5, 500, 100);
    expect(s).toBe(0);
    expect(e).toBeCloseTo(0.5, 10);
  });
});

describe("dateAxisTicks", () => {
  it("labels a multi-year span by year on Jan-1 boundaries", () => {
    const ticks = dateAxisTicks(utc("2019-03-01"), utc("2026-09-01"), 4);
    expect(ticks.length).toBeGreaterThanOrEqual(2);
    // Every tick lands on a January 1st and is labelled with the bare year.
    for (const tk of ticks) {
      const d = new Date(tk.ms);
      expect(d.getUTCMonth()).toBe(0);
      expect(d.getUTCDate()).toBe(1);
      expect(tk.label).toBe(String(d.getUTCFullYear()));
    }
  });

  it("uses a finer unit (days) when zoomed into a few weeks", () => {
    const ticks = dateAxisTicks(utc("2026-06-01"), utc("2026-06-30"), 4);
    // Day/short-range labels read "Mon D", not a bare year.
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    expect(ticks[0].label).toMatch(/^[A-Z][a-z]{2} \d{1,2}$/);
  });

  it("keeps all ticks within the visible range", () => {
    const start = utc("2022-05-10");
    const end = utc("2024-11-20");
    for (const tk of dateAxisTicks(start, end, 4)) {
      expect(tk.ms).toBeGreaterThanOrEqual(start);
      expect(tk.ms).toBeLessThanOrEqual(end);
    }
  });

  it("scales the tick count up with the target", () => {
    const range = [utc("2020-01-01"), utc("2026-01-01")] as const;
    const few = dateAxisTicks(range[0], range[1], 3).length;
    const many = dateAxisTicks(range[0], range[1], 7).length;
    expect(many).toBeGreaterThan(few);
  });

  it("still returns labelled ticks for a degenerate (near-zero) span", () => {
    // Off a day boundary with zero width: no calendar boundary falls inside, so
    // it falls back to the two endpoints rather than returning nothing.
    const t = utc("2026-06-15") + 1000; // 1s past midnight
    const ticks = dateAxisTicks(t, t, 4);
    expect(ticks).toHaveLength(2);
    expect(ticks.every((tk) => tk.ms === t)).toBe(true);
    expect(ticks[0].label).toMatch(/\d{4}$/); // "Jun 2026"

    // On a boundary, the single boundary instant is a valid lone tick.
    const onBoundary = dateAxisTicks(utc("2026-06-15"), utc("2026-06-15"), 4);
    expect(onBoundary.length).toBeGreaterThanOrEqual(1);
  });
});
