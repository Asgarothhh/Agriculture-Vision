// Map tools, ported from the reference UI (Web-markup-updated/app.js) onto the backend:
// selection, ruler, compass, text, create/edit area (brush, eraser, «по точкам»),
// merge, «Соединить линией», Delete, selection history (J) and undo for all of them.
// Object changes go through the API and the in-memory model (layers/store.js);
// ruler/compass/text marks are local map overlays, as in the reference.
import { $, closeAppModal, confirmModal, escapeHtml, openAppModal, showToast } from "../ui.js";
import { logAction } from "../api/activity.js";
import {
  allObjectRecords,
  clearIdAliases,
  coordColor,
  createLayerQuick,
  currentDrawLayerId,
  getLayer,
  getMapDisplay,
  getObjectRecord,
  isRecordVisible,
  onRecordsChanged,
  populateDrawLayerSelect,
  setMapDisplayOption,
  styleFor,
} from "../layers/store.js";
import { createTracked, deleteTracked, mergeTracked, moveTracked, patchTracked } from "../layers/ops.js";
import { expandLayer, populateCropSelect } from "../layers/panel.js";
import { getFeatureGroup, getMap } from "./map.js";
import {
  bridgePolygons,
  circlePolygon,
  differenceGeom,
  distanceToGeomM,
  formatAreaHa,
  geodesicAreaM2,
  isLoopClosedM,
  keepLargestPart,
  mainCornerPoints,
  outerRingLatLngs,
  outlinePolygonGeom,
  polygonFromLatLngs,
  polygonParts,
  strokeBufferGeom,
  unionGeom,
} from "./geometry.js";
import { pushUndo, setUndoHook } from "./undo.js";

const TOOL_NAMES = {
  select: "Выделение области",
  ruler: "Линейка",
  compass: "Циркуль",
  text: "Текст",
  freehand: "Редактирование области",
  polygon: "Полигон по точкам",
};

let active = "select";
let bound = false;
let selected = []; // object ids, all from one layer
let mergeActive = false;
let createSession = false;
let editDrawMode = null; // create | brush | eraser | connect | polygon

let overlaysGroup = null;
let textGroup = null;
let overlays = [];
let hoveredOverlay = null;
let selectedOverlay = null;

let rulerStart = null;
let rulerPreview = null;
let compassCenter = null;
let compassDraft = null;
let compassPreview = null;
let lastCompassCircle = null;

let freehandActive = false;
let freehandPath = [];
let freehandPreview = null;
let freehandTargetId = null;
let brushCursor = null;
let brushCursorMeta = { radius: null, isEraser: null };

let vertexPts = [];
let vertexScratch = null;

const outlines = new Map();
let vertexMarkers = [];
const selectionHistory = [];
let historyCursor = -1;

// Server edits run one after another, so each stroke starts from the saved result of the previous one.
let opChain = Promise.resolve();

function map() {
  return getMap();
}

function display() {
  return styleFor({});
}

function queue(task) {
  const next = opChain.then(task).catch((err) => showToast(err?.message || String(err), true));
  opChain = next;
  return next;
}

function isPointRecord(record) {
  return !!record && (record.obj.is_point || /Point$/.test(record.obj.geom?.type || ""));
}

function partsOf(record) {
  const out = [];
  record?.leaflet?.eachLayer?.((part) => out.push(part));
  return out;
}

export function getSelected() {
  return selected.slice();
}

export function currentMapTool() {
  return active;
}

/* ---------------------------------------------------------------- selection */

function clearOutline(id) {
  (outlines.get(id) || []).forEach((layer) => map()?.removeLayer(layer));
  outlines.delete(id);
}

function applySelectedStyle(record) {
  if (!record) return;
  const base = styleFor(record.layer);
  const m = map();
  clearOutline(record.obj.id);
  const lines = [];
  partsOf(record).forEach((part) => {
    const isPoint = !part.getLatLngs;
    const fill = Math.min(0.85, (isPoint ? base.pointFillOpacity : base.fillOpacity) + 0.2);
    part.setStyle?.({ color: "#ffffff", fillColor: base.color, fillOpacity: fill, weight: base.weight });
    // A thicker line on the clickable shape itself would widen its hit area over the
    // neighbour; the white outline is a separate non-interactive layer, as in the reference.
    if (m && part.getLatLngs && m.hasLayer(part)) {
      const Ctor = part instanceof L.Polygon ? L.polygon : L.polyline;
      lines.push(
        Ctor(part.getLatLngs(), {
          color: "#ffffff",
          weight: base.weight + 3,
          fill: false,
          interactive: false,
          className: "selection-outline",
        }).addTo(m),
      );
    }
    part.bringToFront?.();
  });
  lines.forEach((line) => line.bringToFront());
  outlines.set(record.obj.id, lines);
}

function resetStyle(record) {
  if (!record) return;
  const base = styleFor(record.layer);
  partsOf(record).forEach((part) => {
    const isPoint = !part.getLatLngs;
    part.setStyle?.({
      color: base.color,
      fillColor: base.color,
      fillOpacity: isPoint ? base.pointFillOpacity : base.fillOpacity,
      weight: base.weight,
    });
  });
  clearOutline(record.obj.id);
}

function clearVertexMarkers() {
  vertexMarkers.forEach((marker) => map()?.removeLayer(marker));
  vertexMarkers = [];
}

function showVertexMarkers(record) {
  clearVertexMarkers();
  const m = map();
  if (!m || !record || !getMapDisplay().coords || !isRecordVisible(record)) return;
  const ring = outerRingLatLngs(record.obj.geom);
  if (!ring.length) return;
  let keyPoints = isPointRecord(record) ? [ring[0]] : mainCornerPoints(ring);
  if (keyPoints.length < 2 && ring.length >= 2) keyPoints = [ring[0], ring[Math.floor(ring.length / 2)]];
  const color = coordColor();
  const radius = Math.max(4, display().pointSize || 5);
  vertexMarkers = keyPoints.map((pt) =>
    L.circleMarker(pt, { radius, color, fillColor: color, fillOpacity: 1, weight: 2, interactive: false })
      .addTo(m)
      .bindTooltip(`${pt.lat.toFixed(6)}, ${pt.lng.toFixed(6)}`, {
        permanent: true,
        direction: "top",
        offset: [0, -8],
        opacity: 0.95,
        className: "coord-tooltip",
      }),
  );
}

function showFieldDetail(record) {
  const panel = $("field-detail-panel");
  if (!panel || !record) return;
  panel.style.display = "block";
  const input = $("field-name-input");
  if (input) {
    if (input.dataset.objectId !== String(record.obj.id) || document.activeElement !== input) {
      input.value = record.obj.name || "";
    }
    input.dataset.objectId = record.obj.id;
  }
  const area = $("field-area-value");
  if (area) area.textContent = isPointRecord(record) ? "точечный объект" : formatAreaHa(geodesicAreaM2(record.obj.geom));
  if (document.activeElement !== $("field-crop-select")) populateCropSelect(record.obj.crop || "");
}

