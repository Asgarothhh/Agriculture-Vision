import { describe, expect, it } from "vitest";
import { isWebMercatorMatrix, pickWebMercatorMatrix, resolveTileTemplate, tileAt } from "./tileTemplate.js";

describe("resolveTileTemplate (custom basemap, reference resolveXyzTileTemplate)", () => {
  it("keeps a plain XYZ template", () => {
    const r = resolveTileTemplate("https://tile.openstreetmap.org/{z}/{x}/{y}.png");
    expect(r).toEqual({ url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png", zoomOffset: 0, minNativeZoom: 0, maxNativeZoom: 19 });
  });

  it("turns WMTS placeholders into {z}/{y}/{x}", () => {
    const r = resolveTileTemplate(
      "https://srv/wmts/1.0.0/roads/{Style}/GoogleMapsCompatible/{TileMatrix}/{TileRow}/{TileCol}.png",
    );
    expect(r.url).toBe("https://srv/wmts/1.0.0/roads/default/GoogleMapsCompatible/{z}/{y}/{x}.png");
    expect(r.maxNativeZoom).toBe(19);
  });

  it("puts ArcGIS tiles in {z}/{y}/{x} order and handles cache levels", () => {
    expect(resolveTileTemplate("https://srv/arcgis/rest/services/a/MapServer/tile/{z}/{x}/{y}").url).toBe(
      "https://srv/arcgis/rest/services/a/MapServer/tile/{z}/{y}/{x}",
    );
    const cache = resolveTileTemplate("https://srv/WMTS/tile/1.0.0/L/default/default028mm/{TileMatrix}/{TileRow}/{TileCol}");
    expect(cache).toMatchObject({ zoomOffset: -8, minNativeZoom: 8, maxNativeZoom: 22 });
  });

  it("rejects a URL without a zoom placeholder", () => {
    expect(resolveTileTemplate("https://srv/WMTSCapabilities.xml")).toBeNull();
    expect(resolveTileTemplate("")).toBeNull();
  });
});

describe("WMTS matrices on a Web Mercator map", () => {
  it("accepts Web Mercator and refuses degrees", () => {
    expect(isWebMercatorMatrix({ id: "GoogleMapsCompatible", wellKnown: "GoogleMapsCompatible" })).toBe(true);
    expect(isWebMercatorMatrix({ id: "default028mm", crs: "urn:ogc:def:crs:EPSG::3857" })).toBe(true);
    expect(isWebMercatorMatrix({ id: "GoogleCRS84Quad", wellKnown: "GoogleCRS84Quad" })).toBe(false);
    expect(isWebMercatorMatrix({ id: "m", crs: "urn:ogc:def:crs:EPSG::4326" })).toBe(false);
  });

  it("prefers a reachable Web Mercator matrix", () => {
    const byId = {
      GoogleCRS84Quad: { id: "GoogleCRS84Quad", wellKnown: "GoogleCRS84Quad" },
      GoogleMapsCompatible: { id: "GoogleMapsCompatible", wellKnown: "GoogleMapsCompatible", reachable: false },
      default028mm: { id: "default028mm", crs: "EPSG:3857" },
    };
    expect(pickWebMercatorMatrix(Object.keys(byId), byId).id).toBe("default028mm");
    expect(pickWebMercatorMatrix(["GoogleCRS84Quad"], byId)).toBeNull();
  });
});

describe("tileAt", () => {
  it("finds the XYZ tile of a point", () => {
    expect(tileAt(53.9, 27.55, 12)).toEqual({ z: 12, x: 2361, y: 1317 });
  });
});
