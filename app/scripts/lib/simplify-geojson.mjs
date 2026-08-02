/**
 * Plain-JS GeoJSON shrinker for the committed city-boundary files: round
 * coordinates to 5 decimals (~1 m) and thin ring vertices by radial distance.
 * No npm deps — this runs once from scripts/fetch-boundaries.mjs, never at
 * build or request time, so clarity beats cleverness.
 */

const PRECISION = 1e5; // 5 decimal places

function round(v) {
  return Math.round(v * PRECISION) / PRECISION;
}

/**
 * Keep a vertex only when it moved >= eps degrees (Chebyshev distance) from
 * the last kept vertex; the first point is always kept and re-appended so the
 * ring stays closed.
 */
export function thinRing(ring, eps) {
  if (!Array.isArray(ring) || ring.length === 0) return [];
  const out = [[round(ring[0][0]), round(ring[0][1])]];
  for (let i = 1; i < ring.length - 1; i += 1) {
    const [x, y] = ring[i];
    const [px, py] = out[out.length - 1];
    if (Math.max(Math.abs(x - px), Math.abs(y - py)) >= eps) {
      out.push([round(x), round(y)]);
    }
  }
  out.push([...out[0]]);
  return out;
}

// A ring needs 4 distinct points + closure to bound area; below this it is a
// degenerate sliver left over from thinning — drop it. (Catalina survives
// easily: it is tens of km across.)
const MIN_RING_POINTS = 5;

function simplifyRings(rings, eps) {
  return rings.map((r) => thinRing(r, eps)).filter((r) => r.length >= MIN_RING_POINTS);
}

function simplifyGeometry(geom, eps) {
  if (!geom) return null;
  if (geom.type === "Polygon") {
    const coordinates = simplifyRings(geom.coordinates, eps);
    return coordinates.length ? { type: "Polygon", coordinates } : null;
  }
  if (geom.type === "MultiPolygon") {
    const coordinates = geom.coordinates
      .map((rings) => simplifyRings(rings, eps))
      .filter((rings) => rings.length > 0);
    return coordinates.length ? { type: "MultiPolygon", coordinates } : null;
  }
  return null; // boundary sources are polygonal; anything else is dropped
}

/**
 * Simplify every feature, replace its properties with the provenance stamp
 * (source portal URL + fetch date), and drop features whose geometry
 * vanished. Accepts a bare Feature/geometry input by wrapping it.
 */
export function simplifyFeatureCollection(gj, eps, stamp) {
  const rawFeatures = gj.type === "FeatureCollection" ? (gj.features ?? []) : [gj];
  const features = rawFeatures
    .map((f) => (f.type === "Feature" ? f : { type: "Feature", properties: {}, geometry: f }))
    .map((f) => ({
      type: "Feature",
      properties: { ...stamp },
      geometry: simplifyGeometry(f.geometry, eps),
    }))
    .filter((f) => f.geometry !== null);
  return { type: "FeatureCollection", features };
}