function hideFieldDetail() {
  const panel = $("field-detail-panel");
  if (panel) panel.style.display = "none";
  const input = $("field-name-input");
  if (input) delete input.dataset.objectId;
}

function recordSelectionHistory(record) {
  let bounds;
  try {
    bounds = record?.leaflet?.getBounds?.();
  } catch {
    return;
  }
  if (!bounds?.isValid?.()) return;
  const last = selectionHistory.at(-1);
  if (last && last.equals(bounds)) return;
  selectionHistory.push(bounds);
  if (selectionHistory.length > 50) selectionHistory.shift();
  historyCursor = -1;
}

/** J: back to recently selected areas, newest first, then round again. */
export function jumpToSelectionHistory() {
  const m = map();
  if (!m || !selectionHistory.length) {
    showToast("Пока нет истории выделенных областей", true);
    return;
  }
  historyCursor = historyCursor <= 0 ? selectionHistory.length - 1 : historyCursor - 1;
  m.fitBounds(selectionHistory[historyCursor], { maxZoom: 17, padding: [60, 60] });
  const fromEnd = selectionHistory.length - historyCursor;
  showToast(`Область ${fromEnd} из ${selectionHistory.length} (от недавней к первой)`);
}

function clearSelection() {
  selected.forEach((id) => resetStyle(getObjectRecord(id)));
  outlines.forEach((_lines, id) => clearOutline(id));
  selected = [];
  clearVertexMarkers();
  updateMergeModePanel();
}

function afterSelectionChange() {
  selected.forEach((id) => applySelectedStyle(getObjectRecord(id)));
  if (selected.length === 1) {
    const record = getObjectRecord(selected[0]);
    showVertexMarkers(record);
    recordSelectionHistory(record);
  } else clearVertexMarkers();
  updateMergeModePanel();
}

function selectFeature(id, multi = false) {
  const record = getObjectRecord(id);
  if (!record) return;
  if (!multi) {
    clearSelection();
    selected = [id];
  } else {
    const idx = selected.indexOf(id);
    if (idx >= 0) {
      resetStyle(record);
      selected.splice(idx, 1);
      if (selected.length === 1) {
        const one = getObjectRecord(selected[0]);
        showVertexMarkers(one);
        showFieldDetail(one);
        recordSelectionHistory(one);
      } else {
        clearVertexMarkers();
        hideFieldDetail();
      }
      updateMergeModePanel();
      return;
    }
    const layerId = record.layer.id;
    const sameLayer = !selected.length || selected.every((sid) => getObjectRecord(sid)?.layer.id === layerId);
    if (!sameLayer) {
      showToast("Мультивыбор только в пределах одного слоя", true);
      clearSelection();
      selected = [id];
    } else selected.push(id);
  }
  selectedOverlay = null;
  afterSelectionChange();
}

/** Selects one object from outside the map (layers list etc.). */
export function selectObjectById(id, { zoom = false } = {}) {
  const record = getObjectRecord(id);
  if (!record) return;
  selectFeature(id, false);
  showFieldDetail(record);
  if (!zoom) return;
  const bounds = record.leaflet?.getBounds?.();
  if (!bounds?.isValid?.()) return;
  // "auto": move the map only when the object is not on screen.
  if (zoom === "auto" && map()?.getBounds().intersects(bounds)) return;
  map()?.fitBounds(bounds, { maxZoom: 16, padding: [40, 40] });
}

/** Kept for older callers: plain selection by ids. */
export function setSelection(ids, { additive = false } = {}) {
  if (!additive) clearSelection();
  ids.forEach((id) => {
    if (getObjectRecord(id) && !selected.includes(id)) selected.push(id);
  });
  afterSelectionChange();
  if (selected.length === 1) showFieldDetail(getObjectRecord(selected[0]));
  else if (!selected.length) hideFieldDetail();
}

/** Records were rebuilt (server answer, visibility…): restyle what is still selected. */
function onRecordsRebuilt() {
  outlines.forEach((_lines, id) => clearOutline(id));
  selected = selected.filter((id) => isRecordVisible(getObjectRecord(id)));
  selected.forEach((id) => applySelectedStyle(getObjectRecord(id)));
  if (selected.length === 1) {
    const record = getObjectRecord(selected[0]);
    showVertexMarkers(record);
    if ($("field-detail-panel")?.style.display === "block") showFieldDetail(record);
  } else {
    clearVertexMarkers();
    if (!selected.length) hideFieldDetail();
  }
  updateMergeModePanel();
}

function stopLeaflet(e) {
  L.DomEvent.stopPropagation(e);
  if (e.originalEvent) {
    L.DomEvent.preventDefault(e.originalEvent);
    L.DomEvent.stopPropagation(e.originalEvent);
  }
}

function onObjectClick(e) {
  if (active !== "select") return;
  const part = e.propagatedFrom || e.layer;
  const obj = part?.avObject;
  if (!obj) return;
  // Stop here so the map click (which clears the selection) does not follow.
  stopLeaflet(e);
  const id = obj.id;
  if (mergeActive) {
    toggleMergeSelection(id);
    return;
  }
  const oe = e.originalEvent || {};
  const multi = !!(oe.ctrlKey || oe.metaKey || oe.shiftKey);
  // A click on the only selected object switches to editing it (as in the reference).
  if (!multi && selected.length === 1 && selected[0] === id) {
    openEditAreaMode();
    return;
  }
  selectedOverlay = null;
  selectFeature(id, multi);
  if (selected.length === 1) showFieldDetail(getObjectRecord(selected[0]));
  else if (selected.length > 1) {
    hideFieldDetail();
    showToast(`Выбрано: ${selected.length} · Ctrl+M — объединить`);
  }
}

function onObjectDblClick(e) {
  // The second click means «edit», not «zoom in».
  if (active === "select") stopLeaflet(e);
}

function onMapClick(e) {
  if (active === "freehand") return;
  if (active === "select") {
    const oe = e.originalEvent;
    if (oe && (oe.ctrlKey || oe.metaKey || oe.shiftKey)) return;
    clearSelection();
    hideFieldDetail();
    selectedOverlay = null;
    return;
  }
  if (active === "ruler") handleRulerClick(e);
  else if (active === "compass") handleCompassClick(e);
  else if (active === "text") handleTextClick(e);
  else if (active === "polygon") handlePolygonClick(e);
}

/* ---------------------------------------------------------------- overlays */

function ensureGroups() {
  const m = map();
  if (!m) return false;
  if (!overlaysGroup) overlaysGroup = L.layerGroup().addTo(m);
  if (!textGroup) textGroup = L.layerGroup().addTo(m);
  return true;
}

function bindOverlayEvents(layer) {
  layer.on("click", (e) => {
    if (active !== "select") return;
    L.DomEvent.stopPropagation(e);
    selectedOverlay = layer;
    clearSelection();
    hideFieldDetail();
    showToast("Метка выбрана — Delete или Ctrl+Z");
  });
  // Delete removes exactly the mark under the cursor, whatever tool is active.
  layer.on("mouseover", () => {
    hoveredOverlay = layer;
  });
  layer.on("mouseout", () => {
    if (hoveredOverlay === layer) hoveredOverlay = null;
  });
}

