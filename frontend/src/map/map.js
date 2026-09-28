import { dzzEnsureTileBlob, dzzFetchResilient, dzzPrefetch } from "../dzz/tiles.js";
import {
  DZZ_DEFAULT_SERVICE,
  dzzSession,
  getActiveBasemapTileUrl,
  normalizeServiceRoot,
  toSameOriginDzzUrl,
} from "../dzz/urls.js";
import { isSecurityError, withTimeout } from "../ui.js";

const DEFAULT_CENTER = [53.9, 27.55];
const DEFAULT_ZOOM = 13;
const TILE_OPTS = {
  maxZoom: 22,
  maxNativeZoom: 19,
  minZoom: 3,
  keepBuffer: 4,
  updateWhenZooming: true,
  updateWhenIdle: true,
};
const ESRI_PROXY_TEMPLATE = "/basemap/esri/{z}/{y}/{x}";
const ESRI_DIRECT_TEMPLATE =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";

let map;
let tileSatellite;
let tileScheme;
let tileDzz;
let tileCustom;
let drawControl;
let aoiLayer = null;
let featureGroup;
let loadingCount = 0;
let dzzGrid = null;

export function getMap() {
  return map;
}

export function getFeatureGroup() {
  return featureGroup;
}

function bindTileLoadIndicator(layer) {
  layer.on("loading", () => {
    loadingCount += 1;
    const el = document.getElementById("tiles-loading-indicator");
    if (el) el.style.display = loadingCount > 0 ? "" : "none";
  });
  layer.on("load", () => {
    loadingCount = Math.max(0, loadingCount - 1);
    const el = document.getElementById("tiles-loading-indicator");
    if (el) el.style.display = loadingCount > 0 ? "" : "none";
  });
}

function DzzTileLayer() {
  return L.TileLayer.extend({
    createTile(coords, done) {
      const tile = document.createElement("img");
      tile.alt = "";
      const url = toSameOriginDzzUrl(getActiveBasemapTileUrl(coords.z, coords.x, coords.y));
      dzzEnsureTileBlob(url)
        .then((blob) => {
          if (blob.size < 400) throw new Error(`empty tile ${blob.size}`);
          tile.onload = () => {
            if (tile.naturalWidth <= 1 && tile.naturalHeight <= 1) {
              done(new Error("placeholder tile"), tile);
              return;
            }
            done(null, tile);
            dzzPrefetch(coords);
          };
          tile.onerror = (err) => done(err, tile);
          tile.src = URL.createObjectURL(blob);
        })
        .catch((err) => done(err, tile));
      return tile;
    },
  });
}

export function initMap() {
  if (map) {
    map.invalidateSize();
    return map;
  }
  map = L.map("map", { zoomControl: false, minZoom: 3, maxZoom: 22 }).setView(DEFAULT_CENTER, DEFAULT_ZOOM);
  L.control.zoom({ position: "bottomleft" }).addTo(map);
  tileSatellite = L.tileLayer(ESRI_PROXY_TEMPLATE, {
    ...TILE_OPTS,
    attribution: "Esri",
    crossOrigin: "anonymous",
  });
  // The entry nginx (e.g. behind the remote-access IP) may lack /basemap/esri/.
  // Esri serves tiles with CORS, so the direct URL keeps the canvas clean too.
  tileSatellite.on("tileerror", ({ tile, coords }) => {
    if (!tile || tile.dataset.esriDirect) return;
    tile.dataset.esriDirect = "1";
    tile.src = L.Util.template(ESRI_DIRECT_TEMPLATE, coords);
  });
  tileScheme = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    ...TILE_OPTS,
    attribution: "OSM",
    crossOrigin: "anonymous",
  });
  const DzzLayer = DzzTileLayer();
  tileDzz = new DzzLayer("", {
    maxZoom: 22,
    attribution: "dzz.by",
    keepBuffer: 4,
    updateWhenZooming: true,
  });
  [tileSatellite, tileScheme, tileDzz].forEach(bindTileLoadIndicator);
  tileSatellite.addTo(map);
  featureGroup = L.featureGroup().addTo(map);
  drawControl = new L.Control.Draw({
    draw: {
      polygon: { allowIntersection: false, showArea: true },
      polyline: false,
      circle: false,
      circlemarker: false,
      marker: true,
      rectangle: true,
    },
    edit: { featureGroup, remove: true },
  });
  map.on("mousemove", (e) => {
    const el = document.getElementById("coords-display");
    if (el) el.textContent = `${e.latlng.lat.toFixed(5)}, ${e.latlng.lng.toFixed(5)}`;
  });
  map.on("zoomend moveend", updateScale);
  updateScale();
  return map;
}

