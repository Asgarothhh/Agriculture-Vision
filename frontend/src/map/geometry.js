import polygonClipping from "polygon-clipping";

const M_PER_DEG_LAT = 111320;

function lngScale(lat) {
  return M_PER_DEG_LAT * Math.cos((lat * Math.PI) / 180);
}

export function latlngsToRing(latlngs) {
  const ring = latlngs.map((p) => [p.lng, p.lat]);
  if (ring.length && (ring[0][0] !== ring.at(-1)[0] || ring[0][1] !== ring.at(-1)[1])) {
    ring.push(ring[0]);
  }
  return ring;
}

export function ringToLatLngs(ring) {
  return ring.map(([lng, lat]) => L.latLng(lat, lng));
}

export function geoJsonToCoords(geom) {
  if (!geom) return [];
  if (geom.type === "Polygon") return geom.coordinates;
  if (geom.type === "MultiPolygon") return geom.coordinates.flat();
  return [];
}

export function polygonFromLatLngs(latlngs, holes = []) {
  return {
    type: "Polygon",
    coordinates: [latlngsToRing(latlngs), ...holes.map((h) => latlngsToRing(h))],
  };
}

export function circlePolygon(center, radiusM, steps = 48) {
  const coords = [];
  const latScale = M_PER_DEG_LAT;
  const lng = lngScale(center.lat);
  for (let i = 0; i <= steps; i += 1) {
    const a = (2 * Math.PI * i) / steps;
    coords.push([center.lng + (radiusM * Math.sin(a)) / lng, center.lat + (radiusM * Math.cos(a)) / latScale]);
  }
  return { type: "Polygon", coordinates: [coords] };
}

export function bufferPolyline(latlngs, widthM) {
  if (!latlngs || latlngs.length < 2) return null;
  const half = widthM / 2;
  const left = [];
  const right = [];
  for (let i = 0; i < latlngs.length; i += 1) {
    const prev = latlngs[Math.max(0, i - 1)];
    const next = latlngs[Math.min(latlngs.length - 1, i + 1)];
    const dLat = next.lat - prev.lat;
    const dLng = next.lng - prev.lng;
    const len = Math.hypot(dLat * M_PER_DEG_LAT, dLng * lngScale(latlngs[i].lat)) || 1;
    const nx = (-dLng * lngScale(latlngs[i].lat)) / len;
    const ny = (dLat * M_PER_DEG_LAT) / len;
    left.push([
      latlngs[i].lng + (nx * half) / lngScale(latlngs[i].lat),
      latlngs[i].lat + (ny * half) / M_PER_DEG_LAT,
    ]);
    right.push([
      latlngs[i].lng - (nx * half) / lngScale(latlngs[i].lat),
      latlngs[i].lat - (ny * half) / M_PER_DEG_LAT,
    ]);
  }
  const ring = [...left, ...right.reverse()];
  ring.push(ring[0]);
  return { type: "Polygon", coordinates: [ring] };
}

export function isClosedStroke(latlngs, map, px = 18) {
  if (!latlngs || latlngs.length < 3) return false;
  const a = map.latLngToLayerPoint(latlngs[0]);
  const b = map.latLngToLayerPoint(latlngs.at(-1));
  return a.distanceTo(b) <= px;
}

export function strokeLengthPx(latlngs, mapInst) {
  if (!latlngs || latlngs.length < 2) return 0;
  let total = 0;
  for (let i = 1; i < latlngs.length; i += 1) {
    total += mapInst.latLngToLayerPoint(latlngs[i - 1]).distanceTo(mapInst.latLngToLayerPoint(latlngs[i]));
  }
  return total;
}

export function simplifyLatLngs(latlngs, mapInst, minPx = 4) {
  if (!latlngs?.length) return [];
  const out = [latlngs[0]];
  for (let i = 1; i < latlngs.length; i += 1) {
    const prev = mapInst.latLngToLayerPoint(out.at(-1));
    const cur = mapInst.latLngToLayerPoint(latlngs[i]);
    if (prev.distanceTo(cur) >= minPx) out.push(latlngs[i]);
  }
  const last = latlngs.at(-1);
  if (out.at(-1) !== last) out.push(last);
  return out;
}