function overlayParent(layer) {
  return textGroup?.hasLayer(layer) ? textGroup : overlaysGroup;
}

function removeOverlay(layer) {
  overlayParent(layer)?.removeLayer(layer);
  overlays = overlays.filter((item) => item.layer !== layer);
  if (hoveredOverlay === layer) hoveredOverlay = null;
  if (selectedOverlay === layer) selectedOverlay = null;
}

function restoreOverlay(layer, parent) {
  parent?.addLayer(layer);
  overlays.push({ layer, parent });
}

function removeOverlayWithUndo(layer) {
  const parent = overlayParent(layer);
  removeOverlay(layer);
  pushUndo({ undo: async () => restoreOverlay(layer, parent), redo: async () => removeOverlay(layer) });
}

/** Adds a finished ruler/compass/text mark (one undo step). */
function registerOverlay(layers, parent = overlaysGroup) {
  const list = layers.filter(Boolean);
  // featureGroup forwards click/hover of every part (line, points, label) to the whole mark.
  const stored = list.length > 1 ? L.featureGroup(list) : list[0];
  bindOverlayEvents(stored);
  restoreOverlay(stored, parent);
  pushUndo({ undo: async () => removeOverlay(stored), redo: async () => restoreOverlay(stored, parent) });
  return stored;
}

/* ---------------------------------------------------------------- ruler */

function formatDist(meters) {
  return meters >= 1000 ? `${(meters / 1000).toFixed(2)} км` : `${Math.round(meters)} м`;
}

function rulerTickStep() {
  const zoom = map()?.getZoom() || 13;
  if (zoom >= 17) return 10;
  if (zoom >= 15) return 20;
  if (zoom >= 13) return 50;
  return 100;
}

function pointMark(latlng, fillOpacity = 1) {
  const color = coordColor();
  return L.circleMarker(latlng, { radius: display().pointSize, color, fillColor: color, fillOpacity, weight: 2 });
}

function labelMark(latlng, html) {
  return L.marker(latlng, { icon: L.divIcon({ className: "ruler-label", html, iconSize: null }) });
}

function clearRulerPreview() {
  map()?.off("mousemove", onRulerMove);
  if (rulerPreview) overlaysGroup?.removeLayer(rulerPreview);
  rulerPreview = null;
  rulerStart = null;
}

function onRulerMove(e) {
  if (!rulerPreview || !rulerStart) return;
  const color = coordColor();
  const cursor = e.latlng;
  rulerPreview.clearLayers();
  rulerPreview.addLayer(pointMark(rulerStart));
  rulerPreview.addLayer(L.polyline([rulerStart, cursor], { color, weight: display().weight, dashArray: "6 4" }));
  const mid = L.latLng((rulerStart.lat + cursor.lat) / 2, (rulerStart.lng + cursor.lng) / 2);
  rulerPreview.addLayer(labelMark(mid, formatDist(rulerStart.distanceTo(cursor))));
  rulerPreview.addLayer(pointMark(cursor, 0.85));
}

function handleRulerClick(e) {
  if (!ensureGroups()) return;
  if (!rulerStart) {
    rulerStart = e.latlng;
    rulerPreview = L.layerGroup([pointMark(e.latlng)]).addTo(overlaysGroup);
    map().on("mousemove", onRulerMove);
    return;
  }
  const a = rulerStart;
  const b = e.latlng;
  clearRulerPreview();
  const color = coordColor();
  const distance = a.distanceTo(b);
  const parts = [
    pointMark(a),
    pointMark(b),
    L.polyline([a, b], { color, weight: display().weight, dashArray: "6 4" }),
    labelMark(L.latLng((a.lat + b.lat) / 2, (a.lng + b.lng) / 2), formatDist(distance)),
  ];
  const step = rulerTickStep();
  const count = Math.floor(distance / step);
  for (let i = 1; i <= count; i += 1) {
    const t = (i * step) / distance;
    parts.push(pointMark(L.latLng(a.lat + (b.lat - a.lat) * t, a.lng + (b.lng - a.lng) * t)));
  }
  registerOverlay(parts);
}

/* ---------------------------------------------------------------- compass */

function clearCompassPreview() {
  if (compassPreview) overlaysGroup?.removeLayer(compassPreview);
  compassPreview = null;
}

function clearCompassDrawing() {
  map()?.off("mousemove", onCompassMove);
  clearCompassPreview();
  if (compassDraft) overlaysGroup?.removeLayer(compassDraft);
  compassDraft = null;
  compassCenter = null;
}

function onCompassMove(e) {
  if (!compassCenter) return;
  const radius = compassCenter.distanceTo(e.latlng);
  clearCompassPreview();
  compassPreview = L.layerGroup([
    L.circle(compassCenter, {
      radius,
      color: coordColor(),
      weight: display().weight,
      fillOpacity: 0.08,
      dashArray: "4 4",
      interactive: false,
    }),
    labelMark(e.latlng, `R = ${formatDist(radius)}`),
  ]).addTo(overlaysGroup);
}

function handleCompassClick(e) {
  if (!ensureGroups()) return;
  if (!compassCenter) {
    compassCenter = e.latlng;
    compassDraft = L.layerGroup([pointMark(compassCenter)]).addTo(overlaysGroup);
    map().on("mousemove", onCompassMove);
    showToast("Укажите точку на окружности (радиус)");
    return;
  }
  const center = compassCenter;
  const radius = center.distanceTo(e.latlng);
  const centerParts = compassDraft ? compassDraft.getLayers() : [];
  clearCompassDrawing();
  registerOverlay([
    ...centerParts,
    L.circle(center, { radius, color: coordColor(), weight: display().weight, fillOpacity: 0.08 }),
    pointMark(e.latlng),
    labelMark(e.latlng, `R = ${formatDist(radius)}`),
  ]);
  lastCompassCircle = { center, radius };
  openCompassActionPopup(e.latlng);
  showToast(`Радиус: ${formatDist(radius)}`);
}

function openCompassActionPopup(latlng) {
  const box = document.createElement("div");
  box.className = "compass-action-popup";
  box.innerHTML = `<div class="compass-action-title">Круг циркуля</div>
    <button type="button" class="mini-btn" data-act="area">+ Область по кругу</button>
    <button type="button" class="mini-btn mini-btn-red" data-act="cut">Вырезать по кругу</button>`;
  box.querySelector('[data-act="area"]').addEventListener("click", createAreaFromCompassCircle);
  box.querySelector('[data-act="cut"]').addEventListener("click", eraseWithCompassCircle);
  L.popup({ className: "compass-popup", maxWidth: 240 }).setLatLng(latlng).setContent(box).openOn(map());
}