function updateScale() {
  if (!map) return;
  const z = map.getZoom();
  const center = map.getCenter();
  const latRad = (center.lat * Math.PI) / 180;
  const metersPerPx = (156543.03392 * Math.cos(latRad)) / 2 ** z;
  const el = document.getElementById("scale-display");
  if (el) el.textContent = `1:${Math.round((metersPerPx * 96) / 0.0254)}`;
  const tile = document.getElementById("tile-display");
  if (tile) {
    const n = 2 ** Math.floor(z);
    const x = Math.floor(((center.lng + 180) / 360) * n);
    const y = Math.floor(((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n);
    tile.textContent = `z/x/y ${Math.floor(z)}/${x}/${y}`;
  }
}

let basemapKind = "satellite";

/** Basemap currently on the map: satellite | scheme | dzz | custom. */
export function getBasemapKind() {
  return basemapKind;
}

export function setBasemap(kind, customUrl) {
  if (!map) return;
  [tileSatellite, tileScheme, tileDzz, tileCustom].forEach((layer) => {
    if (layer && map.hasLayer(layer)) map.removeLayer(layer);
  });
  if (kind === "scheme") {
    tileScheme.addTo(map);
    basemapKind = "scheme";
  } else if (kind === "dzz") {
    tileDzz.redraw();
    tileDzz.addTo(map);
    basemapKind = "dzz";
  } else if (kind === "custom" && customUrl) {
    tileCustom = L.tileLayer(customUrl, { ...TILE_OPTS, attribution: "custom", crossOrigin: "anonymous" });
    bindTileLoadIndicator(tileCustom);
    tileCustom.addTo(map);
    basemapKind = "custom";
  } else {
    tileSatellite.addTo(map);
    basemapKind = "satellite";
  }
  // The dzz.by dock and other widgets follow the basemap without importing each other.
  document.dispatchEvent(new CustomEvent("av:basemap", { detail: { kind: basemapKind } }));
}

/** Web-Mercator tile z/x/y under the map centre (or a given point) at the current zoom. */
export function getMapTileCoords(latlng) {
  if (!map) return { z: 0, x: 0, y: 0 };
  const z = Math.max(0, Math.min(22, Math.round(map.getZoom())));
  const p = map.project(latlng || map.getCenter(), z);
  const n = 2 ** z;
  return {
    z,
    x: Math.min(n - 1, Math.max(0, Math.floor(p.x / 256))),
    y: Math.min(n - 1, Math.max(0, Math.floor(p.y / 256))),
  };
}

export function setAoiBounds(bounds) {
  clearAoi();
  aoiLayer = L.rectangle(bounds, { color: "#e14059", weight: 2, dashArray: "6 4", fillOpacity: 0.05 });
  aoiLayer.addTo(map);
}

export function clearAoi() {
  if (aoiLayer) {
    map.removeLayer(aoiLayer);
    aoiLayer = null;
  }
}

export function getAoiGeoJson() {
  if (!aoiLayer) return null;
  const b = aoiLayer.getBounds();
  return {
    type: "Polygon",
    coordinates: [[
      [b.getWest(), b.getSouth()],
      [b.getEast(), b.getSouth()],
      [b.getEast(), b.getNorth()],
      [b.getWest(), b.getNorth()],
      [b.getWest(), b.getSouth()],
    ]],
  };
}

export function getViewBounds() {
  const b = aoiLayer ? aoiLayer.getBounds() : map.getBounds();
  return { west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth() };
}

export function fitBbox(bbox) {
  if (!bbox || bbox.length < 4) return;
  const [west, south, east, north] = bbox;
  map.fitBounds([[south, west], [north, east]], { padding: [30, 30], maxZoom: 15 });
}

export function leafletToGeoJson(layer) {
  return layer.toGeoJSON().geometry;
}

/**
 * Leaflet layer for one server object. Captions are drawn separately (store.renderFieldLabels),
 * as in the reference. Objects of a hidden layer are built but kept off the map.
 */
export function addGeoJsonObject(obj, style, { visible = true } = {}) {
  const geo = obj.geom || obj.geometry;
  if (!geo) return null;
  const layer = L.geoJSON(
    { type: "Feature", geometry: geo, properties: obj },
    {
      style: () => ({
        color: style?.color || "#43A047",
        weight: style?.weight || 2,
        fillColor: style?.color || "#43A047",
        fillOpacity: style?.fillOpacity ?? 0.35,
      }),
      pointToLayer: (_f, latlng) =>
        L.circleMarker(latlng, {
          radius: style?.pointSize || 5,
          color: style?.color || "#546E7A",
          fillColor: style?.color || "#546E7A",
          fillOpacity: style?.pointFillOpacity ?? 0.9,
          weight: style?.weight || 2,
        }),
    },
  );
  // Clicks are not stopped here: in the select tool map/tools.js stops them itself; other
  // tools (ruler, compass, text, «по точкам») must receive clicks made on top of objects.
  layer.eachLayer((part) => {
    part.avObject = obj;
    part.avLayerId = obj.layer_id;
  });
  if (visible) featureGroup.addLayer(layer);
  return layer;
}

/** Shows or hides an object's Leaflet layer (layer visibility toggle) without rebuilding it. */
export function setObjectLayerVisible(layer, visible) {
  if (!layer || !featureGroup) return;
  const has = featureGroup.hasLayer(layer);
  if (visible && !has) featureGroup.addLayer(layer);
  else if (!visible && has) featureGroup.removeLayer(layer);
}

export function removeObjectLayer(layer) {
  if (layer && featureGroup?.hasLayer(layer)) featureGroup.removeLayer(layer);
}

export function clearFeatures() {
  featureGroup.clearLayers();
}

let resultOverlay = null;

/** Show a saved processing result (FeatureCollection, EPSG:4326) on top of the map. */
export function showResultOverlay(geojson) {
  if (!map) return 0;
  if (resultOverlay) map.removeLayer(resultOverlay);
  const features = (geojson?.features || []).filter((f) => f?.geometry);
  resultOverlay = L.geoJSON(
    { type: "FeatureCollection", features },
    {
      style: () => ({ color: "#e14059", weight: 2, dashArray: "4 3", fillOpacity: 0.15 }),
      pointToLayer: (_f, latlng) => L.circleMarker(latlng, { radius: 6, color: "#e14059", fillOpacity: 0.8 }),
    },
  ).addTo(map);
  if (features.length) map.fitBounds(resultOverlay.getBounds(), { padding: [30, 30], maxZoom: 17 });
  return features.length;
}

const TILE_FETCH_TIMEOUT_MS = 8000;

async function fetchTileBitmap(src, minBytes = 0) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TILE_FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(src, { mode: "cors", credentials: "same-origin", signal: ctrl.signal });
    if (!res.ok) return null;
    const type = (res.headers.get("content-type") || "").toLowerCase();
    // An SPA fallback (index.html) instead of a tile means the proxy location is missing.
    if (type && !type.startsWith("image/")) return null;
    const blob = await res.blob();
    // A tiny tile is a «no imagery here» placeholder, not a photo.
    if (minBytes && blob.size < minBytes) return null;
    return await createImageBitmap(blob);
  } finally {
    clearTimeout(timer);
  }
}

