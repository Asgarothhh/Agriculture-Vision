import { showToast } from "../ui.js";
import { deleteObject } from "../api/layers.js";
import { loadMapData, persistDrawnLayer } from "../layers/store.js";
import { getFeatureGroup, getMap } from "./map.js";

let active = "select";
let scratch = null;
let rulerPts = [];
let compassCenter = null;
let brushPts = [];
let drawing = false;
let handlers = [];

function clearScratch() {
  const map = getMap();
  if (scratch && map) map.removeLayer(scratch);
  scratch = null;
}

function detach() {
  const map = getMap();
  handlers.forEach(([ev, fn, target]) => (target || map)?.off(ev, fn));
  handlers = [];
  rulerPts = [];
  compassCenter = null;
  brushPts = [];
  drawing = false;
  if (map?.dragging) map.dragging.enable();
  clearScratch();
}

function on(ev, fn, target) {
  const src = target || getMap();
  src.on(ev, fn);
  handlers.push([ev, fn, target]);
}

function onRulerClick(e) {
  const map = getMap();
  if (!scratch) scratch = L.layerGroup().addTo(map);
  rulerPts.push(e.latlng);
  L.circleMarker(e.latlng, { radius: 4, color: "#e14059" }).addTo(scratch);
  if (rulerPts.length < 2) return;
  const a = rulerPts[rulerPts.length - 2];
  const b = rulerPts[rulerPts.length - 1];
  L.polyline([a, b], { color: "#e14059", weight: 2 }).addTo(scratch);
  const meters = map.distance(a, b);
  const label = meters >= 1000 ? `${(meters / 1000).toFixed(2)} км` : `${Math.round(meters)} м`;
  L.tooltip({ permanent: true, className: "ruler-label", direction: "center" })
    .setLatLng([(a.lat + b.lat) / 2, (a.lng + b.lng) / 2])
    .setContent(label)
    .addTo(scratch);
}

function onCompassClick(e) {
  const map = getMap();
  if (!scratch) scratch = L.layerGroup().addTo(map);
  if (!compassCenter) {
    compassCenter = e.latlng;
    L.circleMarker(e.latlng, { radius: 5, color: "#1e3a5f" }).addTo(scratch);
    showToast("Кликните край окружности");
    return;
  }
  const radius = map.distance(compassCenter, e.latlng);
  L.circle(compassCenter, { radius, color: "#1e3a5f", weight: 2, fillOpacity: 0.08 }).addTo(scratch);
  compassCenter = null;
}

function onTextClick(e) {
  L.DomEvent.stop(e);
  const text = window.prompt("Текст на карте");
  if (!text) return;
  L.marker(e.latlng, {
    icon: L.divIcon({ className: "map-text-label", html: text, iconSize: [0, 0] }),
  }).addTo(getMap());
}

function onBrushDown(e) {
  if (!e.originalEvent || e.originalEvent.button !== 0) return;
  drawing = true;
  brushPts = [e.latlng];
  getMap().dragging.disable();
  clearScratch();
  scratch = L.polyline(brushPts, { color: "#e14059", weight: 3 }).addTo(getMap());
}

function onBrushMove(e) {
  if (!drawing || !scratch) return;
  brushPts.push(e.latlng);
  scratch.setLatLngs(brushPts);
}

async function onBrushUp() {
  if (!drawing) return;
  drawing = false;
  getMap().dragging.enable();
  if (brushPts.length < 3) {
    clearScratch();
    return;
  }
  const poly = L.polygon([...brushPts, brushPts[0]], { color: "#e14059" });
  clearScratch();
  await persistDrawnLayer(poly);
}

async function onEraserClick(e) {
  L.DomEvent.stop(e);
  const obj = e.layer?.avObject || e.target?.avObject;
  if (!obj?.id) return;
  try {
    await deleteObject(obj.id);
    showToast("Объект удалён");
    await loadMapData();
  } catch (err) {
    showToast(err.message, true);
  }
}

export function activateMapTool(name) {
  detach();
  active = name || "select";
  const map = getMap();
  if (!map) return;
  if (active === "ruler") on("click", onRulerClick);
  else if (active === "compass") on("click", onCompassClick);
  else if (active === "text") on("click", onTextClick);
  else if (active === "brush") {
    on("mousedown", onBrushDown);
    on("mousemove", onBrushMove);
    on("mouseup", onBrushUp);
  } else if (active === "eraser") on("click", onEraserClick, getFeatureGroup());
}

export function currentMapTool() {
  return active;
}