function createAreaFromCompassCircle() {
  if (!lastCompassCircle) return;
  map()?.closePopup();
  const layerId = currentDrawLayerId();
  if (!layerId) {
    showToast("Сначала выберите слой в панели рисования", true);
    return;
  }
  const geom = circlePolygon(lastCompassCircle.center, lastCompassCircle.radius, 48);
  queue(async () => {
    await createTracked(layerId, geom);
    expandLayer(layerId);
    showToast("Область создана по кругу циркуля");
  });
}

function eraseWithCompassCircle() {
  if (!lastCompassCircle) return;
  // Checked at click time: the user often draws the circle first and selects the object after.
  if (selected.length !== 1) {
    showToast("Выделите один объект, чтобы вырезать из него круг", true);
    return;
  }
  map()?.closePopup();
  const id = selected[0];
  const cutter = circlePolygon(lastCompassCircle.center, lastCompassCircle.radius, 48);
  queue(async () => {
    const record = getObjectRecord(id);
    if (!record || isPointRecord(record)) {
      showToast("Вырезать можно только из области", true);
      return;
    }
    const before = record.obj.geom;
    const cut = differenceGeom(before, cutter);
    if (cut === undefined) {
      showToast("Не удалось вырезать круг", true);
      return;
    }
    const result = keepLargestPart(cut, { keepAllParts: polygonParts(before).length > 1 });
    if (result.isEmpty) {
      showToast("Круг стирает контур целиком — удалите объект вручную, если это нужно", true);
      return;
    }
    await patchTracked(id, before, result.geom);
    showToast(result.holes > holesOf(before) ? "Вырезано отверстие по кругу" : "Контур обрезан по кругу");
  });
}

function holesOf(geom) {
  return polygonParts(geom).reduce((n, p) => n + Math.max(0, p.length - 1), 0);
}

/* ---------------------------------------------------------------- text */

function handleTextClick(e) {
  const latlng = e.latlng;
  const add = () => {
    const text = $("modal-map-text")?.value.trim();
    if (!text) return;
    closeAppModal();
    if (!ensureGroups()) return;
    const marker = L.marker(latlng, {
      icon: L.divIcon({ className: "map-text-label", html: escapeHtml(text), iconSize: null }),
    });
    registerOverlay([marker], textGroup);
    showToast("Пометка добавлена");
  };
  openAppModal({
    title: "Текстовая пометка",
    bodyHtml: `<label class="modal-label" for="modal-map-text">Текст на карте</label>
      <input type="text" id="modal-map-text" class="search-input modal-input" placeholder="Введите текст…" maxlength="200">`,
    actions: [
      { label: "Добавить", className: "mini-btn mini-btn-red", onClick: add },
      { label: "Отмена", className: "mini-btn", onClick: closeAppModal },
    ],
  });
  const input = $("modal-map-text");
  input?.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      add();
    }
  });
  setTimeout(() => input?.focus(), 30);
}

/* ---------------------------------------------------------------- Delete */

/** Delete / Backspace: mark under the cursor → selected objects (confirmed) → selected mark → last mark. */
export async function deleteCurrentMapSelection() {
  if (hoveredOverlay) {
    removeOverlayWithUndo(hoveredOverlay);
    showToast("Метка под курсором удалена");
    return;
  }
  if (selected.length) {
    await deleteSelectedFeatures();
    return;
  }
  if (selectedOverlay) {
    removeOverlayWithUndo(selectedOverlay);
    showToast("Объект удалён");
    return;
  }
  const last = overlays.at(-1);
  if (last) {
    removeOverlayWithUndo(last.layer);
    showToast("Последняя метка удалена");
    return;
  }
  showToast("Нечего удалить", true);
}

export async function deleteSelectedFeatures() {
  const records = selected.map((id) => getObjectRecord(id)).filter(Boolean);
  if (!records.length) return;
  const names = records.map((r) => r.obj.name).filter(Boolean);
  const ok = await confirmModal({
    title: records.length === 1 ? "Удалить объект?" : "Удалить объекты?",
    bodyHtml:
      records.length === 1
        ? `<p>Удалить «${escapeHtml(names[0] || "объект")}»? Действие можно отменить (Ctrl+Z).</p>`
        : `<p>Будет удалено объектов: ${records.length}. Действие можно отменить (Ctrl+Z).</p>`,
    confirmLabel: "Удалить",
    danger: true,
  });
  if (!ok) return;
  await queue(async () => {
    clearSelection();
    hideFieldDetail();
    await deleteTracked(records);
    showToast("Выделенные объекты удалены");
  });
}

/* ---------------------------------------------------------------- merge */

function announceSelection() {
  document.dispatchEvent(new CustomEvent("av:selection", { detail: { ids: selected.slice() } }));
}

function updateMergeModePanel() {
  announceSelection();
  const panel = $("merge-mode-panel");
  if (!panel) return;
  panel.style.display = mergeActive ? "block" : "none";
  $("merge-menu-item")?.classList.toggle("active", mergeActive);
  const hint = $("merge-mode-hint");
  if (hint) hint.textContent = `Выбрано: ${mergeActive ? selected.length : 0} из 2`;
  const btn = $("merge-confirm-btn");
  if (btn) btn.disabled = selected.length < 2;
}

function toggleMergeSelection(id) {
  const record = getObjectRecord(id);
  if (!record) return;
  const idx = selected.indexOf(id);
  if (idx >= 0) {
    resetStyle(record);
    selected.splice(idx, 1);
  } else {
    if (selected.length >= 2) {
      showToast("За раз можно объединить только 2 области — сначала снимите одну", true);
      return;
    }
    if (selected.length && getObjectRecord(selected[0])?.layer.id !== record.layer.id) {
      showToast("Объединять можно только области одного слоя", true);
      return;
    }
    selected.push(id);
    applySelectedStyle(record);
  }
  clearVertexMarkers();
  updateMergeModePanel();
}

export function startMergePolygonsMode() {
  if (active === "freehand" || active === "polygon") cancelActiveTool({ silent: true });
  clearSelection();
  hideFieldDetail();
  mergeActive = true;
  setTool("select");
  updateMergeModePanel();
  showToast("Кликните по 2 областям одного слоя, затем «Объединить»");
}

export function cancelMergeMode() {
  if (!mergeActive) return;
  mergeActive = false;
  clearSelection();
  updateMergeModePanel();
}

function exitMergeModeKeepSelection() {
  if (!mergeActive) return;
  mergeActive = false;
  updateMergeModePanel();
}

export function confirmMergePolygons() {
  if (selected.length !== 2) return;
  mergeSelectedPolygons();
}

/** Ctrl+M, as in the reference. */
export function mergeHotkey() {
  if (selected.length === 2) {
    const [a, b] = selected.map((id) => getObjectRecord(id));
    if (!a || !b || a.layer.id !== b.layer.id) showToast("Объединять можно только области одного слоя", true);
    else mergeSelectedPolygons();
  } else if (selected.length > 2) {
    showToast("За раз можно объединить только 2 области", true);
  } else {
    showToast("Выделите ровно 2 объекта одного слоя (Ctrl/⌘/Shift + клик), затем Ctrl+M", true);
  }
}

