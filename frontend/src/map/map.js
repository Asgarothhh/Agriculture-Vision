import { getAccessToken } from "../api/client.js";
import { dzzTileUrl } from "../api/dzz.js";

const DEFAULT_CENTER = [53.9, 27.55];
const DEFAULT_ZOOM = 8;

let map;
let tileSatellite;
let tileScheme;
let tileDzz;
let drawControl;
let aoiLayer = null;
let featureGroup;

export function getMap() {
  return map;
}

export function getFeatureGroup() {
  return featureGroup;
}

function AuthedTileLayer() {
  return L.TileLayer.extend({
    createTile(coords, done) {
      const tile = document.createElement("img");
      tile.alt = "";
      const url = this.getTileUrl(coords);
      const token = getAccessToken();
      fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
        .then((res) => {
          if (!res.ok) throw new Error(`tile ${res.status}`);
          return res.blob();
        })
        .then((blob) => {
          tile.onload = () => done(null, tile);
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
  tileSatellite = L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, attribution: "Esri" },
  );
  tileScheme = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "OSM",
  });
  const DzzLayer = AuthedTileLayer();
  tileDzz = new DzzLayer(dzzTileUrl("{z}", "{x}", "{y}"), { maxZoom: 22, attribution: "dzz.by" });
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
  const el = document.getElementById("scale-display");
  if (el) el.textContent = `1:${Math.round(591657550.5 / 2 ** z)}`;
  const tile = document.getElementById("tile-display");
  if (tile) {
    const n = 2 ** Math.floor(z);
    const x = Math.floor(((center.lng + 180) / 360) * n);
    const latRad = (center.lat * Math.PI) / 180;
    const y = Math.floor(((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * n);
    tile.textContent = `z/x/y ${Math.floor(z)}/${x}/${y}`;
  }
}

export function setBasemap(kind) {
  if (!map) return;
  [tileSatellite, tileScheme, tileDzz].forEach((layer) => {
    if (map.hasLayer(layer)) map.removeLayer(layer);
  });
  if (kind === "scheme") tileScheme.addTo(map);
  else if (kind === "dzz") tileDzz.addTo(map);
  else tileSatellite.addTo(map);
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
  });
  featureGroup.addLayer(layer);
  return layer;
}

export function clearFeatures() {
  featureGroup.clearLayers();
}

export async function captureMapJpeg() {
  const size = map.getSize();
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, size.x);
  canvas.height = Math.max(1, size.y);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#111";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  const pane = map.getPane("tilePane");
  const mapPos = map.getContainer().getBoundingClientRect();
  pane.querySelectorAll("img").forEach((img) => {
    const r = img.getBoundingClientRect();
    try {
      ctx.drawImage(img, r.left - mapPos.left, r.top - mapPos.top, r.width, r.height);
    } catch {
      /* CORS */
    }
  });
  const blob = await new Promise((resolve, reject) => {
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("toBlob failed"))), "image/jpeg", 0.92);
  });
  return new File([blob], `map_aoi_${Date.now()}.jpg`, { type: "image/jpeg" });
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

export { drawControl };
