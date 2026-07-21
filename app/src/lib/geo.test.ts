import { describe, expect, it } from "vitest";
import { maskFromBoundary } from "./geo";

const ring = [
  [-88, 41.6],
  [-87.5, 41.6],
  [-87.5, 42.1],
  [-88, 42.1],
  [-88, 41.6],
];

describe("maskFromBoundary", () => {
  it("wraps a Polygon feature: world outer ring + boundary as hole", () => {
    const mask = maskFromBoundary({
      type: "Feature",
      properties: {},
      geometry: { type: "Polygon", coordinates: [ring] },
    });
    expect(mask).not.toBeNull();
    expect(mask?.geometry.coordinates).toHaveLength(2);
    expect(mask?.geometry.coordinates[0][0]).toEqual([-180, -85]);
    expect(mask?.geometry.coordinates[1]).toEqual(ring);
  });

  it("collects every exterior ring of a MultiPolygon FeatureCollection (LA islands)", () => {
    const island = [
      [-118.6, 33.3],
      [-118.3, 33.3],
      [-118.3, 33.5],
      [-118.6, 33.5],
      [-118.6, 33.3],
    ];
    const interiorHole = [
      [-87.9, 41.7],
      [-87.8, 41.7],
      [-87.8, 41.8],
      [-87.9, 41.8],
      [-87.9, 41.7],
    ];
    const mask = maskFromBoundary({
      type: "FeatureCollection",
      features: [
        {
          type: "Feature",
          properties: {},
          geometry: {
            type: "MultiPolygon",
            coordinates: [[ring, interiorHole], [island]],
          },
        },
      ],
    });
    // world ring + 2 exterior rings; the polygon's own interior ring is ignored
    expect(mask?.geometry.coordinates).toHaveLength(3);
    expect(mask?.geometry.coordinates[1]).toEqual(ring);
    expect(mask?.geometry.coordinates[2]).toEqual(island);
  });

  it("returns null for non-polygonal or garbage input", () => {
    expect(maskFromBoundary(null)).toBeNull();
    expect(maskFromBoundary("nope")).toBeNull();
    expect(maskFromBoundary({})).toBeNull();
    expect(
      maskFromBoundary({
        type: "Feature",
        properties: {},
        geometry: { type: "Point", coordinates: [0, 0] },
      }),
    ).toBeNull();
  });
});
