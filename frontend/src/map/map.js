import { dzzEnsureTileBlob, dzzPrefetch } from "../dzz/tiles.js";
import { getActiveBasemapTileUrl, toSameOriginDzzUrl } from "../dzz/urls.js";
import { isSecurityError, withTimeout } from "../ui.js";

const DEFAULT_CENTER = [53.9, 27.55];
const DEFAULT_ZOOM = 13;
const TILE_OPTS = { maxZoom: 19, keepBuffer: 4, updateWhenZooming: true };
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
const visitedBounds = [];
let visitedCursor = -1;

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
  map = L.map("map", { zoomControl: false }).setView(DEFAULT_CENTER, DEFAULT_ZOOM);
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

export function setBasemap(kind, customUrl) {
  if (!map) return;
  [tileSatellite, tileScheme, tileDzz, tileCustom].forEach((layer) => {
    if (layer && map.hasLayer(layer)) map.removeLayer(layer);
  });
  if (kind === "scheme") tileScheme.addTo(map);
  else if (kind === "dzz") {
    tileDzz.redraw();
    tileDzz.addTo(map);
  }
  else if (kind === "custom" && customUrl) {
    tileCustom = L.tileLayer(customUrl, { ...TILE_OPTS, attribution: "custom", crossOrigin: "anonymous" });
    bindTileLoadIndicator(tileCustom);
    tileCustom.addTo(map);
  } else tileSatellite.addTo(map);
}

export function setAoiBounds(bounds) {
  clearAoi();
  aoiLayer = L.rectangle(bounds, { color: "#e14059", weight: 2, dashArray: "6 4", fillOpacity: 0.05 });
  aoiLayer.addTo(map);
  rememberBounds(bounds);
}

export function rememberBounds(bounds) {
  if (!bounds) return;
  visitedBounds.unshift(L.latLngBounds(bounds));
  if (visitedBounds.length > 40) visitedBounds.pop();
  visitedCursor = 0;
}

export function cycleVisitedBounds() {
  if (!visitedBounds.length || !map) return 0;
  visitedCursor = (visitedCursor + 1) % visitedBounds.length;
  map.fitBounds(visitedBounds[visitedCursor], { maxZoom: 16 });
  return visitedCursor;
}

export function visitedCount() {
  return visitedBounds.length;
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

export function addGeoJsonObject(obj, style) {
  const geo = obj.geom || obj.geometry;
  if (!geo) return null;
  const layer = L.geoJSON(
    { type: "Feature", geometry: geo, properties: obj },
    {
      style: () => ({
        color: style?.color || "#43A047",
        weight: style?.weight || 2,
        fillOpacity: style?.fillOpacity ?? 0.35,
      }),
      pointToLayer: (_f, latlng) =>
        L.circleMarker(latlng, {
          radius: style?.pointSize || 5,
          color: style?.color || "#546E7A",
          fillOpacity: 0.9,
        }),
    },
  );
  layer.eachLayer((part) => {
    part.avObject = obj;
    part.avLayerId = obj.layer_id;
    L.DomEvent.on(part, "click", (ev) => L.DomEvent.stopPropagation(ev));
    const showLabels = document.getElementById("opt-field-labels")?.checked !== false;
    if (showLabels && obj.name) {
      part.bindTooltip(obj.name, { permanent: true, direction: "center", className: "field-label" });
    }
  });
  featureGroup.addLayer(layer);
  return layer;
}

export function clearFeatures() {
  featureGroup.clearLayers();
}

const TILE_FETCH_TIMEOUT_MS = 8000;

async function fetchTileBitmap(src) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TILE_FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(src, { mode: "cors", credentials: "same-origin", signal: ctrl.signal });
    if (!res.ok) return null;
    const type = (res.headers.get("content-type") || "").toLowerCase();
    // An SPA fallback (index.html) instead of a tile means the proxy location is missing.
    if (type && !type.startsWith("image/")) return null;
    return await createImageBitmap(await res.blob());
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

/**
 * Snapshot of the basemap under the AOI (or the whole view without an AOI).
 * Returns the JPEG and the geographic bounds that exactly match its pixels.
 */
export async function captureMapJpeg() {
  return withTimeout(
    (async () => {
      if (!map) throw new Error("Карта ещё не готова");
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
        file: new File([blob], `map_aoi_${Date.now()}.jpg`, { type: "image/jpeg" }),
        geoBounds: { west: nw.lng, south: se.lat, east: se.lng, north: nw.lat },
      };
    })(),
    20000,
    "Захват карты превысил 20 секунд",
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
