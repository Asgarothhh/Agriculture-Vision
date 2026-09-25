import { showToast, openAppModal, closeAppModal, $, dbg } from "../ui.js";
import * as layersApi from "../api/layers.js";
import {
  loadMapData,
  persistDrawnLayer,
  patchObjectGeom,
  getObjectRecord,
  allObjectRecords,
  highlightObjects,
  populateDrawLayerSelect,
} from "../layers/store.js";
import { getFeatureGroup, getMap, rememberBounds } from "./map.js";
import {
  bufferStroke,
  bridgePolygons,
  circlePolygon,
  diffGeom,
  formatArea,
  geodesicAreaM2,
  geomContainsLatLng,
  isClosedStroke,
  polygonFromLatLngs,
  simplifyLatLngs,
  strokeLengthPx,
  unionGeom,
} from "./geometry.js";
import { pushUndo } from "./undo.js";

let active = "select";
let scratch = null;
let preview = null;
let rulerPts = [];
let compassCenter = null;
let compassRadius = 0;
let brushPts = [];
let drawing = false;
let handlers = [];
let selected = [];
let lastHover = null;
let annotations = [];
let editMode = "brush";
let paintIntent = "create";
let mergePicks = [];
let vertexPts = [];
let labelsOn = true;
let coordsOn = true;

const DRAW_HINTS = {
  brush: "Зажмите ЛКМ и ведите. Замкните к зелёной точке — полигон; короткий штрих — полоса по толщине.",
  eraser: "Зажмите и проведите по области, чтобы вырезать. Полное стирание контура отменяется.",
  polygon: "Кликайте вершины. Белые точки на концах отрезков; зелёная — замкнуть. Enter или двойной клик — готово.",
};

export function getSelected() {
  return selected.slice();
}

export function currentMapTool() {
  return active;
}

function map() {
  return getMap();
}

function clearScratch() {
  const m = map();
  if (scratch && m) m.removeLayer(scratch);
  if (preview && m) m.removeLayer(preview);
  scratch = null;
  preview = null;
}

function isDomTarget(target) {
  return target === document || (typeof HTMLElement !== "undefined" && target instanceof HTMLElement);
}

function detach() {
  const m = map();
  handlers.forEach(([ev, fn, target, capture]) => {
    if (isDomTarget(target)) target.removeEventListener(ev, fn, !!capture);
    else (target || m)?.off(ev, fn);
  });
  handlers = [];
  rulerPts = [];
  compassCenter = null;
  brushPts = [];
  drawing = false;
  mergePicks = [];
  vertexPts = [];
  if (m?.dragging) m.dragging.enable();
  if (m?.doubleClickZoom) m.doubleClickZoom.enable();
  clearScratch();
}

function wrapDom(fn) {
  return (domEv) => {
    const m = map();
    if (!m) return;
    let latlng = null;
    try {
      latlng = m.mouseEventToLatLng(domEv);
    } catch {
      latlng = null;
    }
    fn({ latlng, originalEvent: domEv });
  };
}

function on(ev, fn, target) {
  if (isDomTarget(target)) {
    const wrapped = wrapDom(fn);
    const capture = ev === "mousedown" || ev === "pointerdown";
    target.addEventListener(ev, wrapped, capture);
    handlers.push([ev, wrapped, target, capture]);
    return;
  }
  const src = target || map();
  src.on(ev, fn);
  handlers.push([ev, fn, target, false]);
}

function coordColor() {
  return $("opt-coord-color")?.value || "#e14059";
}

function brushMeters() {
  return Number($("brush-size")?.value || 20);
}

function isMod(ev) {
  const o = ev.originalEvent || ev;
  return !!(o.ctrlKey || o.metaKey || o.shiftKey);
}

function findPart(e) {
  return e.layer || e.target;
}

