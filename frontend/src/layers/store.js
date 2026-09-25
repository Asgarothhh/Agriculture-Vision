import * as layersApi from "../api/layers.js";
import { $, confirmModal, openAppModal, closeAppModal, showToast } from "../ui.js";
import {
  addGeoJsonObject,
  clearFeatures,
  enableAoiDraw,
  fitBbox,
  getFeatureGroup,
  getMap,
  leafletToGeoJson,
} from "../map/map.js";
import { formatArea, geodesicAreaM2 } from "../map/geometry.js";

let layers = [];
let folders = [];
let objectIndex = new Map();
let selectedIds = [];

const CROP_DEFAULTS = ["Соя", "Свёкла", "Ячмень", "Пшеница", "Кукуруза", "Рапс", "Подсолнечник"];

export function getLayers() {
  return layers;
}

export function getObjectRecord(id) {
  return objectIndex.get(id);
}

export function allObjectRecords() {
  return [...objectIndex.values()];
}

export function selectedClassIds() {
  return layers.filter((l) => l.kind === "auto" && l.is_visible !== false && l.class_id != null).map((l) => l.class_id);
}

function isAuto(layer) {
  return layer.kind === "auto";
}

export async function loadMapData() {
  layers = await layersApi.listLayers();
  folders = await layersApi.listFolders();
  clearFeatures();
  objectIndex = new Map();
  for (const layer of layers) {
    if (layer.is_visible === false) continue;
    const objects = await layersApi.listLayerObjects(layer.id);
    for (const obj of objects) {
      const leaflet = addGeoJsonObject({ ...obj, layer_id: layer.id }, styleFor(layer));
      objectIndex.set(obj.id, { obj, layer, leaflet });
    }
  }
  renderLayersList();
  renderLegend();
  populateCropSelect();
}

function styleFor(layer) {
  return {
    color: layer.color || "#43A047",
    weight: Number(localStorage.getItem("ttz_line_width") || $("opt-line-width")?.value || 2),
    fillOpacity: Number(localStorage.getItem("ttz_fill_opacity") || $("opt-fill-opacity")?.value || 35) / 100,
    pointSize: Number(localStorage.getItem("ttz_point_size") || $("opt-point-size")?.value || 5),
  };
}

function objectCount() {
  return objectIndex.size;
}

function layerCountLabel(layer) {
  let n = 0;
  objectIndex.forEach((item) => {
    if (item.layer.id === layer.id) n += 1;
  });
  return n || Number(layer.objects_count || 0);
}

export function renderLayersList(filter = "") {
  const list = $("layers-list");
  const foldersBox = $("folders-list");
  if (!list) return;
  const q = (filter || $("layer-search")?.value || "").toLowerCase();
  const autoLayers = layers.filter((l) => isAuto(l) && (!q || l.name.toLowerCase().includes(q)));
  const userLayers = layers.filter((l) => !isAuto(l) && (!q || l.name.toLowerCase().includes(q)));

  if (foldersBox) {
    foldersBox.innerHTML = folders
      .map((folder) => {
        const kids = userLayers.filter((l) => l.folder_id === folder.id);
        return `
      <div class="folder-block" data-folder-id="${folder.id}">
        <div class="layer-item" data-folder-id="${folder.id}">
          <button type="button" class="mini-btn collapse-icon" data-act="toggle-folder" data-id="${folder.id}">▾</button>
          <span>📁 ${folder.name}</span>
          <div class="layer-item-actions">
            <button type="button" class="mini-btn" data-act="ren-folder" data-id="${folder.id}" title="Переименовать">✎</button>
            <button type="button" class="mini-btn" data-act="del-folder" data-id="${folder.id}" title="Удалить">✕</button>
          </div>
        </div>
        <div class="folder-children" data-folder-children="${folder.id}">
          ${kids.map((layer) => layerRow(layer, false)).join("")}
        </div>
      </div>`;
      })
      .join("");
  }

  const loose = userLayers.filter((l) => !l.folder_id);
  list.innerHTML = autoLayers.map((layer) => layerRow(layer, true)).join("");
  const userBox = $("user-layers-list");
  if (userBox) userBox.innerHTML = loose.map((layer) => layerRow(layer, false)).join("");
  if ($("layers-count-badge")) $("layers-count-badge").textContent = `${objectCount()} объектов`;
  bindLayerActions();
  populateDrawLayerSelect();
}