function intersects(r, box) {
  return r.right > box.left && r.left < box.right && r.bottom > box.top && r.top < box.bottom;
}

async function paintTile(ctx, img, origin, box) {
  const r = img.getBoundingClientRect();
  if (r.width < 1 || r.height < 1 || !intersects(r, box)) return false;
  const dx = r.left - origin.left;
  const dy = r.top - origin.top;
  const src = img.currentSrc || img.src;
  if (!src) return false;
  if (src.startsWith("blob:") || src.startsWith("data:")) {
    if (!img.complete || !img.naturalWidth) return false;
    ctx.drawImage(img, dx, dy, r.width, r.height);
    return true;
  }
  // Never draw a network <img> itself: if its bytes ever came from another origin
  // without CORS (redirect, proxy, custom basemap, another entry IP/port) the canvas
  // is tainted and toBlob throws SecurityError ("The operation is insecure." in
  // Firefox). A CORS fetch either yields clean pixels or fails, so the canvas stays clean.
  const bmp = await fetchTileBitmap(src);
  if (!bmp) return false;
  try {
    ctx.drawImage(bmp, dx, dy, r.width, r.height);
  } finally {
    if (typeof bmp.close === "function") bmp.close();
  }
  return true;
}

/** Pixel rectangle (container coords) to capture: the AOI clipped to the view, or the whole view. */
function captureRect() {
  const size = map.getSize();
  if (!aoiLayer) return { x: 0, y: 0, w: size.x, h: size.y };
  const b = aoiLayer.getBounds();
  const nw = map.latLngToContainerPoint(b.getNorthWest());
  const se = map.latLngToContainerPoint(b.getSouthEast());
  const x0 = Math.max(0, Math.floor(Math.min(nw.x, se.x)));
  const y0 = Math.max(0, Math.floor(Math.min(nw.y, se.y)));
  const x1 = Math.min(size.x, Math.ceil(Math.max(nw.x, se.x)));
  const y1 = Math.min(size.y, Math.ceil(Math.max(nw.y, se.y)));
  if (x1 - x0 < 8 || y1 - y0 < 8) {
    throw new Error("Выделенная область вне видимой части карты — переместите карту к области");
  }
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

function canvasToJpeg(canvas) {
  return new Promise((resolve, reject) => {
    try {
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Не удалось снять кадр карты"))), "image/jpeg", 0.92);
    } catch (err) {
      reject(
        isSecurityError(err)
          ? new Error("Браузер запретил снимок карты (SecurityError). Обновите страницу с очисткой кэша (Ctrl+F5).")
          : err,
      );
    }
  });
}

/** Old way: copy the tiles currently on screen (screen resolution). Last-resort fallback. */
async function captureScreenJpeg() {
  const size = map.getSize();
  if (!size.x || !size.y) throw new Error("Пустой кадр карты");
  const rect = captureRect();
  const canvas = document.createElement("canvas");
  canvas.width = rect.w;
  canvas.height = rect.h;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#111";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  const mapPos = map.getContainer().getBoundingClientRect();
  const origin = { left: mapPos.left + rect.x, top: mapPos.top + rect.y };
  const box = { left: origin.left, top: origin.top, right: origin.left + rect.w, bottom: origin.top + rect.h };
  const imgs = [...map.getPane("tilePane").querySelectorAll("img")];
  const painted = await Promise.all(imgs.map((img) => paintTile(ctx, img, origin, box).catch(() => false)));
  if (!painted.some(Boolean)) {
    throw new Error("Не удалось получить тайлы подложки для снимка. Дождитесь загрузки карты или смените подложку.");
  }
  const blob = await canvasToJpeg(canvas);
  const nw = map.containerPointToLatLng([rect.x, rect.y]);
  const se = map.containerPointToLatLng([rect.x + rect.w, rect.y + rect.h]);
  return {
    blob,
    geoBounds: { west: nw.lng, south: se.lat, east: se.lng, north: nw.lat },
    info: { mode: "screen", width: rect.w, height: rect.h, zoom: map.getZoom() },
  };
}

// Segmentation snapshot as in the reference: native tiles at the best zoom for the
// area, independent of the window size and of the zoom shown on screen.
export const CAPTURE_TILE = 256;
// 4096 px = the server limit (SegFormer max_side_px); YOLO cuts large snapshots into tiles.
export const CAPTURE_MAX_EDGE = 4096;
export const CAPTURE_MAX_ZOOM = 18;
const CAPTURE_PARALLEL = 8;
// dzz.by orthophoto is ~0.1 m/px — the scale the models are trained on.
const DZZ_TARGET_M_PER_PX = 0.1;
// Esri z19 (~0.18 m/px) only for areas the server can process near that scale anyway.
const SATELLITE_Z19_MAX_EDGE = 3072;
// Esri answers missing z19 imagery with a small grey «no data» tile.
const PLACEHOLDER_TILE_BYTES = 2500;

/**
 * Highest zoom (≤ maxZoom) at which the area fits into `maxEdge` pixels; then raised
 * until the short side has at least one tile of pixels. `edgeAt(z)` → {w, h} in pixels.
 */
export function chooseCaptureZoom(edgeAt, currentZoom, { maxZoom = CAPTURE_MAX_ZOOM, maxEdge = CAPTURE_MAX_EDGE } = {}) {
  let z = Math.min(maxZoom, Math.max(1, Math.round(currentZoom)));
  while (z > 1) {
    const { w, h } = edgeAt(z);
    if (Math.max(w, h) <= maxEdge) break;
    z -= 1;
  }
  while (z < maxZoom) {
    const { w, h } = edgeAt(z + 1);
    if (Math.max(w, h) > maxEdge) break;
    z += 1;
  }
  while (z < maxZoom) {
    const { w, h } = edgeAt(z);
    if (Math.min(w, h) >= CAPTURE_TILE) break;
    z += 1;
  }
  return z;
}

function captureBounds() {
  const b = aoiLayer ? aoiLayer.getBounds() : map.getBounds();
  if (!b?.isValid?.() || b.getSouth() >= b.getNorth() || b.getWest() >= b.getEast()) return map.getBounds();
  return b;
}

/** Candidate URLs of one basemap tile (the first that loads wins). */
function captureTileUrls(z, x, y) {
  if (basemapKind === "scheme") return [`https://${"abc"[(x + y) % 3]}.tile.openstreetmap.org/${z}/${x}/${y}.png`];
  if (basemapKind === "dzz") return [toSameOriginDzzUrl(getActiveBasemapTileUrl(z, x, y))];
  if (basemapKind === "custom" && tileCustom?._url) {
    const subs = tileCustom.options.subdomains || "abc";
    const s = subs[Math.abs(x + y) % subs.length];
    return [L.Util.template(tileCustom._url, { ...tileCustom.options, s, x, y, z, r: "" })];
  }
  return [L.Util.template(ESRI_PROXY_TEMPLATE, { x, y, z }), L.Util.template(ESRI_DIRECT_TEMPLATE, { x, y, z })];
}

async function loadCaptureTile(urls, { minBytes = 0 } = {}) {
  for (const url of urls) {
    try {
      if (basemapKind === "dzz") {
        const blob = await dzzEnsureTileBlob(url);
        if (!blob || blob.size < 400) continue;
        return await createImageBitmap(blob);
      }
      const bmp = await fetchTileBitmap(url, minBytes);
      if (bmp) return bmp;
    } catch {
      /* next candidate */
    }
  }
  return null;
}

async function runPool(jobs, limit) {
  let next = 0;
  const worker = async () => {
    while (next < jobs.length) {
      const job = jobs[next];
      next += 1;
      await job();
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, jobs.length) }, worker));
}