export function bufferStroke(latlngs, widthM) {
  if (!latlngs?.length) return null;
  const radius = Math.max(widthM / 2, 1);
  let acc = circlePolygon(latlngs[0], radius);
  for (let i = 1; i < latlngs.length; i += 1) {
    const cap = bufferPolyline([latlngs[i - 1], latlngs[i]], widthM);
    const disk = circlePolygon(latlngs[i], radius);
    if (cap) acc = unionGeom(acc, cap) || acc;
    acc = unionGeom(acc, disk) || acc;
  }
  return acc;
}

function ringContains(ring, lng, lat) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    const denom = yj - yi || 1e-12;
    const intersect = yi > lat !== yj > lat && lng < ((xj - xi) * (lat - yi)) / denom + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

export function geomContainsLatLng(geom, latlng) {
  if (!geom || !latlng) return false;
  const lng = latlng.lng;
  const lat = latlng.lat;
  return toMulti(geom).some((polygon) => {
    if (!polygon?.[0] || !ringContains(polygon[0], lng, lat)) return false;
    for (let i = 1; i < polygon.length; i += 1) {
      if (ringContains(polygon[i], lng, lat)) return false;
    }
    return true;
  });
}

function toMulti(geom) {
  if (!geom) return [];
  if (geom.type === "Polygon") return [geom.coordinates];
  if (geom.type === "MultiPolygon") return geom.coordinates;
  return [];
}

function fromMulti(coords) {
  if (!coords?.length) return null;
  if (coords.length === 1) return { type: "Polygon", coordinates: coords[0] };
  return { type: "MultiPolygon", coordinates: coords };
}

export function unionGeom(a, b) {
  try {
    return fromMulti(polygonClipping.union(toMulti(a), toMulti(b)));
  } catch {
    return null;
  }
}

export function diffGeom(a, b) {
  try {
    return fromMulti(polygonClipping.difference(toMulti(a), toMulti(b)));
  } catch {
    return null;
  }
}

/** Like diffGeom, but tells an empty result (null) from a clipping failure (undefined). */
export function differenceGeom(a, b) {
  try {
    return fromMulti(polygonClipping.difference(toMulti(a), toMulti(b)));
  } catch {
    return undefined;
  }
}

export function geodesicAreaM2(geom) {
  const rings = geom?.type === "Polygon" ? [geom.coordinates] : geom?.coordinates || [];
  let area = 0;
  rings.forEach((polygon) => {
    polygon.forEach((ring, idx) => {
      const latlngs = ringToLatLngs(ring);
      const piece = L.GeometryUtil?.geodesicArea
        ? L.GeometryUtil.geodesicArea(latlngs)
        : sphericalArea(latlngs);
      area += idx === 0 ? piece : -piece;
    });
  });
  return Math.abs(area);
}

function sphericalArea(latlngs) {
  if (latlngs.length < 3) return 0;
  let sum = 0;
  for (let i = 0; i < latlngs.length; i += 1) {
    const a = latlngs[i];
    const b = latlngs[(i + 1) % latlngs.length];
    sum += ((b.lng - a.lng) * Math.PI) / 180 * (2 + Math.sin((a.lat * Math.PI) / 180) + Math.sin((b.lat * Math.PI) / 180));
  }
  return Math.abs((sum * 6378137 * 6378137) / 2);
}

export function formatArea(areaM2) {
  if (areaM2 < 100) return `${areaM2 < 10 ? areaM2.toFixed(1) : Math.round(areaM2)} м²`;
  return `${(areaM2 / 10000).toFixed(2)} га`;
}

export function nearestPoints(aRing, bRing) {
  let best = { dist: Infinity, a: aRing[0], b: bRing[0] };
  aRing.forEach((pa) => {
    bRing.forEach((pb) => {
      const d = Math.hypot(pa[0] - pb[0], pa[1] - pb[1]);
      if (d < best.dist) best = { dist: d, a: pa, b: pb };
    });
  });
  return best;
}