export function setSelection(ids, { additive = false } = {}) {
  if (!additive) selected = [];
  ids.forEach((id) => {
    if (!selected.includes(id)) selected.push(id);
  });
  highlightObjects(selected);
  const one = selected.length === 1 ? getObjectRecord(selected[0]) : null;
  if (one) {
    $("field-detail-panel").style.display = "block";
    $("field-name-input").value = one.obj.name || "";
    $("field-name-input").dataset.objectId = one.obj.id;
    $("field-area-value").textContent = formatArea(geodesicAreaM2(one.obj.geom));
  } else if (!selected.length) {
    $("field-detail-panel").style.display = "none";
  }
}

function onSelectClick(e) {
  L.DomEvent.stop(e);
  const part = findPart(e);
  const obj = part?.avObject;
  if (!obj) {
    if (!isMod(e)) setSelection([]);
    return;
  }
  if (selected.length === 1 && selected[0] === obj.id && !isMod(e)) {
    openEditAreaMode();
    return;
  }
  if (isMod(e)) setSelection([obj.id], { additive: true });
  else setSelection([obj.id]);
  rememberBounds(part.getBounds?.());
}

function onMapBlankClick(e) {
  if (e.originalEvent?.target?.closest?.(".leaflet-interactive")) return;
  if (!isMod(e)) setSelection([]);
}

function tickStep(zoom) {
  if (zoom >= 16) return 10;
  if (zoom >= 14) return 20;
  if (zoom >= 12) return 50;
  return 100;
}

function onRulerClick(e) {
  const m = map();
  if (!scratch) scratch = L.layerGroup().addTo(m);
  if (rulerPts.length >= 2) {
    rulerPts = [];
    scratch.clearLayers();
  }
  rulerPts.push(e.latlng);
  L.circleMarker(e.latlng, { radius: 5, color: coordColor(), fillOpacity: 1 }).addTo(scratch);
  if (rulerPts.length === 1) {
    preview = L.polyline([e.latlng, e.latlng], { color: coordColor(), dashArray: "6 4", weight: 2 }).addTo(m);
    return;
  }
  finalizeRuler(rulerPts[0], rulerPts[1]);
}

function onRulerMove(e) {
  if (rulerPts.length !== 1 || !preview) return;
  preview.setLatLngs([rulerPts[0], e.latlng]);
  const meters = map().distance(rulerPts[0], e.latlng);
  preview.bindTooltip(formatDist(meters), { permanent: true, direction: "center" }).openTooltip(e.latlng);
}

function formatDist(meters) {
  return meters >= 1000 ? `${(meters / 1000).toFixed(2)} км` : `${Math.round(meters)} м`;
}

function finalizeRuler(a, b) {
  clearScratch();
  const group = L.layerGroup().addTo(map());
  const color = coordColor();
  L.circleMarker(a, { radius: 5, color, fillOpacity: 1 }).addTo(group);
  L.circleMarker(b, { radius: 5, color, fillOpacity: 1 }).addTo(group);
  L.polyline([a, b], { color, weight: 2 }).addTo(group);
  const meters = map().distance(a, b);
  L.tooltip({ permanent: true, direction: "center", className: "ruler-label" })
    .setLatLng([(a.lat + b.lat) / 2, (a.lng + b.lng) / 2])
    .setContent(formatDist(meters))
    .addTo(group);
  const step = tickStep(map().getZoom());
  const n = Math.floor(meters / step);
  for (let i = 1; i < n; i += 1) {
    const t = (i * step) / meters;
    const p = L.latLng(a.lat + (b.lat - a.lat) * t, a.lng + (b.lng - a.lng) * t);
    L.circleMarker(p, { radius: 2, color, fillOpacity: 1 }).addTo(group);
  }
  annotations.push({ type: "ruler", layer: group });
  preview = null;
  scratch = group;
}