function boundsToGeo(bounds) {
  return { west: bounds.getWest(), south: bounds.getSouth(), east: bounds.getEast(), north: bounds.getNorth() };
}

function captureEdgeAt(bounds) {
  return (z) => {
    const nw = map.project(bounds.getNorthWest(), z);
    const se = map.project(bounds.getSouthEast(), z);
    return { w: Math.abs(se.x - nw.x), h: Math.abs(se.y - nw.y) };
  };
}

/**
 * Satellite: for areas small enough, try native z19 (≈0.18 m/px, closer to the 0.1 m/px
 * the models are trained on); if Esri has no z19 imagery there, fall back to z18.
 */
async function captureSatellite(bounds) {
  const edge = captureEdgeAt(bounds)(19);
  if (basemapKind === "satellite" && Math.max(edge.w, edge.h) <= SATELLITE_Z19_MAX_EDGE) {
    try {
      const shot = await captureTileMosaic(bounds, { maxZoom: 19, minBytes: PLACEHOLDER_TILE_BYTES });
      if (shot.info.zoom === 19 && shot.info.painted >= shot.info.tiles * 0.9) return shot;
    } catch {
      /* no z19 here: z18 below */
    }
  }
  return captureTileMosaic(bounds);
}

async function captureTileMosaic(bounds, { maxZoom = CAPTURE_MAX_ZOOM, minBytes = 0 } = {}) {
  const edgeAt = captureEdgeAt(bounds);
  const zoom = chooseCaptureZoom(edgeAt, map.getZoom(), { maxZoom });
  const nwPix = map.project(bounds.getNorthWest(), zoom);
  const sePix = map.project(bounds.getSouthEast(), zoom);
  const minX = Math.min(nwPix.x, sePix.x);
  const maxX = Math.max(nwPix.x, sePix.x);
  const minY = Math.min(nwPix.y, sePix.y);
  const maxY = Math.max(nwPix.y, sePix.y);
  let outW = Math.max(64, Math.round(maxX - minX));
  let outH = Math.max(64, Math.round(maxY - minY));
  const scale = Math.min(1, CAPTURE_MAX_EDGE / Math.max(outW, outH));
  outW = Math.max(64, Math.round(outW * scale));
  outH = Math.max(64, Math.round(outH * scale));

  const tileMinX = Math.floor(minX / CAPTURE_TILE);
  const tileMaxX = Math.floor((maxX - 1e-6) / CAPTURE_TILE);
  const tileMinY = Math.floor(minY / CAPTURE_TILE);
  const tileMaxY = Math.floor((maxY - 1e-6) / CAPTURE_TILE);
  const n = 2 ** zoom;
  const mosaic = document.createElement("canvas");
  mosaic.width = (tileMaxX - tileMinX + 1) * CAPTURE_TILE;
  mosaic.height = (tileMaxY - tileMinY + 1) * CAPTURE_TILE;
  const mctx = mosaic.getContext("2d");
  mctx.fillStyle = "#1a1a1a";
  mctx.fillRect(0, 0, mosaic.width, mosaic.height);

  let total = 0;
  let painted = 0;
  const jobs = [];
  for (let ty = tileMinY; ty <= tileMaxY; ty += 1) {
    if (ty < 0 || ty >= n) continue;
    for (let tx = tileMinX; tx <= tileMaxX; tx += 1) {
      const x = ((tx % n) + n) % n;
      const dx = (tx - tileMinX) * CAPTURE_TILE;
      const dy = (ty - tileMinY) * CAPTURE_TILE;
      total += 1;
      jobs.push(async () => {
        const bmp = await loadCaptureTile(captureTileUrls(zoom, x, ty), { minBytes });
        if (!bmp) return;
        try {
          mctx.drawImage(bmp, dx, dy, CAPTURE_TILE, CAPTURE_TILE);
          painted += 1;
        } finally {
          bmp.close?.();
        }
      });
    }
  }
  await runPool(jobs, CAPTURE_PARALLEL);
  if (!painted) throw new Error("Не удалось загрузить тайлы подложки для снимка");

  const out = document.createElement("canvas");
  out.width = outW;
  out.height = outH;
  const octx = out.getContext("2d");
  octx.imageSmoothingEnabled = true;
  octx.imageSmoothingQuality = "high";
  octx.drawImage(
    mosaic,
    minX - tileMinX * CAPTURE_TILE,
    minY - tileMinY * CAPTURE_TILE,
    Math.max(1, maxX - minX),
    Math.max(1, maxY - minY),
    0,
    0,
    outW,
    outH,
  );
  const blob = await canvasToJpeg(out);
  return {
    blob,
    geoBounds: boundsToGeo(bounds),
    info: { mode: "tiles", zoom, width: outW, height: outH, tiles: total, painted },
  };
}

