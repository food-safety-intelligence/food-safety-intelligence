import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { CITIES, CITY_CONFIG } from "./city";
import { maskFromBoundary } from "./geo";

// The committed boundary assets the maps fetch at runtime. A broken commit
// here degrades silently in the app (mask-less map), so this test is the
// regression net: every file must parse, produce a mask, and sit inside its
// city's camera clamp (LA's San Clemente Island is the documented exception -
// it lies south of the clamp on purpose; zero establishments there).
const BOUNDARIES_DIR = join(__dirname, "..", "..", "public", "data", "boundaries");

function ringsOf(file: string): [number, number][][] {
  const gj = JSON.parse(readFileSync(join(BOUNDARIES_DIR, file), "utf-8"));
  const mask = maskFromBoundary(gj);
  expect(mask).not.toBeNull();
  // Drop the world ring - the rest are the city's exterior rings.
  return (mask?.geometry.coordinates.slice(1) ?? []) as [number, number][][];
}

describe("committed boundary files", () => {
  it.each(CITIES)("%s parses and produces a mask", (city) => {
    expect(ringsOf(`${city}.json`).length).toBeGreaterThan(0);
  });

  it.each(CITIES)("%s boundary sits inside its maxBounds clamp", (city) => {
    const [[west, south], [east, north]] = CITY_CONFIG[city].maxBounds;
    // South floor: LA's San Clemente Island (lat < 33.1) is intentionally
    // outside the clamp; every other coordinate must be inside the box.
    const allowSouthOutlier = city === "la";
    for (const ring of ringsOf(`${city}.json`)) {
      for (const [lon, lat] of ring) {
        expect(lon).toBeGreaterThanOrEqual(west);
        expect(lon).toBeLessThanOrEqual(east);
        expect(lat).toBeLessThanOrEqual(north);
        if (!allowSouthOutlier) expect(lat).toBeGreaterThanOrEqual(south);
      }
    }
  });

  it("la keeps Catalina Island inside the clamp (un-dimmed and reachable)", () => {
    const south = CITY_CONFIG.la.maxBounds[0][1];
    // Catalina's ring: entirely between lat 33.2-33.6, west of -118.2.
    const catalina = ringsOf("la.json").find((ring) =>
      ring.every(([lon, lat]) => lat > 33.2 && lat < 33.6 && lon < -118.2),
    );
    expect(catalina).toBeDefined();
    for (const [, lat] of catalina ?? []) expect(lat).toBeGreaterThanOrEqual(south);
  });
});
