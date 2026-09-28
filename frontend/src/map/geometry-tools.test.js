import { beforeAll, describe, expect, it } from "vitest";

// Minimal Leaflet stand-in: the helpers only need L.latLng(...).distanceTo(...).
function latLng(lat, lng) {
  return {
    lat,
    lng,
    distanceTo(other) {
      const R = 6371000;
      const toRad = (d) => (d * Math.PI) / 180;
      const dLat = toRad(other.lat - lat);
      const dLng = toRad(other.lng - lng);
      const a = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(lat)) * Math.cos(toRad(other.lat)) * Math.sin(dLng / 2) ** 2;
      return 2 * R * Math.asin(Math.sqrt(a));
    },
  };
}

let geo;
beforeAll(async () => {
  globalThis.L = { latLng };
  geo = await import("./geometry.js");
});

const square = (x, y, size = 0.01) => ({
  type: "Polygon",
  coordinates: [[[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]],
});

describe("freehand helpers (reference behaviour)", () => {
  it("resamples long gaps so buffer circles overlap", () => {
    const pts = geo.resamplePath([latLng(53, 27), latLng(53.001, 27)], 10);
    expect(pts.length).toBeGreaterThan(10);
    expect(pts[0].lat).toBe(53);
    expect(pts.at(-1).lat).toBe(53.001);
  });

  it("builds one stroke polygon along the path", () => {
    const geom = geo.strokeBufferGeom([latLng(53, 27), latLng(53.001, 27), latLng(53.001, 27.001)], 5);
    expect(geom?.type).toBe("Polygon");
    expect(geo.geodesicAreaM2(geom)).toBeGreaterThan(1000);
  });

  it("closes a freehand outline end-to-start", () => {
    const geom = geo.outlinePolygonGeom([latLng(53, 27), latLng(53, 27.01), latLng(53.01, 27.01), latLng(53.01, 27)]);
    expect(geom?.type).toBe("Polygon");
    expect(geo.geodesicAreaM2(geom)).toBeGreaterThan(500000);
  });

  it("detects a closed lasso loop in metres", () => {
    const loop = [latLng(53, 27), latLng(53, 27.001), latLng(53.001, 27.001), latLng(53.00001, 27.00001)];
    expect(geo.isLoopClosedM(loop, 5)).toBe(true);
    expect(geo.isLoopClosedM([latLng(53, 27), latLng(53, 27.001), latLng(53.001, 27.001)], 5)).toBe(false);
  });
});

describe("keepLargestPart", () => {
  it("keeps the largest part and drops detached pieces", () => {
    const multi = { type: "MultiPolygon", coordinates: [square(27, 53, 0.01).coordinates, square(28, 53, 0.001).coordinates] };
    const res = geo.keepLargestPart(multi);
    expect(res.discarded).toBe(true);
    expect(res.geom.type).toBe("Polygon");
    expect(res.geom.coordinates[0][0]).toEqual([27, 53]);
  });

  it("keeps all parts of an object that already had several", () => {
    const multi = { type: "MultiPolygon", coordinates: [square(27, 53).coordinates, square(28, 53).coordinates] };
    const res = geo.keepLargestPart(multi, { keepAllParts: true });
    expect(res.geom.type).toBe("MultiPolygon");
    expect(res.discarded).toBe(false);
  });

  it("reports an empty result", () => {
    expect(geo.keepLargestPart(null).isEmpty).toBe(true);
  });

  it("counts a hole cut inside the contour", () => {
    const cut = geo.differenceGeom(square(27, 53, 0.01), square(27.004, 53.004, 0.002));
    const res = geo.keepLargestPart(cut);
    expect(res.holes).toBe(1);
  });
});

describe("differenceGeom", () => {
  it("returns null when everything is erased", () => {
    expect(geo.differenceGeom(square(27, 53), square(26.9, 52.9, 0.5))).toBeNull();
  });
});

describe("vertex markers and «Соединить линией»", () => {
  it("returns N/E/S/W corner points without duplicates", () => {
    const ring = geo.outerRingLatLngs(square(27, 53));
    const pts = geo.mainCornerPoints(ring);
    expect(pts.length).toBeGreaterThanOrEqual(2);
    expect(pts.length).toBeLessThanOrEqual(4);
  });

  it("measures distance to a polygon edge in metres", () => {
    expect(geo.distanceToGeomM(square(27, 53), { lat: 53.005, lng: 27.005 })).toBe(0);
    const d = geo.distanceToGeomM(square(27, 53), { lat: 53.005, lng: 27.0101 });
    expect(d).toBeGreaterThan(3);
    expect(d).toBeLessThan(15);
  });

  it("formats area like the reference properties panel", () => {
    expect(geo.formatAreaHa(250000)).toBe("25.00 га");
    expect(geo.formatAreaHa(50)).toBe("50 м²");
  });
});