/** dzz.by: one exportImage of the whole area (as in the reference) — full orthophoto detail. */
async function captureDzzExport(bounds) {
  if (dzzSession.wmtsTemplate) throw new Error("WMTS source: tiles only");
  const root = normalizeServiceRoot(dzzSession.serviceRoot || dzzSession.url || DZZ_DEFAULT_SERVICE);
  const sw = L.CRS.EPSG3857.project(bounds.getSouthWest());
  const ne = L.CRS.EPSG3857.project(bounds.getNorthEast());
  const xmin = Math.min(sw.x, ne.x);
  const xmax = Math.max(sw.x, ne.x);
  const ymin = Math.min(sw.y, ne.y);
  const ymax = Math.max(sw.y, ne.y);
  const aspect = (xmax - xmin) / Math.max(1, ymax - ymin);
  // Web-Mercator units are stretched by 1/cos(lat): ground metres of the longer side.
  const cosLat = Math.cos((bounds.getCenter().lat * Math.PI) / 180);
  const longMeters = Math.max(xmax - xmin, ymax - ymin) * cosLat;
  const longPx = Math.max(256, Math.min(CAPTURE_MAX_EDGE, Math.round(longMeters / DZZ_TARGET_M_PER_PX)));
  let w = longPx;
  let h = longPx;
  if (aspect >= 1) h = Math.max(64, Math.round(w / aspect));
  else w = Math.max(64, Math.round(h * aspect));
  const url = toSameOriginDzzUrl(
    `${root}/exportImage?bbox=${xmin},${ymin},${xmax},${ymax}&bboxSR=3857&imageSR=3857&size=${w},${h}&format=jpg&f=image`,
  );
  const res = await dzzFetchResilient(url, 30000);
  if (!res.ok) throw new Error(`dzz exportImage ${res.status}`);
  const type = (res.headers.get("content-type") || "").toLowerCase();
  if (type && !type.startsWith("image/")) throw new Error("dzz exportImage: not an image");
  const blob = await res.blob();
  if (!blob || blob.size < 400) throw new Error("dzz exportImage: empty");
  return { blob, geoBounds: boundsToGeo(bounds), info: { mode: "dzz-export", width: w, height: h } };
}