function onCompassClick(e) {
  const m = map();
  if (!scratch) scratch = L.layerGroup().addTo(m);
  if (!compassCenter) {
    compassCenter = e.latlng;
    L.circleMarker(e.latlng, { radius: 5, color: coordColor() }).addTo(scratch);
    preview = L.circle(e.latlng, { radius: 1, color: coordColor(), dashArray: "6 4", fillOpacity: 0.08 }).addTo(m);
    showToast("Кликните край окружности");
    return;
  }
  compassRadius = m.distance(compassCenter, e.latlng);
  finalizeCompass(compassCenter, compassRadius);
  compassCenter = null;
}

function onCompassMove(e) {
  if (!compassCenter || !preview) return;
  const r = map().distance(compassCenter, e.latlng);
  preview.setRadius(r);
  preview.bindTooltip(`R = ${formatDist(r)}`, { permanent: true }).openTooltip(e.latlng);
}

function finalizeCompass(center, radius) {
  const group = L.layerGroup().addTo(map());
  const color = coordColor();
  L.circleMarker(center, { radius: 5, color }).addTo(group);
  L.circle(center, { radius, color, fillOpacity: 0.08 }).addTo(group);
  L.tooltip({ permanent: true })
    .setLatLng(center)
    .setContent(`R = ${formatDist(radius)}`)
    .addTo(group);
  annotations.push({ type: "compass", layer: group, center, radius });
  clearScratch();
  openAppModal({
    title: "Циркуль",
    bodyHtml: `<p>Радиус ${formatDist(radius)}</p>`,
    actions: [
      { label: "Закрыть", onClick: closeAppModal },
      {
        label: "+ Область по кругу",
        className: "mini-btn mini-btn-blue",
        onClick: async () => {
          closeAppModal();
          const poly = L.geoJSON(circlePolygon(center, radius));
          const created = await persistDrawnLayer(poly.getLayers()[0]);
          if (created) {
            pushUndo({
              undo: async () => {
                await layersApi.deleteObject(created.id);
                await loadMapData();
              },
              redo: async () => {
                await persistDrawnLayer(poly.getLayers()[0]);
              },
            });
          }
        },
      },
      {
        label: "Вырезать по кругу",
        className: "mini-btn mini-btn-red",
        onClick: async () => {
          closeAppModal();
          if (selected.length !== 1) {
            showToast("Выделите один объект", true);
            return;
          }
          await cutWithGeom(selected[0], circlePolygon(center, radius));
        },
      },
    ],
  });
}

function onTextClick(e) {
  L.DomEvent.stop(e);
  openAppModal({
    title: "Текст на карте",
    bodyHtml: `<div class="input-group"><label>ПОДПИСЬ</label><input id="map-text-input" class="search-input"></div>`,
    actions: [
      { label: "Отмена", onClick: closeAppModal },
      {
        label: "Добавить",
        className: "mini-btn mini-btn-red",
        onClick: () => {
          const text = $("map-text-input")?.value?.trim();
          closeAppModal();
          if (!text) return;
          const marker = L.marker(e.latlng, {
            icon: L.divIcon({ className: "map-text-label", html: text, iconSize: [0, 0] }),
          }).addTo(map());
          annotations.push({ type: "text", layer: marker });
        },
      },
    ],
  });
  setTimeout(() => $("map-text-input")?.focus(), 50);
}

function isUiEvent(domEv) {
  return !!domEv?.target?.closest?.(".more-menu, .sidebar-panel, .sidebar-icons, .topbar, #app-modal, button, input, select, textarea, a");
}

function brushWeightPx() {
  const m = map();
  const meters = brushMeters();
  const c = m.getCenter();
  const a = m.latLngToLayerPoint(c);
  const b = m.latLngToLayerPoint(L.latLng(c.lat + meters / 111320, c.lng));
  return Math.max(6, a.distanceTo(b));
}

function objectIdAt(latlng) {
  if (!latlng) return null;
  for (const rec of allObjectRecords()) {
    if (geomContainsLatLng(rec.obj.geom, latlng)) return rec.obj.id;
  }
  return null;
}

