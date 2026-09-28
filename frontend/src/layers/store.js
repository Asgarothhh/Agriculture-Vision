// In-memory model of the user's layers, folders and objects, synced with the server.
// Everyday edits update single records from the server answer (no full map reload);
// the layers panel (layers/panel.js) and the map tools (map/tools.js) work on this model.
import * as layersApi from "../api/layers.js";
import { $, escapeHtml, showToast } from "../ui.js";
import {
  addGeoJsonObject,
  clearFeatures,
  enableAoiDraw,
  fitBbox,
  getFeatureGroup,
  getMap,
  leafletToGeoJson,
  removeObjectLayer,
  setObjectLayerVisible,
} from "../map/map.js";
import { formatArea, geodesicAreaM2 } from "../map/geometry.js";
import { logAction } from "../api/activity.js";
import { formatCropHtml } from "./crops.js";

let layers = [];
let folders = [];
let objectIndex = new Map();
let labelsGroup = null;
// «Подписи объектов на карте» / «Координаты вершин» (Ctrl+G toggles both).
const mapDisplay = { labels: true, coords: true };
const recordListeners = new Set();
const viewListeners = new Set();

// Undo recreates deleted layers/objects/folders under new server ids: old id → new id.
const idAlias = new Map();

export function aliasId(oldId, newId) {
  if (oldId && newId && oldId !== newId) idAlias.set(oldId, newId);
}

export function resolveId(id) {
  let cur = id;
  const seen = new Set();
  while (idAlias.has(cur) && !seen.has(cur)) {
    seen.add(cur);
    cur = idAlias.get(cur);
  }
  return cur;
}

export function clearIdAliases() {
  idAlias.clear();
}

export function getLayers() {
  return layers;
}

export function getFolders() {
  return folders;
}

export function getFolder(id) {
  return folders.find((f) => f.id === id) || null;
}

export function getObjectRecord(id) {
  return objectIndex.get(id);
}

export function allObjectRecords() {
  return [...objectIndex.values()];
}

export function recordsOfLayer(layerId) {
  return allObjectRecords().filter((record) => record.layer.id === layerId);
}

// Settings → «Категории распознавания» checkboxes → ObjectClass ids (app/core/seed.py).
// Spec 5.3: a switched-off category is not put on the map even if the model finds it.
export const CLASS_CHECKBOXES = {
  "opt-crops": [2],
  "opt-double-sow": [21],
  "opt-withering": [22],
  "opt-edge-strip": [23],
  "opt-flood": [4],
  "opt-watercourse": [24],
  "opt-weeds": [25],
  "opt-seeder-skip": [26],
  "opt-obstacle": [5, 6],
  "opt-nutrition": [27],
  "opt-hail": [28],
};

export function selectedClassIds(root = document) {
  const ids = [];
  let present = 0;
  Object.entries(CLASS_CHECKBOXES).forEach(([id, classIds]) => {
    const box = root.getElementById?.(id);
    if (!box) return;
    present += 1;
    if (box.checked) ids.push(...classIds);
  });
  // No settings panel in the DOM: fall back to every auto category.
  if (!present) return layers.filter((l) => l.kind === "auto" && l.class_id != null).map((l) => l.class_id);
  return ids;
}

/** Recognition categories created by the server: cannot be renamed, recoloured or deleted. */
export function isStandardLayer(layer) {
  return layer?.kind === "auto";
}

/* ---------------------------------------------------------------- folders & visibility */

/**
 * Folder where the whole layer lives (reference getLayerHomeFolderId): the layer's own
 * folder, or the common folder when every object of the layer sits in the same folder.
 */
export function layerHomeFolderId(layer) {
  if (!layer) return null;
  if (layer.folder_id) return layer.folder_id;
  const records = recordsOfLayer(layer.id);
  if (!records.length) return null;
  let folder = null;
  for (const record of records) {
    const fid = record.obj.folder_id || null;
    if (!fid) return null;
    if (!folder) folder = fid;
    else if (folder !== fid) return null;
  }
  return folder;
}

/** Folder an object is shown in: its layer's folder, else its own. */
export function objectFolderId(record) {
  return record?.layer?.folder_id || record?.obj?.folder_id || null;
}