export function bridgePolygons(geomA, geomB) {
  const a = toMulti(geomA)[0]?.[0];
  const b = toMulti(geomB)[0]?.[0];
  if (!a || !b) return unionGeom(geomA, geomB);
  const near = nearestPoints(a, b);
  const gapM = Math.max(40, near.dist * 111320 * 4);
  const windowPoly = circlePolygon(L.latLng(near.a[1], near.a[0]), gapM);
  const clippedA = polygonClipping.intersection(toMulti(geomA), toMulti(windowPoly));
  const clippedB = polygonClipping.intersection(toMulti(geomB), toMulti(windowPoly));
  const hullPts = [...(clippedA[0]?.[0] || []), ...(clippedB[0]?.[0] || []), near.a, near.b];
  if (hullPts.length < 3) return unionGeom(geomA, geomB);
  const hull = convexHull(hullPts);
  const bridge = { type: "Polygon", coordinates: [hull] };
  return unionGeom(unionGeom(geomA, geomB), bridge);
}

function convexHull(points) {
  const pts = points.slice().sort((p, q) => p[0] - q[0] || p[1] - q[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower = [];
  pts.forEach((p) => {
    while (lower.length >= 2 && cross(lower.at(-2), lower.at(-1), p) <= 0) lower.pop();
    lower.push(p);
  });
  const upper = [];
  pts.slice().reverse().forEach((p) => {
    while (upper.length >= 2 && cross(upper.at(-2), upper.at(-1), p) <= 0) upper.pop();
    upper.push(p);
  });
  const hull = lower.slice(0, -1).concat(upper.slice(0, -1));
  hull.push(hull[0]);
  return hull;
}

export function layerToPolyBoolRegion(layer) {
  const geo = layer.toGeoJSON?.().geometry || layer.feature?.geometry;
  return geo;
}

/**
 * Evenly spaced points along a freehand path (as in the reference): thins dense mouse
 * points and fills long gaps, so the circles of the stroke buffer always overlap.
 */
export function resamplePath(path, stepM) {
  if (!path?.length) return [];
  const out = [path[0]];
  for (let i = 1; i < path.length; i += 1) {
    const a = path[i - 1];
    const b = path[i];
    const segLen = a.distanceTo(b);
    if (segLen > stepM) {
      const n = Math.ceil(segLen / stepM);
      for (let k = 1; k < n; k += 1) {
        const t = k / n;
        out.push(L.latLng(a.lat + (b.lat - a.lat) * t, a.lng + (b.lng - a.lng) * t));
      }
    }
    if (i === path.length - 1 || out.at(-1).distanceTo(b) >= stepM * 0.5) out.push(b);
  }
  return out;
}

/** Stroke of the brush/eraser: union of circles of `radiusM` along the path (follows the stroke shape). */
export function strokeBufferGeom(path, radiusM) {
  if (!path?.length) return null;
  const step = Math.max(1, radiusM * 0.85);
  const sampled = path.length > 1 ? resamplePath(path, step) : path.slice();
  const circles = sampled.map((p) => toMulti(circlePolygon(p, radiusM, 16)));
  try {
    return fromMulti(polygonClipping.union(...circles));
  } catch {
    return null;
  }
}

/** Freehand outline closed end-to-start; self-crossings are resolved. Null if degenerate. */
export function outlinePolygonGeom(path) {
  if (!path || path.length < 3) return null;
  const ring = latlngsToRing(path);
  if (ring.length < 4) return null;
  try {
    return fromMulti(polygonClipping.union([[ring]]));
  } catch {
    return null;
  }
}

/** Is the freehand loop closed (end near start), in metres — the reference eraser «lasso» rule. */
export function isLoopClosedM(path, radiusM) {
  if (!path || path.length < 3) return false;
  return path[0].distanceTo(path.at(-1)) <= Math.max(radiusM * 1.5, 10);
}

export function polygonParts(geom) {
  return toMulti(geom);
}

/**
 * Result of a boolean edit, as in the reference: the largest part is the object (holes
 * inside it are kept); detached pieces are dropped. Objects that already consisted of
 * several parts (imports, recognition) keep all parts.
 */
export function keepLargestPart(geom, { keepAllParts = false } = {}) {
  const parts = toMulti(geom).filter((p) => p?.[0]?.length >= 4);
  if (!parts.length) return { geom: null, holes: 0, discarded: false, isEmpty: true };
  if (keepAllParts || parts.length === 1) {
    return {
      geom: fromMulti(parts),
      holes: parts.reduce((n, p) => n + p.length - 1, 0),
      discarded: false,
      isEmpty: false,
    };
  }
  let best = parts[0];
  let bestArea = -1;
  parts.forEach((p) => {
    const area = geodesicAreaM2({ type: "Polygon", coordinates: p });
    if (area > bestArea) {
      best = p;
      bestArea = area;
    }
  });
  return { geom: { type: "Polygon", coordinates: best }, holes: best.length - 1, discarded: true, isEmpty: false };
}

/** Outer ring of the largest part as LatLngs (for N/E/S/W vertex markers). */
export function outerRingLatLngs(geom) {
  if (geom?.type === "Point") return [L.latLng(geom.coordinates[1], geom.coordinates[0])];
  const parts = toMulti(geom);
  if (!parts.length) return [];
  let best = parts[0];
  if (parts.length > 1) {
    let bestArea = -1;
    parts.forEach((p) => {
      const area = geodesicAreaM2({ type: "Polygon", coordinates: p });
      if (area > bestArea) {
        best = p;
        bestArea = area;
      }
    });
  }
  return ringToLatLngs(best[0] || []);
}

/** Extreme points north/east/south/west of a ring, without duplicates (reference getMainCornerPoints). */
export function mainCornerPoints(ring) {
  if (!ring?.length) return [];
  let n = ring[0];
  let s = ring[0];
  let e = ring[0];
  let w = ring[0];
  ring.forEach((pt) => {
    if (pt.lat > n.lat) n = pt;
    if (pt.lat < s.lat) s = pt;
    if (pt.lng > e.lng) e = pt;
    if (pt.lng < w.lng) w = pt;
  });
  const uniq = [];
  [n, e, s, w].forEach((p) => {
    if (!uniq.some((u) => Math.abs(u.lat - p.lat) < 1e-10 && Math.abs(u.lng - p.lng) < 1e-10)) uniq.push(p);
  });
  return uniq;
}

/** Distance in metres from a point to a polygon's boundary (0 inside). Used by «Соединить линией». */
export function distanceToGeomM(geom, latlng) {
  if (geomContainsLatLng(geom, latlng)) return 0;
  const kx = lngScale(latlng.lat);
  const ky = M_PER_DEG_LAT;
  let best = Infinity;
  toMulti(geom).forEach((polygon) => {
    polygon.forEach((ring) => {
      for (let i = 1; i < ring.length; i += 1) {
        const ax = (ring[i - 1][0] - latlng.lng) * kx;
        const ay = (ring[i - 1][1] - latlng.lat) * ky;
        const bx = (ring[i][0] - latlng.lng) * kx;
        const by = (ring[i][1] - latlng.lat) * ky;
        const dx = bx - ax;
        const dy = by - ay;
        const len2 = dx * dx + dy * dy || 1e-12;
        const t = Math.max(0, Math.min(1, -(ax * dx + ay * dy) / len2));
        best = Math.min(best, Math.hypot(ax + t * dx, ay + t * dy));
      }
    });
  });
  return best;
}

/** Area label as in the reference «Свойства объекта»: hectares from 0.01 ha, otherwise m². */
export function formatAreaHa(areaM2) {
  const ha = areaM2 / 10000;
  return ha >= 0.01 ? `${ha.toFixed(2)} га` : `${Math.round(areaM2)} м²`;
}