function onBrushDown(e) {
  if (active !== "brush" && active !== "freehand" && active !== "eraser") return;
  const oe = e.originalEvent;
  if (!oe || oe.button !== 0) return;
  if (isUiEvent(oe)) return;
  if (!e.latlng) return;
  oe.preventDefault?.();
  drawing = true;
  brushPts = [e.latlng];
  map().dragging.disable();
  clearScratch();
  const erasing = active === "eraser" || editMode === "eraser";
  scratch = L.polyline(brushPts, {
    color: erasing ? "#0f172a" : "#e14059",
    weight: brushWeightPx(),
    opacity: 0.45,
    lineCap: "round",
    lineJoin: "round",
    interactive: false,
  }).addTo(map());
}

function onBrushMove(e) {
  if (!drawing || !scratch || !e.latlng) return;
  const last = brushPts.at(-1);
  const pt = map().latLngToLayerPoint(e.latlng);
  const prev = map().latLngToLayerPoint(last);
  if (pt.distanceTo(prev) < 1.5) return;
  brushPts.push(e.latlng);
  scratch.setLatLngs(brushPts);
  const erasing = active === "eraser" || editMode === "eraser";
  scratch.setStyle({
    color: isClosedStroke(brushPts, map()) ? "#22c55e" : erasing ? "#0f172a" : "#e14059",
  });
}

async function onBrushUp() {
  if (!drawing) return;
  drawing = false;
  if (active !== "brush" && active !== "freehand" && active !== "eraser") return;
  try {
    const m = map();
    const pts = simplifyLatLngs(brushPts, m, 3);
    const travel = strokeLengthPx(pts, m);
    clearScratch();
    if (travel < 8 && pts.length < 3) {
      showToast("Проведите штрих по карте (клик без движения не рисует)");
      return;
    }
    const closed = isClosedStroke(pts, m);
    const geom = closed ? polygonFromLatLngs(pts) : bufferStroke(pts, brushMeters());
    if (!geom) {
      showToast("Не удалось построить контур", true);
      return;
    }
    const erasing = active === "eraser" || editMode === "eraser";
    if (erasing) {
      const targetId = selected.length === 1 ? selected[0] : objectIdAt(pts[0]) || objectIdAt(pts.at(-1));
      if (!targetId) {
        showToast("Проведите ластиком по области (или сначала выделите её)", true);
        return;
      }
      await cutWithGeom(targetId, geom);
      return;
    }
    if (paintIntent === "edit" && selected.length === 1) {
      await unionWithGeom(selected[0], geom);
      return;
    }
    const layer = L.geoJSON(geom);
    const created = await persistDrawnLayer(layer.getLayers()[0]);
    if (created) {
      pushUndo({
        undo: async () => {
          await layersApi.deleteObject(created.id);
          await loadMapData();
        },
        redo: async () => persistDrawnLayer(layer.getLayers()[0]),
      });
    }
  } catch (err) {
    showToast(err.message || "Не удалось применить штрих", true);
  }
}

async function unionWithGeom(objectId, extra) {
  const rec = getObjectRecord(objectId);
  if (!rec) return;
  const prev = rec.obj.geom;
  const next = unionGeom(prev, extra);
  if (!next) {
    showToast("Операция уничтожила контур — отменена", true);
    return;
  }
  await patchObjectGeom(objectId, next);
  pushUndo({
    undo: () => patchObjectGeom(objectId, prev),
    redo: () => patchObjectGeom(objectId, next),
  });
}

async function cutWithGeom(objectId, cutter) {
  const rec = getObjectRecord(objectId);
  if (!rec) return;
  const prev = rec.obj.geom;
  const next = diffGeom(prev, cutter);
  if (!next) {
    showToast("Операция уничтожила контур — отменена", true);
    return;
  }
  await patchObjectGeom(objectId, next);
  pushUndo({
    undo: () => patchObjectGeom(objectId, prev),
    redo: () => patchObjectGeom(objectId, next),
  });
}

