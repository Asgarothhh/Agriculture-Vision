export const DZZ_DEFAULT_SERVICE =
  "https://www.dzz.by/arcgis/rest/services/georesursDDZ/Polya_all/ImageServer";
export const DZZ_CACHE_MIN_Z = 10;
export const DZZ_CACHE_MAX_Z = 14;
export const DZZ_Z_OFFSET = 8;
export const WEB_MERCATOR_ORIGIN = 20037508.342789244;

export const dzzSession = {
  connected: false,
  serviceRoot: DZZ_DEFAULT_SERVICE,
  url: DZZ_DEFAULT_SERVICE,
  wmtsTemplate: "",
  bounds: null,
};

export function isDzzHost(hostname) {
  return /^(www\.)?(geo)?dzz\.by$/i.test(String(hostname || ""));
}

export function normalizeServiceRoot(url) {
  let raw = String(url || "").trim();
  raw = raw.replace(/\/WMTS(?:\/1\.0\.0)?\/WMTSCapabilities\.xml.*$/i, "");
  raw = raw.replace(/\/tile\/\{[^/]+\}\/\{[^/]+\}\/\{[^/]+\}\/?$/i, "");
  raw = raw.replace(/\/\{z\}\/\{[xy]\}\/\{[xy]\}(?:\.png)?\/?$/i, "");
  raw = raw.replace(/\/+$/, "");
  const match = raw.match(/https?:\/\/[^/]+\/arcgis\/rest\/services\/[^/]+\/[^/]+\/ImageServer/i);
  return match ? match[0].replace(/\/+$/, "") : raw;
}

export function toSameOriginDzzUrl(url) {
  const raw = String(url || "");
  if (!raw) return raw;
  if (raw.startsWith("/api/v1/dzz/")) return raw;
  try {
    const parsed = new URL(raw, "https://www.dzz.by");
    if (!isDzzHost(parsed.hostname)) return raw;
    return `/api/v1/dzz${parsed.pathname}${parsed.search}`;
  } catch {
    return raw;
  }
}

export function dzzExportImageUrl(root, z, x, y, fmt = "jpg") {
  const n = 2 ** Math.max(Number(z) || 0, 0);
  const size = (WEB_MERCATOR_ORIGIN * 2) / n;
  const minx = -WEB_MERCATOR_ORIGIN + x * size;
  const maxy = WEB_MERCATOR_ORIGIN - y * size;
  const miny = maxy - size;
  const maxx = minx + size;
  return `${root}/exportImage?bbox=${minx},${miny},${maxx},${maxy}&bboxSR=3857&imageSR=3857&size=256,256&format=${fmt}&f=image`;
}

export function fillRuntimeTemplate(template, z, x, y) {
  return String(template || "")
    .replaceAll("{TileMatrix}", String(z))
    .replaceAll("{TileRow}", String(y))
    .replaceAll("{TileCol}", String(x))
    .replaceAll("{z}", String(z))
    .replaceAll("{y}", String(y))
    .replaceAll("{x}", String(x));
}

export function getActiveBasemapTileUrl(z, x, y) {
  const template = dzzSession.wmtsTemplate || "";
  if (/\{(TileMatrix|TileCol|TileRow|z|x|y)\}/.test(template)) {
    return fillRuntimeTemplate(template, z, x, y);
  }
  const root = normalizeServiceRoot(dzzSession.serviceRoot || dzzSession.url || DZZ_DEFAULT_SERVICE);
  if (z >= DZZ_CACHE_MIN_Z && z <= DZZ_CACHE_MAX_Z) {
    return `${root}/tile/${z - DZZ_Z_OFFSET}/${y}/${x}`;
  }
  return dzzExportImageUrl(root, z, x, y);
}

export function parseDzzSites(payload) {
  const features = payload?.features;
  if (!Array.isArray(features)) return [];
  return features
    .map((feature, idx) => {
      const attrs = feature?.attributes || {};
      const geom = feature?.geometry || {};
      const rings = geom.rings || geom.paths || [];
      const xs = [];
      const ys = [];
      rings.forEach((ring) => {
        (ring || []).forEach((point) => {
          if (point && point.length >= 2) {
            xs.push(Number(point[0]));
            ys.push(Number(point[1]));
          }
        });
      });
      if (!xs.length) {
        if (geom.x == null || geom.y == null) return null;
        const lat = Number(geom.y);
        const lon = Number(geom.x);
        const name = String(attrs.Name || attrs.name || `Участок ${idx + 1}`);
        return { id: attrs.OBJECTID || idx, name, title: name, center: [lat, lon], bounds: [lon, lat, lon, lat] };
      }
      const west = Math.min(...xs);
      const east = Math.max(...xs);
      const south = Math.min(...ys);
      const north = Math.max(...ys);
      const name = String(attrs.Name || attrs.name || attrs.TITLE || `Участок ${idx + 1}`);
      return {
        id: attrs.OBJECTID || attrs.FID || idx,
        name,
        title: name,
        center: [(south + north) / 2, (west + east) / 2],
        bounds: [west, south, east, north],
      };
    })
    .filter(Boolean);
}

export function unionSiteBounds(sites) {
  if (!sites?.length) return null;
  let west = 180;
  let south = 90;
  let east = -180;
  let north = -90;
  sites.forEach((site) => {
    const [w, s, e, n] = site.bounds || [];
    if (![w, s, e, n].every(Number.isFinite)) return;
    west = Math.min(west, w);
    south = Math.min(south, s);
    east = Math.max(east, e);
    north = Math.max(north, n);
  });
  if (west > east || south > north) return null;
  return [west, south, east, north];
}