export function isFolderVisible(folderId) {
  if (!folderId) return true;
  return getFolder(folderId)?.is_visible !== false;
}

/** Shown on the map: its layer is on and the folder it is in is not hidden. */
export function isRecordVisible(record) {
  if (!record || record.layer.is_visible === false) return false;
  return isFolderVisible(objectFolderId(record));
}

function applyVisibility() {
  objectIndex.forEach((record) => setObjectLayerVisible(record.leaflet, isRecordVisible(record)));
}

/** Re-applies visibility and redraws the list, legend and captions after bulk changes. */
export function refreshModel() {
  applyVisibility();
  refreshViews();
  notifyRecords();
}

/* ---------------------------------------------------------------- loading */

let loadSeq = 0;

/**
 * Full load from the server — only at login / session restore / after bulk changes
 * (segmentation results, import). Everyday edits update single records instead.
 * Objects of hidden layers are loaded too (kept off the map), like the reference keeps
 * them in memory: counters, legend and undo need them.
 */
export async function loadMapData() {
  // Overlapping reloads (quick clicks) must not both draw: only the latest one renders.
  const seq = ++loadSeq;
  const nextLayers = await layersApi.listLayers();
  const nextFolders = await layersApi.listFolders();
  const perLayer = [];
  for (const layer of nextLayers) {
    perLayer.push([layer, await layersApi.listLayerObjects(layer.id)]);
    if (seq !== loadSeq) return;
  }
  if (seq !== loadSeq) return;
  layers = nextLayers;
  folders = nextFolders;
  clearFeatures();
  objectIndex = new Map();
  for (const [layer, objects] of perLayer) {
    for (const obj of objects) objectIndex.set(obj.id, buildRecord(layer, obj));
  }
  refreshViews();
  notifyRecords();
}

/** Base style of a layer's objects; point objects get a denser fill (+20 %, as in the reference). */
export function styleFor(layer) {
  const fillOpacity = Number(localStorage.getItem("ttz_fill_opacity") || $("opt-fill-opacity")?.value || 35) / 100;
  return {
    color: layer.color || "#43A047",
    weight: Number(localStorage.getItem("ttz_line_width") || $("opt-line-width")?.value || 2),
    fillOpacity,
    pointFillOpacity: Math.min(0.9, fillOpacity + 0.2),
    pointSize: Number(localStorage.getItem("ttz_point_size") || $("opt-point-size")?.value || 5),
  };
}

export function coordColor() {
  return $("opt-coord-color")?.value || "#ff3366";
}

function buildRecord(layer, obj) {
  const record = { obj: { ...obj, layer_id: layer.id }, layer, leaflet: null };
  record.leaflet = addGeoJsonObject(record.obj, styleFor(layer), { visible: isRecordVisible(record) });
  return record;
}

/** Tools subscribe to re-apply selection styling after records are rebuilt. */
export function onRecordsChanged(listener) {
  recordListeners.add(listener);
  return () => recordListeners.delete(listener);
}

function notifyRecords() {
  recordListeners.forEach((listener) => {
    try {
      listener();
    } catch {
      /* a broken listener must not stop the others */
    }
  });
}

/** The layers panel re-renders on every model change. */
export function onViewsRefresh(listener) {
  viewListeners.add(listener);
  return () => viewListeners.delete(listener);
}

export function refreshViews() {
  viewListeners.forEach((listener) => {
    try {
      listener();
    } catch (err) {
      console.error(err);
    }
  });
  renderLegend();
  renderFieldLabels();
  populateDrawLayerSelect();
}

export function getLayer(layerId) {
  return layers.find((l) => l.id === layerId) || null;
}

/* ---------------------------------------------------------------- objects */

/** Puts a server object into the model (new or changed) without reloading the map. */
export function upsertObject(obj) {
  const layer = getLayer(obj.layer_id);
  if (!layer) return null;
  const previous = objectIndex.get(obj.id);
  if (previous) removeObjectLayer(previous.leaflet);
  const record = buildRecord(layer, obj);
  objectIndex.set(obj.id, record);
  refreshViews();
  notifyRecords();
  return record;
}