export async function mergeSelectedPair() {
  const ids = mergePicks.length === 2 ? mergePicks : selected;
  if (ids.length !== 2) {
    showToast("За раз можно объединить только 2 области", true);
    return;
  }
  const a = getObjectRecord(ids[0]);
  const b = getObjectRecord(ids[1]);
  if (!a || !b) return;
  if (a.obj.layer_id !== b.obj.layer_id) {
    showToast("Объединять можно только области одного слоя", true);
    return;
  }
  try {
    let geom = unionGeom(a.obj.geom, b.obj.geom);
    const multi = geom?.type === "MultiPolygon";
    if (multi) geom = bridgePolygons(a.obj.geom, b.obj.geom);
    const merged = await layersApi.mergeObjects([a.obj.id, b.obj.id], geom);
    showToast("Объекты объединены");
    await loadMapData();
    if (merged?.id) setSelection([merged.id]);
    pushUndo({
      undo: async () => {
        showToast("Отмена объединения: восстановите объекты через историю, если нужно");
      },
      redo: async () => {},
    });
  } catch (err) {
    showToast(err.message, true);
  }
}

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
  const m = map();
  if (!m) return;
  if (!scratch) scratch = L.layerGroup().addTo(m);
  scratch.clearLayers();
  if (vertexPts.length >= 3) {
    L.polygon([...vertexPts, vertexPts[0]], {
      color: "#e14059",
      weight: 1,
      fillColor: "#e14059",
      fillOpacity: 0.12,
      dashArray: "4 4",
      interactive: false,
    }).addTo(scratch);
  }
  if (vertexPts.length >= 2) {
    L.polyline(vertexPts, { color: "#e14059", weight: 3, interactive: false }).addTo(scratch);
  }
  if (cursor && vertexPts.length) {
    L.polyline([vertexPts.at(-1), cursor], {
      color: "#fb7185",
      weight: 2,
      dashArray: "6 4",
      interactive: false,
    }).addTo(scratch);
  }
  vertexPts.forEach((p, i) => vertexDot(p, i === 0).addTo(scratch));
}

