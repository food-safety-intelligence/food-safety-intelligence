import { describe, expect, it } from "vitest";
import { simplifyFeatureCollection, thinRing } from "./simplify-geojson.mjs";

describe("thinRing", () => {
  it("drops sub-epsilon jitter but keeps the ring closed", () => {
    const ring = [
      [0, 0],
      [0.00001, 0.00001], // sub-eps jitter — dropped
      [1, 0],
      [1, 1],
      [0, 1],
      [0, 0],
    ];
    const out = thinRing(ring, 0.001);
    expect(out[0]).toEqual([0, 0]);
    expect(out[out.length - 1]).toEqual([0, 0]); // closed
    expect(out).toHaveLength(5); // 4 corners + closing point
  });

  it("rounds to 5 decimal places", () => {
    const out = thinRing(
      [
        [0.123456789, 0],
        [1, 1],
        [0.123456789, 0],
      ],
      0.0001,
    );
    expect(out[0]).toEqual([0.12346, 0]);
  });
});

describe("simplifyFeatureCollection", () => {
  const square = [
    [0, 0],
    [1, 0],
    [1, 1],
    [0, 1],
    [0, 0],
  ];

  it("keeps MultiPolygon islands and stamps provenance", () => {
    const island = [
      [5, 5],
      [6, 5],
      [6, 6],
      [5, 6],
      [5, 5],
    ];
    const out = simplifyFeatureCollection(
      {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            properties: { junk: 1 },
            geometry: { type: "MultiPolygon", coordinates: [[square], [island]] },
          },
        ],
      },
      0.001,
      { source: "http://example.com", fetched: "2026-07-17" },
    );
    expect(out.features).toHaveLength(1);
    expect(out.features[0].geometry.coordinates).toHaveLength(2); // both polys kept
    expect(out.features[0].properties).toEqual({
      source: "http://example.com",
      fetched: "2026-07-17",
    });
  });

  it("drops rings that collapse into slivers", () => {
    const sliver = [
      [0, 0],
      [0.0001, 0],
      [0.0001, 0.0001],
      [0, 0],
    ];
    const out = simplifyFeatureCollection(
      {
        type: "FeatureCollection",
        features: [
          { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [sliver] } },
        ],
      },
      0.01,
      {},
    );
    expect(out.features).toHaveLength(0); // geometry vanished -> feature dropped
  });
});