function mergeSelectedPolygons() {
  const ids = selected.slice(0, 2);
  queue(async () => {
    const [a, b] = ids.map((id) => getObjectRecord(id));
    if (!a || !b) return;
    if (isPointRecord(a) || isPointRecord(b)) {
      showToast("Точечные объекты нельзя объединять", true);
      return;
    }
    let geom = unionGeom(a.obj.geom, b.obj.geom);
    if (!geom) {
      showToast("Не удалось объединить полигоны", true);
      return;
    }
    let bridged = false;
    // The areas did not touch: fill the space between them so the fields become one.
    if (polygonParts(geom).length > polygonParts(a.obj.geom).length + polygonParts(b.obj.geom).length - 1) {
      const withBridge = bridgePolygons(a.obj.geom, b.obj.geom);
      if (withBridge && polygonParts(withBridge).length < polygonParts(geom).length) {
        geom = withBridge;
        bridged = true;
      }
    }
    const keepAll = polygonParts(a.obj.geom).length > 1 || polygonParts(b.obj.geom).length > 1;
    const result = keepLargestPart(geom, { keepAllParts: keepAll });
    if (result.isEmpty) {
      showToast("Не удалось объединить полигоны", true);
      return;
    }
    clearSelection();
    hideFieldDetail();
    const merged = await mergeTracked(a, b, result.geom);
    showToast(bridged ? "Объединено — пространство между областями заполнено" : "Выделенные полигоны объединены");
    if (mergeActive) {
      // The result becomes the first of the next pair — merge on without leaving the mode.
      selected = [merged.id];
      applySelectedStyle(getObjectRecord(merged.id));
      updateMergeModePanel();
      showToast("Выберите следующую область, чтобы объединить с ней");
    } else {
      selectFeature(merged.id, false);
      showFieldDetail(getObjectRecord(merged.id));
    }
  });
}

/* ---------------------------------------------------------------- create / edit area (freehand) */

function brushMeters() {
  return parseInt($("brush-size")?.value || "20", 10);
}

function syncMenuItems() {
  const drawing = active === "freehand" || active === "polygon";
  $("create-area-item")?.classList.toggle("active", drawing && createSession && editDrawMode === "create");
  $("polygon-area-item")?.classList.toggle("active", drawing && editDrawMode === "polygon");
  $("edit-area-item")?.classList.toggle(
    "active",
    drawing && !createSession && (editDrawMode === "brush" || editDrawMode === "eraser"),
  );
  $("manual-connect-menu-item")?.classList.toggle("active", drawing && editDrawMode === "connect");
}

function showEditControls({ title, toggleRow = true }) {
  const box = $("edit-area-controls");
  if (box) box.style.display = "block";
  const row = $("edit-mode-toggle-row");
  if (row) row.style.display = toggleRow ? "" : "none";
  if ($("paint-hud-title")) $("paint-hud-title").textContent = title;
  $("more-menu")?.classList.add("active");
}

function setEraserEnabled(enabled) {
  const btn = $("edit-eraser-btn");
  if (!btn) return;
  btn.disabled = !enabled;
  btn.title = enabled ? "" : "Ластик редактирует уже существующий объект — сначала завершите создание";
}

function syncModeButtons(mode) {
  $("edit-brush-btn")?.classList.toggle("active", mode === "brush" || mode === "create");
  $("edit-eraser-btn")?.classList.toggle("active", mode === "eraser");
  $("edit-polygon-btn")?.classList.toggle("active", mode === "polygon");
  const hint = $("paint-hud-hint");
  if (hint) {
    hint.textContent =
      mode === "eraser"
        ? "Проведите ластиком по краю выделенного объекта. Замкнутый обвод вырезает всю область внутри."
        : mode === "polygon"
          ? "Кликайте вершины. Зелёная точка, Enter или двойной клик — замкнуть. Esc — отмена."
          : mode === "connect"
            ? "Проведите линию от одной области к другой (того же слоя) — они соединятся по линии."
            : createSession
              ? "Обведите область кистью — контур замкнётся сам. Каждый штрих — отдельный объект."
              : "Проведите кистью от края выделенного объекта, чтобы расширить его.";
  }
}

function preferredDrawLayer() {
  populateDrawLayerSelect();
  const sel = $("draw-layer-select");
  const layerId = currentDrawLayerId();
  if (sel && layerId) sel.value = layerId;
  return layerId;
}

export function startCreateArea() {
  exitMergeModeKeepSelection();
  if (active === "freehand" || active === "polygon") deactivateCurrentTool();
  clearSelection();
  hideFieldDetail();
  createSession = true;
  preferredDrawLayer();
  showEditControls({ title: "Создание области" });
  setEraserEnabled(false);
  setEditDrawMode("brush");
  showToast("Создание: обведите область кистью. Каждый штрих — объект. «Готово» — выход.");
}

/** «Полигон по точкам» — backend version only, kept. */
export function startPolygonMode() {
  exitMergeModeKeepSelection();
  if (active === "freehand" || active === "polygon") deactivateCurrentTool();
  clearSelection();
  hideFieldDetail();
  createSession = true;
  preferredDrawLayer();
  showEditControls({ title: "Полигон по точкам" });
  setEraserEnabled(false);
  setEditDrawMode("polygon");
  showToast("Кликайте вершины. На концах отрезков — точки. Зелёная замыкает.");
}

export function openEditAreaMode() {
  if (selected.length !== 1) {
    showToast("Выделите одну область для редактирования (или создайте новую через «Создать область»).", true);
    return;
  }
  exitMergeModeKeepSelection();
  createSession = false;
  const record = getObjectRecord(selected[0]);
  populateDrawLayerSelect();
  const sel = $("draw-layer-select");
  if (sel && record) sel.value = record.layer.id;
  const name = record?.obj.name;
  showEditControls({ title: name ? `Редактирование: «${name}»` : "Редактирование" });
  setEraserEnabled(true);
  setEditDrawMode("brush");
  showToast("Редактирование: кисть расширяет, ластик подрезает край. «Готово» — выход.");
}

/** «Соединить линией»: a line from one area to another (same layer) joins them along the line. */
export function startManualConnectMode() {
  if (active === "freehand" || active === "polygon") deactivateCurrentTool();
  exitMergeModeKeepSelection();
  clearSelection();
  hideFieldDetail();
  createSession = false;
  preferredDrawLayer();
  showEditControls({ title: "Соединение линией", toggleRow: false });
  editDrawMode = "connect";
  syncModeButtons("connect");
  startFreehandEdit("connect");
  showToast("Проведите линию от одной области к другой (или от края уже готовой) — они соединятся. «Готово» — выход.");
}

export function setEditDrawMode(mode) {
  let next = mode;
  // While creating there is nothing to erase yet: the brush stays «create».
  if (createSession && mode !== "polygon") next = "create";
  if (mode === "eraser" && createSession) next = "create";
  syncModeButtons(next);
  if (next === "polygon") startPolygonDrawing();
  else startFreehandEdit(next);
}