function layerRow(layer, locked) {
  const count = layerCountLabel(layer);
  return `
    <div class="layer-item ${layer.is_visible === false ? "off" : ""} ${locked ? "locked" : ""}" data-layer-id="${layer.id}">
      <label>
        <input type="checkbox" data-act="vis" data-id="${layer.id}" ${layer.is_visible === false ? "" : "checked"}>
        <span style="color:${layer.color}">●</span>
        <span class="layer-name">${layer.name}</span>
        ${locked ? "<small>auto</small>" : ""}
        <small class="layer-count">${count}</small>
      </label>
      <div class="layer-item-actions">
        ${locked ? "" : `<button type="button" class="mini-btn" data-act="edit-layer" data-id="${layer.id}" title="Изменить">✎</button>`}
        ${locked ? "" : `<button type="button" class="mini-btn" data-act="del-layer" data-id="${layer.id}" title="Удалить">✕</button>`}
      </div>
    </div>`;
}

function bindLayerActions() {
  document.querySelectorAll("#layers-list [data-act], #folders-list [data-act], #user-layers-list [data-act]").forEach((el) => {
    el.addEventListener("change", onLayerAction);
    el.addEventListener("click", onLayerAction);
  });
}

async function onLayerAction(event) {
  const act = event.currentTarget.getAttribute("data-act");
  const id = event.currentTarget.getAttribute("data-id");
  if (act === "vis") event.stopPropagation();
  try {
    if (act === "vis") {
      await layersApi.patchLayer(id, { is_visible: event.currentTarget.checked });
      await loadMapData();
    } else if (act === "del-layer") {
      const layer = layers.find((l) => l.id === id);
      const ok = await confirmModal({
        title: "Удалить слой",
        bodyHtml: `<p>Удалить слой «${layer?.name || ""}» со всеми объектами?</p>`,
        confirmLabel: "Удалить",
        danger: true,
      });
      if (!ok) return;
      await layersApi.deleteLayer(id);
      await loadMapData();
    } else if (act === "del-folder") {
      const folder = folders.find((f) => f.id === id);
      const ok = await confirmModal({
        title: "Удалить папку",
        bodyHtml: `<p>Удалить папку «${folder?.name || ""}»? Слои и объекты останутся на карте.</p>`,
        confirmLabel: "Удалить",
        danger: true,
      });
      if (!ok) return;
      await layersApi.deleteFolder(id);
      await loadMapData();
    } else if (act === "edit-layer") {
      const layer = layers.find((l) => l.id === id);
      openLayerModal(layer);
    } else if (act === "ren-folder") {
      const folder = folders.find((f) => f.id === id);
      openFolderModal(folder);
    } else if (act === "toggle-folder") {
      const box = document.querySelector(`[data-folder-children="${id}"]`);
      box?.classList.toggle("collapsed");
    }
  } catch (err) {
    showToast(err.message, true);
  }
}

export function filterLayers(value) {
  renderLayersList(value);
}

function folderOptions(selectedId) {
  return `<option value="">Без папки</option>${folders
    .map((f) => `<option value="${f.id}" ${f.id === selectedId ? "selected" : ""}>${f.name}</option>`)
    .join("")}`;
}