export function removeObject(id) {
  const record = objectIndex.get(id);
  if (!record) return;
  removeObjectLayer(record.leaflet);
  objectIndex.delete(id);
  refreshViews();
  notifyRecords();
}

/** Server operations that update the model with the server's answer (no full reload). */
export async function createObjectOnServer(layerId, payload) {
  const created = await layersApi.addObject(layerId, payload);
  upsertObject(created);
  return created;
}

export async function patchObjectOnServer(id, patch) {
  const updated = await layersApi.patchObject(id, patch);
  upsertObject(updated);
  return updated;
}

export async function deleteObjectOnServer(id) {
  await layersApi.deleteObject(id);
  removeObject(id);
}

/** POST /objects/merge: the server keeps the first object (new geometry) and deletes the rest. */
export async function mergeObjectsOnServer(ids, geom) {
  const merged = await layersApi.mergeObjects(ids, geom);
  ids.slice(1).forEach((id) => {
    const record = objectIndex.get(id);
    if (record) removeObjectLayer(record.leaflet);
    objectIndex.delete(id);
  });
  upsertObject(merged);
  return merged;
}

/* ---------------------------------------------------------------- layers */

function restyleLayer(layerId) {
  objectIndex.forEach((record, id) => {
    if (record.layer.id !== layerId) return;
    removeObjectLayer(record.leaflet);
    objectIndex.set(id, buildRecord(record.layer, record.obj));
  });
}

export async function createLayerOnServer({ name, color = "#3388ff", folderId = null }) {
  const created = await layersApi.createLayer({ name, color });
  let layer = { ...created, is_visible: created.is_visible !== false };
  if (folderId) layer = { ...layer, ...(await layersApi.patchLayer(created.id, { folder_id: folderId })) };
  layers = [...layers, layer];
  refreshViews();
  logAction("tool", `Создан новый слой «${name}»`);
  return layer;
}

/** «+ Новый слой…» in the draw layer list. */
export function createLayerQuick(name, color = "#3388ff") {
  return createLayerOnServer({ name, color });
}

/** PATCH /layers/{id} and apply the answer to the model (colour restyles its objects). */
export async function patchLayerOnServer(layerId, patch) {
  const layer = getLayer(layerId);
  if (!layer) return null;
  const updated = await layersApi.patchLayer(layerId, patch);
  const colorChanged = updated.color && updated.color !== layer.color;
  Object.assign(layer, updated);
  if (colorChanged) restyleLayer(layerId);
  applyVisibility();
  refreshViews();
  notifyRecords();
  return layer;
}

export async function deleteLayerOnServer(layerId) {
  await layersApi.deleteLayer(layerId);
  objectIndex.forEach((record, id) => {
    if (record.layer.id !== layerId) return;
    removeObjectLayer(record.leaflet);
    objectIndex.delete(id);
  });
  layers = layers.filter((l) => l.id !== layerId);
  refreshViews();
  notifyRecords();
}

/** Layer checkbox: hide/show at once, then persist; roll back if the server refuses. */
export async function setLayerVisibility(layerId, visible) {
  const layer = getLayer(layerId);
  if (!layer) return;
  const apply = (on) => {
    layer.is_visible = on;
    applyVisibility();
    refreshViews();
    notifyRecords();
  };
  apply(visible);
  try {
    await layersApi.patchLayer(layerId, { is_visible: visible });
    logAction("tool", `Изменена видимость слоя «${layer.name}»`);
  } catch (err) {
    apply(!visible);
    throw err;
  }
}

/* ---------------------------------------------------------------- folders */

export async function createFolderOnServer(name) {
  const created = await layersApi.createFolder(name);
  folders = [...folders, { ...created, is_visible: created.is_visible !== false }];
  refreshViews();
  return created;
}

export async function patchFolderOnServer(folderId, patch) {
  const folder = getFolder(folderId);
  if (!folder) return null;
  const updated = await layersApi.patchFolder(folderId, patch);
  Object.assign(folder, updated);
  applyVisibility();
  refreshViews();
  notifyRecords();
  return folder;
}

