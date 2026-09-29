// Tile URL templates of the custom basemap and WMTS matrices (reference
// resolveXyzTileTemplate). The map works in Web Mercator only (user decision 29.09):
// matrices in degrees (EPSG:4326 / GoogleCRS84Quad) are not applied.

/**
 * A template Leaflet can use: WMTS placeholders → {z}/{y}/{x}, ArcGIS «tile/{z}/{x}/{y}»
 * written the OSM way → {z}/{y}/{x}, ArcGIS cache levels (default028mm) → zoom offset.
 * Returns null when there is no zoom placeholder at all.
 */
export function resolveTileTemplate(template) {
  let url = String(template || "").trim();
  if (!url) return null;
  url = url
    .replaceAll("{TileMatrix}", "{z}")
    .replaceAll("{TileRow}", "{y}")
    .replaceAll("{TileCol}", "{x}")
    .replaceAll("{Style}", "default");
  if (!url.includes("{z}")) return null;
  if (/\/(ImageServer|MapServer)\/tile\//i.test(url) && url.includes("{z}/{x}/{y}")) {
    url = url.replace("{z}/{x}/{y}", "{z}/{y}/{x}");
  }
  const isGmc = /GoogleMapsCompatible|WebMercatorQuad/i.test(url);
  // ArcGIS cache levels start 8 web-mercator zooms higher (same as the dzz.by ImageServer).
  const arcgisLevels = /default028mm/i.test(url) || (/dzz\.by/i.test(url) && /\/tile\//i.test(url) && !isGmc);
  return {
    url,
    zoomOffset: arcgisLevels ? -8 : 0,
    minNativeZoom: arcgisLevels ? 8 : 0,
    maxNativeZoom: isGmc ? 19 : arcgisLevels ? 22 : 19,
  };
}

const MERCATOR_RE = /3857|900913|102100|102113|3785|GoogleMapsCompatible|WebMercatorQuad/i;
const DEGREES_RE = /4326|CRS84|GoogleCRS84Quad/i;

/** Is this WMTS matrix in Web Mercator (usable on our map)? */
export function isWebMercatorMatrix(matrix) {
  if (!matrix) return false;
  const text = `${matrix.crs || ""} ${matrix.wellKnown || ""} ${matrix.id || ""}`;
  if (MERCATOR_RE.test(text)) return true;
  if (DEGREES_RE.test(text)) return false;
  // Unknown CRS: let it through (as before), the test tile will tell.
  return matrix.supported !== false;
}

/** Best matrix for our map among the layer's ones: Web Mercator and reachable first. */
export function pickWebMercatorMatrix(matrixIds, byId) {
  const items = (matrixIds || []).map((id) => byId[id] || { id });
  return (
    items.find((m) => isWebMercatorMatrix(m) && m.reachable !== false) ||
    items.find((m) => isWebMercatorMatrix(m)) ||
    null
  );
}

/** Tile x/y/z under a point at a zoom (Web Mercator XYZ). */
export function tileAt(lat, lng, z) {
  const n = 2 ** z;
  const latRad = (lat * Math.PI) / 180;
  const x = Math.floor(((lng + 180) / 360) * n);
  const y = Math.floor(((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n);
  return { z, x: Math.min(n - 1, Math.max(0, x)), y: Math.min(n - 1, Math.max(0, y)) };
}

/**
 * Loads one tile of the template at the given point as an <img> (works without CORS).
 * Resolves true / false; never throws.
 */
export function probeTileTemplate(resolved, lat, lng, zoom, { timeoutMs = 8000, subdomains = "abc" } = {}) {
  return new Promise((resolve) => {
    if (!resolved?.url) {
      resolve(false);
      return;
    }
    const z = Math.max(resolved.minNativeZoom || 0, Math.min(resolved.maxNativeZoom || 19, Math.round(zoom)));
    const t = tileAt(lat, lng, z);
    const url = resolved.url
      .replaceAll("{s}", subdomains[0] || "a")
      .replaceAll("{z}", String(z + (resolved.zoomOffset || 0)))
      .replaceAll("{x}", String(t.x))
      .replaceAll("{y}", String(t.y))
      .replaceAll("{r}", "");
    const img = new Image();
    // Same as the tile layer itself (crossOrigin), so the check matches what the map will show.
    img.crossOrigin = "anonymous";
    const timer = setTimeout(() => {
      img.src = "";
      resolve(false);
    }, timeoutMs);
    img.onload = () => {
      clearTimeout(timer);
      resolve(img.naturalWidth > 1 && img.naturalHeight > 1);
    };
    img.onerror = () => {
      clearTimeout(timer);
      resolve(false);
    };
    img.src = url;
  });
}