function openLayerModal(existing) {
  openAppModal({
    title: existing ? "Слой" : "Новый слой",
    bodyHtml: `
      <div class="input-group"><label>НАЗВАНИЕ</label><input id="modal-layer-name" class="search-input" value="${existing?.name || ""}"></div>
      <div class="input-group"><label>ЦВЕТ</label><input id="modal-layer-color" type="color" class="color-input" value="${existing?.color || "#3388ff"}"></div>
      <div class="input-group"><label>ПАПКА</label><select id="modal-layer-folder" class="search-input">${folderOptions(existing?.folder_id)}</select></div>
    `,
    actions: [
      { label: "Отмена", onClick: closeAppModal },
      {
        label: existing ? "Сохранить" : "Создать",
        className: "mini-btn mini-btn-red",
        onClick: async () => {
          const name = $("modal-layer-name").value.trim();
          if (!name) return;
          const color = $("modal-layer-color").value;
          const folder_id = $("modal-layer-folder").value || null;
          try {
            if (existing) await layersApi.patchLayer(existing.id, { name, color, folder_id });
            else {
              const created = await layersApi.createLayer({ name, color });
              if (folder_id && created?.id) await layersApi.patchLayer(created.id, { folder_id });
            }
            closeAppModal();
            await loadMapData();
          } catch (err) {
            showToast(err.message, true);
          }
        },
      },
    ],
  });
}

function openFolderModal(existing) {
  openAppModal({
    title: existing ? "Папка" : "Новая папка",
    bodyHtml: `<div class="input-group"><label>НАЗВАНИЕ</label><input id="modal-folder-name" class="search-input" value="${existing?.name || ""}"></div>`,
    actions: [
      { label: "Отмена", onClick: closeAppModal },
      {
        label: existing ? "Сохранить" : "Создать",
        className: "mini-btn mini-btn-red",
        onClick: async () => {
          const name = $("modal-folder-name").value.trim();
          if (!name) return;
          try {
            if (existing) await layersApi.patchFolder(existing.id, { name });
            else await layersApi.createFolder(name);
            closeAppModal();
            await loadMapData();
          } catch (err) {
            showToast(err.message, true);
          }
        },
      },
    ],
  });
}

export async function toggleCreateLayerForm() {
  openLayerModal(null);
}

export async function createFolder() {
  openFolderModal(null);
}

export function populateDrawLayerSelect() {
  const select = $("draw-layer-select");
  if (!select) return;
  select.innerHTML = layers.map((l) => `<option value="${l.id}">${l.name}</option>`).join("");
}

export function currentDrawLayerId() {
  return $("draw-layer-select")?.value || layers.find((l) => l.kind === "user")?.id || layers[0]?.id;
}

export async function persistDrawnLayer(leafletLayer, origin = "manual") {
  const layerId = currentDrawLayerId();
  if (!layerId) {
    showToast("Создайте слой для рисования", true);
    return;
  }
  const geom = leafletToGeoJson(leafletLayer);
  try {
    const created = await layersApi.addObject(layerId, { name: "", geom, origin });
    getMap()?.removeLayer(leafletLayer);
    await loadMapData();
    return created;
  } catch (err) {
    showToast(err.message, true);
  }
}

export async function patchObjectGeom(id, geom) {
  await layersApi.patchObject(id, { geom });
  await loadMapData();
}

export function highlightObjects(ids) {
  selectedIds = ids;
  objectIndex.forEach((item) => {
    item.leaflet?.eachLayer?.((part) => {
      const on = ids.includes(item.obj.id);
      part.setStyle?.({ weight: on ? 4 : styleFor(item.layer).weight, color: on ? "#e14059" : item.layer.color });
    });
  });
}

export function startCreateArea() {
  populateDrawLayerSelect();
  $("edit-area-controls").style.display = "block";
  $("merge-mode-panel").style.display = "none";
  $("more-menu")?.classList.add("active");
  $("create-area-item")?.classList.add("active");
  $("polygon-area-item")?.classList.remove("active");
  $("edit-area-item")?.classList.remove("active");
  $("merge-menu-item")?.classList.remove("active");
  import("../map/tools.js").then((mod) => {
    mod.setPaintIntent("create");
    mod.setEditDrawMode("brush");
  });
  showToast("Кисть: зажмите ЛКМ. Замкните к началу — полигон; иначе — полоса. «По точкам» — прямые по вершинам.");
}

export function startPolygonArea() {
  import("../map/tools.js").then((mod) => mod.startPolygonMode());
}

export function startAoiSelection() {
  enableAoiDraw(() => showToast("Область выделена"));
}