export function finishEditAreaMode() {
  if (active === "polygon" && vertexPts.length >= 3) finishPolygonDraw({ stay: true });
  createSession = false;
  stopFreehandEdit();
  clearPolygonDraft();
  const box = $("edit-area-controls");
  if (box) box.style.display = "none";
  setEraserEnabled(true);
  setTool("select");
}

function startFreehandEdit(mode) {
  const m = map();
  if (!m) {
    showToast("Карта ещё не готова", true);
    return;
  }
  if (!ensureGroups()) return;
  stopFreehandEdit();
  clearPolygonDraft();
  active = "freehand";
  editDrawMode = mode;
  const mapArea = $("map-area");
  mapArea?.classList.remove("tool-select", "tool-ruler", "tool-compass", "tool-text", "tool-polygon");
  mapArea?.classList.add("tool-freehand");
  mapArea?.classList.toggle("tool-eraser", mode === "eraser");
  mapArea?.classList.toggle("tool-brush", mode !== "eraser");
  document.querySelectorAll(".tool-btn[data-tool]").forEach((btn) => btn.classList.remove("active"));
  m.dragging.disable();
  m.on("mousedown", onFreehandDown);
  document.addEventListener("mousemove", onFreehandDocMove);
  document.addEventListener("mouseup", onFreehandUp);
  syncMenuItems();
  showToast(
    mode === "eraser"
      ? "Ластик: проведите по краю объекта"
      : mode === "connect"
        ? "Проведите линию между областями"
        : createSession
          ? "Обведите область кистью, затем «Готово»"
          : "Кисть: проведите рядом с объектом, чтобы расширить",
  );
}

function stopFreehandEdit() {
  freehandActive = false;
  freehandPath = [];
  if (freehandPreview) overlaysGroup?.removeLayer(freehandPreview);
  freehandPreview = null;
  if (brushCursor) overlaysGroup?.removeLayer(brushCursor);
  brushCursor = null;
  brushCursorMeta = { radius: null, isEraser: null };
  const m = map();
  if (m) {
    m.off("mousedown", onFreehandDown);
    m.dragging.enable();
  }
  document.removeEventListener("mousemove", onFreehandDocMove);
  document.removeEventListener("mouseup", onFreehandUp);
}

function updateBrushCursor(latlng) {
  if (active !== "freehand" || !overlaysGroup || !latlng) return;
  const radius = Math.max(0.8, brushMeters() / 2);
  const isEraser = editDrawMode === "eraser";
  if (brushCursor && brushCursorMeta.isEraser === isEraser) {
    brushCursor.setLatLng(latlng);
    if (brushCursorMeta.radius !== radius) {
      brushCursor.setRadius(radius);
      brushCursorMeta.radius = radius;
    }
    return;
  }
  if (brushCursor) overlaysGroup.removeLayer(brushCursor);
  brushCursor = L.circle(latlng, {
    radius,
    color: isEraser ? "#e14059" : "#3388ff",
    weight: 1.5,
    dashArray: isEraser ? "2 3" : null,
    fillColor: isEraser ? "#e14059" : "#3388ff",
    fillOpacity: isEraser ? 0.12 : 0.08,
    interactive: false,
  });
  overlaysGroup.addLayer(brushCursor);
  brushCursorMeta = { radius, isEraser };
}

function onFreehandDown(e) {
  if (active !== "freehand" || !e.latlng) return;
  const oe = e.originalEvent;
  if (oe && oe.button !== 0) return;
  if (oe) {
    L.DomEvent.stopPropagation(oe);
    L.DomEvent.preventDefault(oe);
  }
  freehandTargetId = null;
  if (!createSession && (editDrawMode === "brush" || editDrawMode === "eraser")) {
    if (selected.length !== 1) {
      showToast("Выделите один объект для редактирования", true);
      return;
    }
    const record = getObjectRecord(selected[0]);
    if (isPointRecord(record)) {
      showToast("Кисть и ластик работают только с областями", true);
      return;
    }
    freehandTargetId = selected[0];
  }
  freehandActive = true;
  freehandPath = [e.latlng];
  updateBrushCursor(e.latlng);
}

function onFreehandDocMove(ev) {
  const m = map();
  if (active !== "freehand" || !m) return;
  let latlng;
  try {
    latlng = m.mouseEventToLatLng(ev);
  } catch {
    return;
  }
  if (!latlng) return;
  updateBrushCursor(latlng);
  if (!freehandActive) return;
  const last = freehandPath.at(-1);
  if (last && m.latLngToContainerPoint(last).distanceTo(m.latLngToContainerPoint(latlng)) < 1.5) return;
  freehandPath.push(latlng);
  updateFreehandPreview();
}

function onFreehandUp() {
  if (!freehandActive) return;
  freehandActive = false;
  if (freehandPreview) overlaysGroup?.removeLayer(freehandPreview);
  freehandPreview = null;
  const path = freehandPath;
  const mode = editDrawMode;
  const targetId = freehandTargetId;
  freehandPath = [];
  freehandTargetId = null;
  if (path.length >= 2) queue(() => applyFreehandStroke(path, mode, targetId));
}

function updateFreehandPreview() {
  if (freehandPath.length < 2) return;
  if (freehandPreview) {
    freehandPreview.setLatLngs(freehandPath);
    return;
  }
  const isEraser = editDrawMode === "eraser";
  freehandPreview = L.polyline(freehandPath, {
    color: isEraser ? "#e14059" : coordColor(),
    weight: isEraser
      ? Math.max(2, Math.min(16, brushMeters() / 3))
      : Math.max(2, Math.min(6, (display().weight || 2) + 1)),
    opacity: 0.9,
    lineCap: "round",
    lineJoin: "round",
    dashArray: isEraser ? "5 4" : "4 4",
    interactive: false,
  });
  overlaysGroup.addLayer(freehandPreview);
}

/** Visible polygon objects of a layer near a point (inside, or within `tolM` of the edge). */
function findRecordNear(layerId, latlng, tolM) {
  let best = null;
  let bestDist = Infinity;
  allObjectRecords().forEach((record) => {
    if (record.layer.id !== layerId || !isRecordVisible(record) || isPointRecord(record)) return;
    const d = distanceToGeomM(record.obj.geom, latlng);
    if (d <= tolM && d < bestDist) {
      best = record;
      bestDist = d;
    }
  });
  return best;
}

