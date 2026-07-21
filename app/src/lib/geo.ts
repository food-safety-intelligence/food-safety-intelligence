/**
 * Boundary-mask geometry for the city maps.
 *
 * The gray-out layer is an INVERTED polygon: a world-sized outer ring with the
 * city's exterior rings punched out as holes, so a translucent fill dims
 * everything OUTSIDE the boundary. Pure data-in/data-out so it is unit
 * testable without a map. GeoJSON types come from @types/geojson (already in
 * the tree via maplibre-gl).
 */

import type { Feature, FeatureCollection, Geometry, Polygon, Position } from "geojson";

// ±85 (not ±90) keeps the ring inside web-mercator's renderable range.
const WORLD_RING: Position[] = [
  [-180, -85],
  [180, -85],
  [180, 85],
  [-180, 85],
  [-180, -85],
];

function collectExteriorRings(geom: Geometry, out: Position[][]): void {
  if (geom.type === "Polygon") {
    if (geom.coordinates.length > 0) out.push(geom.coordinates[0]);
  } else if (geom.type === "MultiPolygon") {
    for (const poly of geom.coordinates) if (poly.length > 0) out.push(poly[0]);
  } else if (geom.type === "GeometryCollection") {
    for (const g of geom.geometries) collectExteriorRings(g, out);
  }
  // Points/lines can't bound an area — ignored.
}

/**
 * Build the inverted mask polygon from a boundary GeoJSON (Feature,
 * FeatureCollection, or bare Geometry). Interior rings (holes inside the
 * city itself) are ignored — none of the three cities has an enclave worth
 * re-dimming. Returns null when the input carries no polygonal geometry, so
 * a failed or garbled boundary fetch degrades to "no mask" upstream.
 */
export function maskFromBoundary(boundary: unknown): Feature<Polygon> | null {
  const b = boundary as { type?: unknown } | null;
  if (!b || typeof b !== "object" || typeof b.type !== "string") return null;

  const rings: Position[][] = [];
  if (b.type === "FeatureCollection") {
    const features = (b as FeatureCollection).features;
    if (Array.isArray(features)) {
      for (const f of features) {
        if (f?.geometry) collectExteriorRings(f.geometry, rings);
      }
    }
  } else if (b.type === "Feature") {
    const f = b as Feature;
    if (f.geometry) collectExteriorRings(f.geometry, rings);
  } else {
    collectExteriorRings(b as Geometry, rings);
  }
  if (rings.length === 0) return null;
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "Polygon", coordinates: [WORLD_RING, ...rings] },
  };
}