/** DELETE /folders/{id}: the server takes its layers and objects out of it (they stay on the map). */
export async function deleteFolderOnServer(folderId) {
  await layersApi.deleteFolder(folderId);
  layers.forEach((l) => {
    if (l.folder_id === folderId) l.folder_id = null;
  });
  objectIndex.forEach((record) => {
    if (record.obj.folder_id === folderId) record.obj.folder_id = null;
  });
  folders = folders.filter((f) => f.id !== folderId);
  applyVisibility();
  refreshViews();
  notifyRecords();
}

/** POST /folders/{id}/items — a whole layer or one object into a folder (folderId null = out of it). */
export async function moveToFolderOnServer({ layerId = null, objectId = null, folderId = null, fromFolderId = null }) {
  const target = folderId || fromFolderId;
  if (!target) return;
  const body = layerId ? { layer_id: layerId } : { object_id: objectId };
  if (!folderId) body.detach = true;
  await layersApi.moveFolderItem(target, body);
  if (layerId) {
    const layer = getLayer(layerId);
    if (layer) layer.folder_id = folderId;
  } else {
    const record = objectIndex.get(objectId);
    if (record) record.obj.folder_id = folderId;
  }
  applyVisibility();
  refreshViews();
  notifyRecords();
}

/* ---------------------------------------------------------------- captions & legend */

export function getMapDisplay() {
  return { ...mapDisplay };
}

/** Captions / vertex coordinates on the map (checkboxes and Ctrl+G). */
export function setMapDisplayOption(key, value) {
  if (!(key in mapDisplay)) return;
  mapDisplay[key] = !!value;
  if ($("opt-field-labels")) $("opt-field-labels").checked = mapDisplay.labels;
  if ($("opt-field-coords")) $("opt-field-coords").checked = mapDisplay.coords;
  renderFieldLabels();
  notifyRecords();
  const label = key === "labels" ? "подписи объектов" : "координаты вершин";
  logAction("map", value ? `Включены ${label} на карте` : `Скрыты ${label} на карте`);
}

function objectCenter(leaflet) {
  let center = null;
  leaflet?.eachLayer?.((part) => {
    if (center) return;
    if (part.getBounds) center = part.getBounds().getCenter();
    else if (part.getLatLng) center = part.getLatLng();
  });
  return center;
}

/** Captions in the middle of each shown object: name + crop, like the reference. */
export function renderFieldLabels() {
  const map = getMap();
  if (!map) return;
  if (!labelsGroup) labelsGroup = L.layerGroup().addTo(map);
  labelsGroup.clearLayers();
  if (!mapDisplay.labels) return;
  objectIndex.forEach((record) => {
    if (!isRecordVisible(record) || !record.obj.name) return;
    const center = objectCenter(record.leaflet);
    if (!center) return;
    let html = `<strong>${escapeHtml(record.obj.name)}</strong>`;
    if (record.obj.crop) html += `<span>${formatCropHtml(record.obj.crop)}</span>`;
    labelsGroup.addLayer(
      L.marker(center, {
        icon: L.divIcon({ className: "field-map-label", html, iconSize: null }),
        interactive: false,
      }),
    );
  });
}

export function layerObjectCount(layer) {
  let n = 0;
  objectIndex.forEach((item) => {
    if (item.layer.id === layer.id) n += 1;
  });
  return n;
}

/**
 * Legend entries as in the reference: a folder holding layers with objects is one entry
 * (folder name, colour of its first such layer); then every loose layer that has objects.
 * Hidden layers/folders stay listed, exactly as in the reference (user decision).
 */
export function legendItems(allLayers, allFolders, countOf) {
  const withObjects = allLayers.filter((l) => countOf(l) > 0);
  const items = [];
  allFolders.forEach((folder) => {
    const children = withObjects.filter((l) => l.folder_id === folder.id);
    if (children.length) items.push({ name: folder.name, color: children[0].color });
  });
  const folderIds = new Set(allFolders.map((folder) => folder.id));
  withObjects
    .filter((l) => !l.folder_id || !folderIds.has(l.folder_id))
    .forEach((l) => items.push({ name: l.name, color: l.color }));
  return items;
}