async function applyFreehandStroke(path, mode, targetId) {
  const radius = Math.max(1, brushMeters() / 2);
  const layerId = currentDrawLayerId();
  if (!layerId || !getLayer(layerId)) {
    showToast("Выберите слой", true);
    return;
  }

  if (mode === "create") {
    // The outline always closes end-to-start, like drawing a shape by hand.
    let result = null;
    const outline = outlinePolygonGeom(path);
    if (outline) result = keepLargestPart(outline);
    if (!result || result.isEmpty || geodesicAreaM2(result.geom) < 1) {
      const buffer = strokeBufferGeom(path, radius);
      result = buffer ? keepLargestPart(buffer) : null;
    }
    if (!result || result.isEmpty) {
      showToast("Проведите дольше, чтобы создать область", true);
      return;
    }
    await createTracked(layerId, result.geom);
    expandLayer(layerId);
    showToast("Контур применён");
    return;
  }

  const strokeBuf = strokeBufferGeom(path, radius);
  if (!strokeBuf) {
    showToast("Проведите дольше, чтобы применить инструмент", true);
    return;
  }

  if (mode === "connect") {
    const tolM = Math.max(radius, 5);
    const start = findRecordNear(layerId, path[0], tolM);
    const end = findRecordNear(layerId, path.at(-1), tolM);
    if (!start && !end) {
      showToast("Начните или закончите линию на объекте выбранного слоя", true);
      return;
    }
    if (start && end && start.obj.id !== end.obj.id) {
      const joined = unionGeom(unionGeom(start.obj.geom, end.obj.geom), strokeBuf);
      const keepAll = polygonParts(start.obj.geom).length > 1 || polygonParts(end.obj.geom).length > 1;
      const result = joined ? keepLargestPart(joined, { keepAllParts: keepAll }) : null;
      if (!result || result.isEmpty) {
        showToast("Не удалось соединить области", true);
        return;
      }
      clearSelection();
      hideFieldDetail();
      await mergeTracked(start, end, result.geom);
      showToast("Области соединены по нарисованной линии");
      return;
    }
    const target = start || end;
    const extended = unionGeom(target.obj.geom, strokeBuf);
    const result = extended
      ? keepLargestPart(extended, { keepAllParts: polygonParts(target.obj.geom).length > 1 })
      : null;
    if (!result || result.isEmpty) {
      showToast("Не удалось дорисовать соединение", true);
      return;
    }
    await patchTracked(target.obj.id, target.obj.geom, result.geom);
    showToast("Соединение дорисовано");
    return;
  }

  const record = getObjectRecord(targetId);
  if (!record) {
    showToast("Выделите один объект — инструмент работает только с ним", true);
    return;
  }
  const before = record.obj.geom;
  const keepAllParts = polygonParts(before).length > 1;

  if (mode === "eraser") {
    // A closed loop (lasso) removes everything inside it, not only a strip along the line.
    let cutter = strokeBuf;
    if (isLoopClosedM(path, radius)) {
      const loop = outlinePolygonGeom(path);
      if (loop) cutter = unionGeom(loop, strokeBuf) || strokeBuf;
    }
    const cut = differenceGeom(before, cutter);
    if (cut === undefined) {
      showToast("Не удалось изменить контур — попробуйте провести иначе", true);
      return;
    }
    const result = keepLargestPart(cut, { keepAllParts });
    if (result.isEmpty) {
      showToast("Ластик стирает контур целиком — удалите объект вручную, если это нужно", true);
      return;
    }
    await patchTracked(record.obj.id, before, result.geom);
    showToast(
      result.holes > holesOf(before)
        ? "В контуре вырезано отверстие"
        : result.discarded
          ? "Контур скорректирован (оставлена самая крупная часть)"
          : "Контур скорректирован",
    );
    return;
  }

  // brush: extend the selected object
  const unioned = unionGeom(before, strokeBuf);
  const result = unioned ? keepLargestPart(unioned, { keepAllParts }) : null;
  if (!result || result.isEmpty) {
    showToast("Не удалось расширить область — попробуйте провести иначе", true);
    return;
  }
  await patchTracked(record.obj.id, before, result.geom);
  showToast("Область расширена");
}

/* ---------------------------------------------------------------- polygon by vertices */

function vertexDot(latlng, isFirst) {
  return L.circleMarker(latlng, {
    radius: isFirst ? 10 : 7,
    color: "#ffffff",
    weight: 3,
    fillColor: isFirst ? "#22c55e" : "#e14059",
    fillOpacity: 1,
    interactive: false,
    className: "vertex-handle",
  });
}

function redrawVertexPreview(cursor) {
  if (!ensureGroups()) return;
  if (!vertexScratch) vertexScratch = L.layerGroup().addTo(overlaysGroup);
  vertexScratch.clearLayers();
  if (vertexPts.length >= 3) {
    L.polygon([...vertexPts, vertexPts[0]], {
      color: "#e14059",
      weight: 1,
      fillColor: "#e14059",
      fillOpacity: 0.12,
      dashArray: "4 4",
      interactive: false,
    }).addTo(vertexScratch);
  }
  if (vertexPts.length >= 2) L.polyline(vertexPts, { color: "#e14059", weight: 3, interactive: false }).addTo(vertexScratch);
  if (cursor && vertexPts.length) {
    L.polyline([vertexPts.at(-1), cursor], { color: "#fb7185", weight: 2, dashArray: "6 4", interactive: false }).addTo(
      vertexScratch,
    );
  }
  vertexPts.forEach((p, i) => vertexDot(p, i === 0).addTo(vertexScratch));
}

function clearPolygonDraft() {
  vertexPts = [];
  if (vertexScratch) overlaysGroup?.removeLayer(vertexScratch);
  vertexScratch = null;
  const m = map();
  m?.off("mousemove", onPolygonMove);
  m?.off("dblclick", onPolygonDblClick);
  m?.doubleClickZoom?.enable();
}

function startPolygonDrawing() {
  const m = map();
  if (!m || !ensureGroups()) return;
  stopFreehandEdit();
  clearPolygonDraft();
  active = "polygon";
  editDrawMode = "polygon";
  const mapArea = $("map-area");
  mapArea?.classList.remove("tool-select", "tool-ruler", "tool-compass", "tool-text", "tool-freehand", "tool-eraser", "tool-brush");
  mapArea?.classList.add("tool-polygon");
  document.querySelectorAll(".tool-btn[data-tool]").forEach((btn) => btn.classList.remove("active"));
  m.doubleClickZoom?.disable();
  m.on("mousemove", onPolygonMove);
  m.on("dblclick", onPolygonDblClick);
  syncMenuItems();
}

function handlePolygonClick(e) {
  const m = map();
  if (!e.latlng || !m) return;
  if (vertexPts.length >= 3) {
    const first = m.latLngToLayerPoint(vertexPts[0]);
    if (first.distanceTo(m.latLngToLayerPoint(e.latlng)) <= 16) {
      finishPolygonDraw({ stay: true });
      return;
    }
  }
  if (vertexPts.length) {
    const last = m.latLngToLayerPoint(vertexPts.at(-1));
    if (last.distanceTo(m.latLngToLayerPoint(e.latlng)) < 4) return;
  }
  vertexPts.push(e.latlng);
  redrawVertexPreview();
  if (vertexPts.length === 1) showToast("Кликайте следующие вершины. Зелёная точка замыкает контур.");
}

