import { describe, expect, it } from "vitest";

import { arcPath } from "@/components/ArcGauge";

// Parse "M x1 y1 A rx ry 0 largeArc sweepFlag x2 y2" into its numeric parts.
function parseArc(d: string) {
  const t = d.split(" ").filter((tok) => tok !== "M" && tok !== "A");
  return {
    x1: Number(t[0]),
    y1: Number(t[1]),
    rx: Number(t[2]),
    ry: Number(t[3]),
    largeArc: Number(t[5]),
    sweepFlag: Number(t[6]),
    x2: Number(t[7]),
    y2: Number(t[8]),
  };
}

// Mirrors ArcGauge's own geometry so endpoint expectations stay in sync.
const CX = 110;
const CY = 110;
const R = 88; // size 220 → size/2 - 22
const START = 225; // lower-left endpoint

describe("arcPath", () => {
  it("returns an empty path for a zero, negative, or NaN sweep", () => {
    // A zero/empty value arc (e.g. score 0) must render nothing, not "M NaN …".
    expect(arcPath(CX, CY, R, START, 0)).toBe("");
    expect(arcPath(CX, CY, R, START, -10)).toBe("");
    expect(arcPath(CX, CY, R, START, Number.NaN)).toBe("");
  });

  it("places the start point at the lower-left 225° endpoint", () => {
    const { x1, y1, rx, ry } = parseArc(arcPath(CX, CY, R, START, 270));
    expect(rx).toBe(R);
    expect(ry).toBe(R);
    // 225°: x = cx + r·cos225 (left of centre), y = cy − r·sin225 (below centre).
    expect(x1).toBeCloseTo(CX + R * Math.cos((Math.PI / 180) * 225), 4);
    expect(y1).toBeCloseTo(CY - R * Math.sin((Math.PI / 180) * 225), 4);
  });

  it("sets large-arc-flag from the sweep SIZE (minor <180°, major >180°)", () => {
    expect(parseArc(arcPath(CX, CY, R, START, 90)).largeArc).toBe(0);
    expect(parseArc(arcPath(CX, CY, R, START, 179)).largeArc).toBe(0);
    expect(parseArc(arcPath(CX, CY, R, START, 180)).largeArc).toBe(0); // boundary
    expect(parseArc(arcPath(CX, CY, R, START, 181)).largeArc).toBe(1);
    expect(parseArc(arcPath(CX, CY, R, START, 270)).largeArc).toBe(1);
  });

  it("keeps sweep-flag constant at 1 for EVERY sweep (the arc-flag bug fix)", () => {
    // The old bug tied sweep-flag to large-arc, so partial value arcs (≤180°)
    // reversed direction and bulged through the gauge centre. Sweep-flag is the
    // rotational sense only — it must stay 1 regardless of sweep size.
    for (const sweep of [1, 43.2, 90, 135, 179, 180, 181, 200, 269, 270]) {
      expect(parseArc(arcPath(CX, CY, R, START, sweep)).sweepFlag).toBe(1);
    }
  });

  it("draws the score-43 partial arc as a minor arc, not a reversed major one", () => {
    // score 0.43 → sweep 270·0.43 = 116.1°: the exact case that used to invert.
    const { largeArc, sweepFlag } = parseArc(arcPath(CX, CY, R, START, 270 * 0.43));
    expect(largeArc).toBe(0);
    expect(sweepFlag).toBe(1);
  });

  it("ends a full 270° sweep at the lower-right −45° endpoint (mirror of start)", () => {
    const { x2, y2 } = parseArc(arcPath(CX, CY, R, START, 270));
    const endRad = (Math.PI / 180) * (START - 270); // -45°
    expect(x2).toBeCloseTo(CX + R * Math.cos(endRad), 4);
    expect(y2).toBeCloseTo(CY - R * Math.sin(endRad), 4);
    // Symmetric about the vertical centre line: end x mirrors start x.
    const { x1 } = parseArc(arcPath(CX, CY, R, START, 270));
    expect(x2).toBeCloseTo(2 * CX - x1, 4);
  });
});