function onPolygonClick(e) {
  L.DomEvent.stop(e);
  if (!e.latlng) return;
  if (isUiEvent(e.originalEvent)) return;
  if (vertexPts.length >= 3) {
    const first = map().latLngToLayerPoint(vertexPts[0]);
    const cur = map().latLngToLayerPoint(e.latlng);
    if (first.distanceTo(cur) <= 16) {
      finishPolygonDraw({ stay: true });
      return;
    }
  }
  if (vertexPts.length) {
    const last = map().latLngToLayerPoint(vertexPts.at(-1));
    const cur = map().latLngToLayerPoint(e.latlng);
    if (last.distanceTo(cur) < 4) return;
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
  L.DomEvent.stop(e);
  if (vertexPts.length >= 2) {
    const last = map().latLngToLayerPoint(vertexPts.at(-1));
    const prev = map().latLngToLayerPoint(vertexPts.at(-2));
    if (last.distanceTo(prev) <= 10) vertexPts.pop();
  }
  finishPolygonDraw({ stay: true });
}

export async function finishPolygonDraw({ stay = true } = {}) {
  if (active !== "polygon") return false;
  if (vertexPts.length < 3) {
    showToast("Нужно минимум 3 точки", true);
    return false;
  }
  const geom = polygonFromLatLngs(vertexPts);
  vertexPts = [];
  clearScratch();
  if (paintIntent === "edit" && selected.length === 1) {
    await unionWithGeom(selected[0], geom);
    showToast("Контур добавлен к области");
    if (!stay) setTool("select");
    else redrawVertexPreview();
    return true;
  }
  const layer = L.geoJSON(geom);
  const created = await persistDrawnLayer(layer.getLayers()[0]);
  if (created) {
    pushUndo({
      undo: async () => {
        await layersApi.deleteObject(created.id);
        await loadMapData();
      },
      redo: async () => persistDrawnLayer(layer.getLayers()[0]),
    });
  }
  showToast("Область создана — кликайте, чтобы начать следующую");
  if (!stay) setTool("select");
  return true;
}

export function setPaintIntent(intent) {
  paintIntent = intent === "edit" ? "edit" : "create";
}

export function startPolygonMode() {
  populateDrawLayerSelect();
  $("edit-area-controls").style.display = "block";
  $("merge-mode-panel").style.display = "none";
  $("more-menu")?.classList.add("active");
  $("polygon-area-item")?.classList.add("active");
  $("create-area-item")?.classList.remove("active");
  $("edit-area-item")?.classList.remove("active");
  $("merge-menu-item")?.classList.remove("active");
  vertexPts = [];
  setPaintIntent("create");
  setEditDrawMode("polygon");
  showToast("Кликайте вершины. На концах отрезков — точки. Зелёная замыкает.");
}

export function startMergeMode() {
  mergePicks = [];
  $("merge-mode-panel").style.display = "block";
  $("edit-area-controls").style.display = "none";
  $("merge-mode-hint").textContent = "Выбрано: 0 из 2";
  $("merge-confirm-btn").disabled = true;
  $("more-menu")?.classList.add("active");
  setTool("merge");
}

function onMergeClick(e) {
  L.DomEvent.stop(e);
  const obj = findPart(e)?.avObject;
  if (!obj) return;
  if (mergePicks.includes(obj.id)) return;
  if (mergePicks.length >= 2) {
    showToast("За раз можно объединить только 2 области — сначала снимите одну", true);
    return;
  }
  if (mergePicks.length) {
    const first = getObjectRecord(mergePicks[0]);
    if (first && first.obj.layer_id !== obj.layer_id) {
      showToast("Объединять можно только области одного слоя", true);
      return;
    }
  }
  mergePicks.push(obj.id);
  $("merge-mode-hint").textContent = `Выбрано: ${mergePicks.length} из 2`;
  $("merge-confirm-btn").disabled = mergePicks.length < 2;
}

export function cancelMergeMode() {
  mergePicks = [];
  $("merge-mode-panel").style.display = "none";
  $("merge-confirm-btn").disabled = true;
  setTool("select");
}

export function openEditAreaMode() {
  if (selected.length !== 1) {
    showToast("Сначала выберите одну область инструментом «Выделить»", true);
    return;
  }
  $("edit-area-controls").style.display = "block";
  $("merge-mode-panel").style.display = "none";
  $("more-menu")?.classList.add("active");
  $("edit-area-item")?.classList.add("active");
  $("create-area-item")?.classList.remove("active");
  $("polygon-area-item")?.classList.remove("active");
  $("merge-menu-item")?.classList.remove("active");
  populateDrawLayerSelect();
  setPaintIntent("edit");
  setEditDrawMode("brush");
}

export async function finishEditAreaMode() {
  if (active === "polygon" && vertexPts.length >= 3) {
    await finishPolygonDraw({ stay: false });
  }
  $("edit-area-controls").style.display = "none";
  $("create-area-item")?.classList.remove("active");
  $("polygon-area-item")?.classList.remove("active");
  $("edit-area-item")?.classList.remove("active");
  setPaintIntent("create");
  setTool("select");
}

function updatePaintHud() {
  const titles = { brush: "Кисть", eraser: "Ластик", polygon: "Полигон по точкам" };
  if ($("paint-hud-title")) $("paint-hud-title").textContent = titles[editMode] || "Рисование";
  if ($("paint-hud-hint")) $("paint-hud-hint").textContent = DRAW_HINTS[editMode] || "";
  $("edit-brush-btn")?.classList.toggle("active", editMode === "brush");
  $("edit-eraser-btn")?.classList.toggle("active", editMode === "eraser");
  $("edit-polygon-btn")?.classList.toggle("active", editMode === "polygon");
}

export function setEditDrawMode(mode) {
  editMode = mode;
  updatePaintHud();
  if (mode === "polygon") {
    $("polygon-area-item")?.classList.add("active");
    $("create-area-item")?.classList.remove("active");
  } else if (paintIntent === "create") {
    $("create-area-item")?.classList.add("active");
    $("polygon-area-item")?.classList.remove("active");
  }
  setTool(mode === "eraser" ? "eraser" : mode === "polygon" ? "polygon" : "brush");
}

function hoverAt(e) {
  lastHover = e.layer?.avObject || e.target?.avObject || null;
}

export async function deleteAtPriority() {
  const hoverAnn = annotations.find((item) => item.layer?._map && item.layer.getBounds?.()?.contains?.(map().getCenter()));
  const under = annotations.find((item) => {
    try {
      return item.layer.getElement?.() && item.layer._icon;
    } catch {
      return false;
    }
  });
  if (lastHover?.id) {
    const rec = getObjectRecord(lastHover.id);
    await layersApi.deleteObject(lastHover.id);
    await loadMapData();
    pushUndo({
      undo: async () => rec && persistDrawnLayer(L.geoJSON(rec.obj.geom).getLayers()[0]),
      redo: async () => layersApi.deleteObject(lastHover.id).then(loadMapData),
    });
    return;
  }
  if (selected.length) {
    const ids = selected.slice();
    await Promise.all(ids.map((id) => layersApi.deleteObject(id)));
    await loadMapData();
    setSelection([]);
    return;
  }
  const last = annotations.pop();
  if (last?.layer) {
    map().removeLayer(last.layer);
    return;
  }
  if (under?.layer) {
    map().removeLayer(under.layer);
    return;
  }
  if (hoverAnn) {
    map().removeLayer(hoverAnn.layer);
    return;
  }
  showToast("Нечего удалить");
}

export function toggleLabelsAndCoords() {
  const labels = $("opt-field-labels");
  const coords = $("opt-field-coords");
  const next = !(labels?.checked && coords?.checked);
  if (labels) labels.checked = next;
  if (coords) coords.checked = next;
  labelsOn = next;
  coordsOn = next;
}

export function setTool(name) {
  detach();
  active = name || "select";
  // #region agent log
  dbg("H5", "set-tool", { active });
  // #endregion
  document.querySelectorAll(".tool-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tool === active);
  });
  const mapArea = $("map-area");
  if (mapArea) {
    mapArea.className = mapArea.className.replace(/tool-\w+/g, "").trim();
    mapArea.classList.add(`tool-${active}`);
    if (active === "brush" || active === "eraser") mapArea.classList.add("tool-freehand");
  }
  if (["select", "ruler", "compass", "text"].includes(active)) {
    $("edit-area-controls").style.display = "none";
    $("merge-mode-panel").style.display = "none";
    $("create-area-item")?.classList.remove("active");
    $("polygon-area-item")?.classList.remove("active");
    $("edit-area-item")?.classList.remove("active");
    $("merge-menu-item")?.classList.remove("active");
  }
  const m = map();
  if (!m) return;
  if (active === "select") {
    on("click", onSelectClick, getFeatureGroup());
    on("click", onMapBlankClick);
    on("mouseover", hoverAt, getFeatureGroup());
  } else if (active === "ruler") {
    on("click", onRulerClick);
    on("mousemove", onRulerMove);
  } else if (active === "compass") {
    on("click", onCompassClick);
    on("mousemove", onCompassMove);
  } else if (active === "text") on("click", onTextClick);
  else if (active === "brush" || active === "freehand" || active === "eraser") {
    m.dragging.disable();
    on("mousedown", onBrushDown, m.getContainer());
    on("mousemove", onBrushMove, document);
    on("mouseup", onBrushUp, document);
  } else if (active === "polygon") {
    m.dragging.disable();
    m.doubleClickZoom?.disable();
    on("click", onPolygonClick);
    on("mousemove", onPolygonMove);
    on("dblclick", onPolygonDblClick);
  } else if (active === "merge") {
    on("click", onMergeClick, getFeatureGroup());
  }
}

export function activateMapTool(name) {
  setTool(name);
}

export { labelsOn, coordsOn };
