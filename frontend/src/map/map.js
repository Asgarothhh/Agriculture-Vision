import { dzzEnsureTileBlob, dzzPrefetch } from "../dzz/tiles.js";
import { getActiveBasemapTileUrl, toSameOriginDzzUrl } from "../dzz/urls.js";
import { withTimeout } from "../ui.js";

const DEFAULT_CENTER = [53.9, 27.55];
const DEFAULT_ZOOM = 13;
const TILE_OPTS = { maxZoom: 19, keepBuffer: 4, updateWhenZooming: true };

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
  // #region agent log
  window.__avMap = map;
  // #endregion
  L.control.zoom({ position: "bottomleft" }).addTo(map);
  tileSatellite = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { ...TILE_OPTS, attribution: "Esri", crossOrigin: true },
  );
  tileScheme = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    ...TILE_OPTS,
    attribution: "OSM",
    crossOrigin: true,
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
    tileCustom = L.tileLayer(customUrl, { ...TILE_OPTS, attribution: "custom", crossOrigin: true });
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

async function paintTile(ctx, img, mapPos) {
  const r = img.getBoundingClientRect();
  const dx = r.left - mapPos.left;
  const dy = r.top - mapPos.top;
  if (img.src.startsWith("blob:")) {
    ctx.drawImage(img, dx, dy, r.width, r.height);
    return;
  }
  try {
    const res = await fetch(img.src, { mode: "cors" });
    const blob = await res.blob();
    const bmp = await createImageBitmap(blob);
    ctx.drawImage(bmp, dx, dy, r.width, r.height);
  } catch {
    ctx.drawImage(img, dx, dy, r.width, r.height);
  }
}

export async function captureMapJpeg() {
  return withTimeout(
    (async () => {
      if (!map) throw new Error("Карта ещё не готова");
      const size = map.getSize();
      if (!size.x || !size.y) throw new Error("Пустой кадр карты");
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, size.x);
      canvas.height = Math.max(1, size.y);
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#111";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      const pane = map.getPane("tilePane");
      const mapPos = map.getContainer().getBoundingClientRect();
      const imgs = [...pane.querySelectorAll("img")];
      await Promise.all(imgs.map((img) => paintTile(ctx, img, mapPos).catch(() => {})));
      const blob = await new Promise((resolve, reject) => {
        try {
          canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Не удалось снять кадр карты"))), "image/jpeg", 0.92);
        } catch (err) {
          reject(err);
        }
      });
      return new File([blob], `map_aoi_${Date.now()}.jpg`, { type: "image/jpeg" });
    })(),
    15000,
    "Захват карты превысил 15 секунд",
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
