import { describe, expect, it } from "vitest";
import { boundaryUrl, CITIES, CITY_CONFIG } from "./city";

describe("per-city map clamp config", () => {
  it.each(CITIES)("%s has well-formed bounds containing its center", (city) => {
    const cfg = CITY_CONFIG[city];
    const [[west, south], [east, north]] = cfg.maxBounds;
    expect(west).toBeLessThan(east);
    expect(south).toBeLessThan(north);
    expect(cfg.center.lon).toBeGreaterThan(west);
    expect(cfg.center.lon).toBeLessThan(east);
    expect(cfg.center.lat).toBeGreaterThan(south);
    expect(cfg.center.lat).toBeLessThan(north);
    // The default framing must be reachable under the floor.
    expect(cfg.minZoom).toBeLessThanOrEqual(cfg.zoom);
  });

  it("boundary urls are city-scoped committed assets (no data prefix)", () => {
    expect(boundaryUrl("chicago")).toBe("/data/boundaries/chicago.json");
    expect(boundaryUrl("nyc")).toBe("/data/boundaries/nyc.json");
    expect(boundaryUrl("la")).toBe("/data/boundaries/la.json");
  });
});