export function startMergePolygonsMode() {
  $("more-menu")?.classList.add("active");
  $("merge-menu-item")?.classList.add("active");
  $("create-area-item")?.classList.remove("active");
  $("polygon-area-item")?.classList.remove("active");
  $("edit-area-item")?.classList.remove("active");
  import("../map/tools.js").then((mod) => mod.startMergeMode());
}

export async function confirmMergePolygons() {
  const mod = await import("../map/tools.js");
  await mod.mergeSelectedPair();
}

export function cancelMergeMode() {
  import("../map/tools.js").then((mod) => mod.cancelMergeMode());
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

function renderLegend() {
  const el = $("legend");
  if (!el) return;
  el.innerHTML = layers
    .filter((l) => l.is_visible !== false && layerCountLabel(l) > 0)
    .map((l) => `<span class="legend-item" title="${l.name}"><i style="background:${l.color}"></i>${l.name}</span>`)
    .join("");
}

export function bindMapClicksForDetails() {
  /* selection handled by map tools */
}

export async function saveFieldName() {
  const id = $("field-name-input")?.dataset.objectId;
  if (!id) return;
  try {
    await layersApi.patchObject(id, { name: $("field-name-input").value });
    await loadMapData();
  } catch (err) {
    showToast(err.message, true);
  }
}

export function cropStorageKey() {
  return "ttz_custom_crops";
}

function customCrops() {
  try {
    return JSON.parse(localStorage.getItem(cropStorageKey()) || "[]");
  } catch {
    return [];
  }
}

export function populateCropSelect() {
  const select = $("field-crop-select");
  if (!select) return;
  const all = [...CROP_DEFAULTS, ...customCrops()];
  select.innerHTML = `<option value="">—</option>${all
    .map((c) => `<option value="${c}">${c}</option>`)
    .join("")}<option value="__custom__">⚙ Свои культуры…</option>`;
}

export function onFieldCropSelect(value) {
  if (value === "__custom__") {
    openCropsModal();
    return;
  }
  const id = $("field-name-input")?.dataset.objectId;
  if (!id) return;
  localStorage.setItem(`ttz_crop_${id}`, value);
}

function openCropsModal() {
  const list = customCrops();
  openAppModal({
    title: "Свои культуры",
    bodyHtml: `
      <div class="input-group"><input id="modal-crop-name" class="search-input" placeholder="Новая культура"></div>
      <div id="modal-crop-list">${list.map((c) => `<div class="layer-item">${c} <button type="button" class="mini-btn" data-crop="${c}">✕</button></div>`).join("")}</div>
    `,
    actions: [
      { label: "Закрыть", onClick: closeAppModal },
      {
        label: "+ Добавить культуру",
        className: "mini-btn mini-btn-red",
        onClick: () => {
          const name = $("modal-crop-name").value.trim();
          if (!name) return;
          const next = [...customCrops(), name];
          localStorage.setItem(cropStorageKey(), JSON.stringify(next));
          closeAppModal();
          populateCropSelect();
        },
      },
    ],
  });
  $("modal-crop-list")?.querySelectorAll("[data-crop]").forEach((btn) => {
    btn.onclick = () => {
      const next = customCrops().filter((c) => c !== btn.dataset.crop);
      localStorage.setItem(cropStorageKey(), JSON.stringify(next));
      btn.parentElement.remove();
    };
  });
}

export function applyDisplaySettings() {
  applyLiveStyles();
}

export function applyLiveStyles() {
  localStorage.setItem("ttz_point_size", $("opt-point-size")?.value || "5");
  localStorage.setItem("ttz_line_width", $("opt-line-width")?.value || "2");
  localStorage.setItem("ttz_fill_opacity", $("opt-fill-opacity")?.value || "35");
  localStorage.setItem("ttz_coord_color", $("opt-coord-color")?.value || "#ff3366");
  objectIndex.forEach((item) => {
    const st = styleFor(item.layer);
    item.leaflet?.eachLayer?.((part) => {
      part.setStyle?.({
        weight: st.weight,
        fillOpacity: st.fillOpacity,
        color: item.layer.color,
        radius: st.pointSize,
      });
      if (typeof part.setRadius === "function") part.setRadius(st.pointSize);
    });
  });
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