function renderLegend() {
  const el = $("legend");
  if (!el) return;
  el.innerHTML = legendItems(layers, folders, layerObjectCount)
    .map(
      (item) => `<span class="legend-item" title="${escapeHtml(item.name)}">
        <span class="legend-swatch" style="background:${escapeHtml(item.color)}"></span>
        <span class="legend-text">${escapeHtml(item.name)}</span>
      </span>`,
    )
    .join("");
}

/* ---------------------------------------------------------------- drawing layer */

export function populateDrawLayerSelect() {
  const select = $("draw-layer-select");
  if (!select) return;
  const previous = select.value;
  // Own layers first: a new drawing defaults to a user layer, not a recognition category.
  const ordered = [...layers.filter((l) => !isStandardLayer(l)), ...layers.filter(isStandardLayer)];
  select.innerHTML =
    ordered.map((l) => `<option value="${l.id}">${escapeHtml(l.name)}</option>`).join("") +
    '<option value="__new__">+ Новый слой…</option>';
  if (previous && ordered.some((l) => l.id === previous)) select.value = previous;
  else if (defaultDrawLayer()) select.value = defaultDrawLayer().id;
}

/** Own layer first; without own layers — «Культурные растения» (class 2), like the reference default. */
function defaultDrawLayer() {
  return (
    layers.find((l) => !isStandardLayer(l)) ||
    layers.find((l) => isStandardLayer(l) && l.class_id === 2) ||
    layers[0] ||
    null
  );
}

export function currentDrawLayerId() {
  const value = $("draw-layer-select")?.value;
  if (value && value !== "__new__") return value;
  return defaultDrawLayer()?.id;
}

export async function persistDrawnLayer(leafletLayer, origin = "manual") {
  const layerId = currentDrawLayerId();
  if (!layerId) {
    showToast("Создайте слой для рисования", true);
    return;
  }
  const geom = leafletToGeoJson(leafletLayer);
  try {
    const created = await createObjectOnServer(layerId, { name: "", geom, origin });
    getMap()?.removeLayer(leafletLayer);
    return created;
  } catch (err) {
    showToast(err.message, true);
  }
}

export function startAoiSelection() {
  enableAoiDraw(() => showToast("Область выделена"));
}

export async function importLayerFile(file) {
  if (!file) return;
  try {
    const result = await layersApi.importLayer(file);
    showToast("Импорт выполнен");
    await loadMapData();
    if (result.bbox) fitBbox(result.bbox);
  } catch (err) {
    showToast(err.message, true);
  }
}

/* ---------------------------------------------------------------- display settings (stage 5) */

export function applyDisplaySettings() {
  applyLiveStyles();
}

export function applyLiveStyles() {
  localStorage.setItem("ttz_point_size", $("opt-point-size")?.value || "5");
  localStorage.setItem("ttz_line_width", $("opt-line-width")?.value || "2");
  localStorage.setItem("ttz_fill_opacity", $("opt-fill-opacity")?.value || "35");
  localStorage.setItem("ttz_coord_color", $("opt-coord-color")?.value || "#ff3366");
  layers.forEach((layer) => restyleLayer(layer.id));
  renderFieldLabels();
  notifyRecords();
}

export function restoreDisplaySettings() {
  const line = localStorage.getItem("ttz_line_width");
  const fill = localStorage.getItem("ttz_fill_opacity");
  const point = localStorage.getItem("ttz_point_size");
  const coord = localStorage.getItem("ttz_coord_color");
  if (line && $("opt-line-width")) {
    $("opt-line-width").value = line;
    if ($("line-width-value")) $("line-width-value").innerText = line;
  }
  if (fill && $("opt-fill-opacity")) {
    $("opt-fill-opacity").value = fill;
    if ($("fill-opacity-value")) $("fill-opacity-value").innerText = fill;
  }
  if (point && $("opt-point-size")) {
    $("opt-point-size").value = point;
    if ($("point-size-value")) $("point-size-value").innerText = point;
  }
  if (coord && $("opt-coord-color")) $("opt-coord-color").value = coord;
}

export function resetDisplaySettings() {
  ["ttz_point_size", "ttz_line_width", "ttz_fill_opacity", "ttz_coord_color", "ttz_basemap"].forEach((k) =>
    localStorage.removeItem(k),
  );
}

export { geodesicAreaM2, formatArea, getFeatureGroup };