function onPolygonMove(e) {
  if (!vertexPts.length || !e.latlng) return;
  redrawVertexPreview(e.latlng);
}

function onPolygonDblClick(e) {
  L.DomEvent.stopPropagation(e);
  const m = map();
  if (m && vertexPts.length >= 2) {
    const last = m.latLngToLayerPoint(vertexPts.at(-1));
    const prev = m.latLngToLayerPoint(vertexPts.at(-2));
    if (last.distanceTo(prev) <= 10) vertexPts.pop();
  }
  finishPolygonDraw({ stay: true });
}

/** Enter / double click / green point / «Готово»: saves the drawn polygon. */
export function finishPolygonDraw({ stay = true } = {}) {
  if (active !== "polygon") return false;
  if (vertexPts.length < 3) {
    showToast("Нужно минимум 3 точки", true);
    return false;
  }
  const geom = polygonFromLatLngs(vertexPts);
  vertexPts = [];
  redrawVertexPreview();
  const editId = !createSession && selected.length === 1 ? selected[0] : null;
  const layerId = currentDrawLayerId();
  queue(async () => {
    if (editId) {
      const record = getObjectRecord(editId);
      if (!record) return;
      const unioned = unionGeom(record.obj.geom, geom);
      const result = unioned
        ? keepLargestPart(unioned, { keepAllParts: polygonParts(record.obj.geom).length > 1 })
        : null;
      if (!result || result.isEmpty) {
        showToast("Операция уничтожила контур — отменена", true);
        return;
      }
      await patchTracked(editId, record.obj.geom, result.geom);
      showToast("Контур добавлен к области");
      return;
    }
    if (!layerId) {
      showToast("Создайте слой для рисования", true);
      return;
    }
    await createTracked(layerId, geom);
    expandLayer(layerId);
    showToast(stay ? "Область создана — кликайте, чтобы начать следующую" : "Область создана");
  });
  if (!stay) setTool("select");
  return true;
}

/* ---------------------------------------------------------------- draw layer select */

/** «Слой» in the drawing panel: «+ Новый слой…», target layer while creating, move of the edited object. */
export function onDrawLayerSelect(value) {
  if (value === "__new__") {
    openAppModal({
      title: "Новый слой",
      bodyHtml: `<label class="modal-label" for="modal-new-layer-name">Название</label>
        <input type="text" id="modal-new-layer-name" class="search-input modal-input" value="Новый слой" maxlength="120">`,
      actions: [
        {
          label: "Создать",
          className: "mini-btn mini-btn-red",
          onClick: async () => {
            const name = $("modal-new-layer-name")?.value.trim();
            if (!name) return;
            closeAppModal();
            try {
              const created = await createLayerQuick(name);
              populateDrawLayerSelect();
              const sel = $("draw-layer-select");
              if (sel) sel.value = created.id;
              onDrawLayerSelect(created.id);
              showToast(`Слой «${name}» создан`);
            } catch (err) {
              showToast(err.message, true);
              populateDrawLayerSelect();
            }
          },
        },
        {
          label: "Отмена",
          className: "mini-btn",
          onClick: () => {
            closeAppModal();
            populateDrawLayerSelect();
          },
        },
      ],
    });
    setTimeout(() => $("modal-new-layer-name")?.select(), 30);
    return;
  }
  if (createSession || editDrawMode === "connect") return;
  if (selected.length === 1) {
    const record = getObjectRecord(selected[0]);
    if (record && record.layer.id !== value) {
      const target = getLayer(value);
      queue(async () => {
        await moveTracked(record.obj.id, record.layer.id, value);
        showToast(`Объект перенесён в слой «${target?.name || ""}»`);
      });
    }
  }
}

/* ---------------------------------------------------------------- tool switching */

function deactivateCurrentTool() {
  stopFreehandEdit();
  clearPolygonDraft();
  clearRulerPreview();
  clearCompassDrawing();
  $("map-area")?.classList.remove("tool-eraser", "tool-brush");
}

function ensureBound() {
  if (bound) return;
  const m = map();
  const group = getFeatureGroup();
  if (!m || !group) return;
  bound = true;
  ensureGroups();
  m.on("click", onMapClick);
  group.on("click", onObjectClick);
  group.on("dblclick", onObjectDblClick);
  onRecordsChanged(onRecordsRebuilt);
  // «Слои карты» → click on an object name: select it and fly to it.
  document.addEventListener("av:select-object", (e) => {
    if (!e.detail?.id) return;
    if (active !== "select") setTool("select", { silent: true });
    selectObjectById(e.detail.id, { zoom: !!e.detail.zoom });
  });
  setUndoHook(() => {
    clearSelection();
    hideFieldDetail();
  });
}

export function setTool(tool, { silent = false } = {}) {
  ensureBound();
  const name = TOOL_NAMES[tool] ? tool : "select";
  if (mergeActive && name !== "select") cancelMergeMode();
  if (name !== "freehand" && name !== "polygon") createSession = false;
  deactivateCurrentTool();
  active = name;
  editDrawMode = null;
  document.querySelectorAll(".tool-btn[data-tool]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tool === name);
  });
  const mapArea = $("map-area");
  if (mapArea) {
    mapArea.classList.remove(
      "tool-select",
      "tool-ruler",
      "tool-compass",
      "tool-text",
      "tool-freehand",
      "tool-eraser",
      "tool-brush",
      "tool-polygon",
      "tool-merge",
    );
    mapArea.classList.add(`tool-${name}`);
  }
  map()?.dragging?.enable();
  const box = $("edit-area-controls");
  if (box) box.style.display = "none";
  syncMenuItems();
  if (!silent) {
    const label = TOOL_NAMES[name] || name;
    showToast(`Инструмент: ${label}`);
    logAction("tool", `Выбран инструмент: ${label}`);
  }
}

export function activateMapTool(name, options) {
  setTool(name, options);
}

/** Esc: drop whatever is being drawn (nothing is saved) and return to selection. */
export function cancelActiveTool({ silent = false } = {}) {
  if (mergeActive) cancelMergeMode();
  map()?.closePopup();
  createSession = false;
  deactivateCurrentTool();
  const box = $("edit-area-controls");
  if (box) box.style.display = "none";
  setEraserEnabled(true);
  setTool("select", { silent });
}

/** Ctrl+G: captions and vertex coordinates together. */
export function toggleLabelsAndCoords() {
  const current = getMapDisplay();
  const next = !(current.labels && current.coords);
  setMapDisplayOption("labels", next);
  setMapDisplayOption("coords", next);
  showToast(next ? "Подписи и координаты включены" : "Подписи и координаты скрыты");
}

/** After logout: forget the selection, marks and history of the previous account. */
export function resetTools() {
  cancelActiveTool({ silent: true });
  clearSelection();
  hideFieldDetail();
  overlays.forEach(({ layer, parent }) => parent?.removeLayer(layer));
  overlays = [];
  hoveredOverlay = null;
  selectedOverlay = null;
  selectionHistory.length = 0;
  historyCursor = -1;
  clearIdAliases();
}