let lastCaptureInfo = null;

/** Size/zoom of the last segmentation snapshot (for the status line and checks). */
export function getLastCaptureInfo() {
  return lastCaptureInfo;
}

/**
 * Snapshot of the basemap under the AOI (or the whole view without an AOI) for segmentation.
 * Returns the JPEG and the geographic bounds that exactly match its pixels.
 */
export async function captureMapJpeg() {
  return withTimeout(
    (async () => {
      if (!map) throw new Error("Карта ещё не готова");
      const bounds = captureBounds();
      let shot = null;
      if (basemapKind === "dzz") {
        try {
          shot = await captureDzzExport(bounds);
        } catch (err) {
          console.warn("dzz exportImage capture → tiles", err);
        }
      }
      if (!shot) {
        try {
          shot = await captureSatellite(bounds);
        } catch (err) {
          if (isSecurityError(err)) throw err;
          console.warn("tile mosaic capture → screen", err);
        }
      }
      if (!shot) shot = await captureScreenJpeg();
      lastCaptureInfo = shot.info;
      return {
        file: new File([shot.blob], `map_aoi_${Date.now()}.jpg`, { type: "image/jpeg" }),
        geoBounds: shot.geoBounds,
        info: shot.info,
      };
    })(),
    60000,
    "Захват карты превысил 60 секунд",
  );
}

export function enableAoiDraw(onDone) {
  if (!map) return;
  const drawer = new L.Draw.Rectangle(map, { shapeOptions: { color: "#e14059" } });
  drawer.enable();
  map.once(L.Draw.Event.CREATED, (e) => {
    setAoiBounds(e.layer.getBounds());
    onDone?.(e.layer.getBounds());
  });
}

export function setDzzCoverageBounds(bounds) {
  if (!tileDzz) return;
  tileDzz.options.bounds = bounds || undefined;
  if (map && map.hasLayer(tileDzz)) tileDzz.redraw();
}

export function setDzzTileGrid(on) {
  if (!map) return;
  if (dzzGrid) {
    map.removeLayer(dzzGrid);
    dzzGrid = null;
  }
  if (!on) return;
  dzzGrid = L.gridLayer({
    tileSize: 256,
    opacity: 1,
  });
  dzzGrid.createTile = () => {
    const el = document.createElement("div");
    el.style.border = "1px solid rgba(225,64,89,0.45)";
    return el;
  };
  dzzGrid.addTo(map);
}

export { drawControl };
