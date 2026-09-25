import { describe, expect, it } from "vitest";
import { bufferStroke, diffGeom, formatArea, geomContainsLatLng, unionGeom } from "./geometry.js";

const square = (x, y, size = 0.01) => ({
  type: "Polygon",
  coordinates: [
    [
      [x, y],
      [x + size, y],
      [x + size, y + size],
      [x, y + size],
      [x, y],
    ],
  ],
});

describe("polygon boolean ops", () => {
  it("unions overlapping polygons", () => {
    const merged = unionGeom(square(27, 53), square(27.005, 53));
    expect(merged).toBeTruthy();
    expect(["Polygon", "MultiPolygon"]).toContain(merged.type);
  });

  it("difference refuses to return an empty contour", () => {
    const cut = diffGeom(square(27, 53), square(27, 53));
    expect(cut).toBeNull();
  });
});

describe("bufferStroke", () => {
  it("builds a buffered strip from two vertices", () => {
    const geom = bufferStroke(
      [
        { lat: 53, lng: 27 },
        { lat: 53.002, lng: 27 },
      ],
      40,
    );
    expect(geom).toBeTruthy();
    expect(["Polygon", "MultiPolygon"]).toContain(geom.type);
  });
});

describe("geomContainsLatLng", () => {
  it("detects a point inside a square", () => {
    expect(geomContainsLatLng(square(27, 53), { lat: 53.005, lng: 27.005 })).toBe(true);
    expect(geomContainsLatLng(square(27, 53), { lat: 52, lng: 26 })).toBe(false);
  });
});

describe("formatArea", () => {
  it("uses m² below 0.01 ha", () => {
    expect(formatArea(80)).toMatch(/м²/);
  });

  it("uses ha from 0.01 ha", () => {
    expect(formatArea(100)).toBe("0.01 га");
  });
});
