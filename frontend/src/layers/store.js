import * as layersApi from "../api/layers.js";
import { $, showToast } from "../ui.js";
import {
  addGeoJsonObject,
  clearFeatures,
  enableAoiDraw,
  fitBbox,
  getFeatureGroup,
  getMap,
  leafletToGeoJson,
} from "../map/map.js";

let layers = [];
let folders = [];
let selectedIds = [];
let objectIndex = new Map();

export function getLayers() {
  return layers;
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
    const objects = await layersApi.listLayerObjects(layer.id);
    for (const obj of objects) {
      const leaflet = addGeoJsonObject({ ...obj, layer_id: layer.id }, styleFor(layer));
      objectIndex.set(obj.id, { obj, layer, leaflet });
    }
  }
  renderLayersList();
  renderLegend();
}

function styleFor(layer) {
  return {
    color: layer.color || "#43A047",
    weight: Number($("opt-line-width")?.value || 2),
    fillOpacity: Number($("opt-fill-opacity")?.value || 35) / 100,
    pointSize: Number($("opt-point-size")?.value || 5),
  };
}

function polygonCount() {
  return [...objectIndex.values()].filter((item) => !item.obj.is_point).length;
}

export function renderLayersList(filter = "") {
  const list = $("layers-list");
  const foldersBox = $("folders-list");
  if (!list) return;
  const q = (filter || $("layer-search")?.value || "").toLowerCase();
  foldersBox.innerHTML = folders
    .map(
      (folder) => `
      <div class="layer-item" data-folder-id="${folder.id}">
        <span>📁 ${folder.name}</span>
        <button type="button" class="mini-btn" data-act="del-folder" data-id="${folder.id}">×</button>
      </div>`,
    )
    .join("");
  const visible = layers.filter((layer) => !q || layer.name.toLowerCase().includes(q));
  list.innerHTML = visible
    .map((layer) => {
      const locked = isAuto(layer);
      return `
      <div class="layer-item ${layer.is_visible === false ? "off" : ""}" data-layer-id="${layer.id}">
        <label>
          <input type="checkbox" data-act="vis" data-id="${layer.id}" ${layer.is_visible === false ? "" : "checked"}>
          <span style="color:${layer.color}">●</span> ${layer.name}
          ${locked ? "<small>auto</small>" : ""}
        </label>
        ${locked ? "" : `<button type="button" class="mini-btn" data-act="del-layer" data-id="${layer.id}">×</button>`}
      </div>`;
    })
    .join("");
  if ($("layers-count-badge")) $("layers-count-badge").textContent = `${polygonCount()} полигонов`;
  bindLayerActions();
  populateDrawLayerSelect();
}

function bindLayerActions() {
  $("layers-list")?.querySelectorAll("[data-act]").forEach((el) => {
    el.addEventListener("change", onLayerAction);
    el.addEventListener("click", onLayerAction);
  });
  $("folders-list")?.querySelectorAll("[data-act]").forEach((el) => {
    el.addEventListener("click", onLayerAction);
  });
}

async function onLayerAction(event) {
  const act = event.currentTarget.getAttribute("data-act");
  const id = event.currentTarget.getAttribute("data-id");
  try {
    if (act === "vis") {
      await layersApi.patchLayer(id, { is_visible: event.currentTarget.checked });
      await loadMapData();
    } else if (act === "del-layer") {
      await layersApi.deleteLayer(id);
      await loadMapData();
    } else if (act === "del-folder") {
      await layersApi.deleteFolder(id);
      await loadMapData();
    }
  } catch (err) {
    showToast(err.message, true);
  }
}

export function filterLayers(value) {
  renderLayersList(value);
}

export async function toggleCreateLayerForm() {
  const name = window.prompt("Имя слоя");
  if (!name) return;
  try {
    await layersApi.createLayer({ name, color: "#2E7D32" });
    await loadMapData();
  } catch (err) {
    showToast(err.message, true);
  }
}

export async function createFolder() {
  const name = window.prompt("Имя папки");
  if (!name) return;
  try {
    await layersApi.createFolder(name);
    await loadMapData();
  } catch (err) {
    showToast(err.message, true);
  }
}

export function populateDrawLayerSelect() {
  const select = $("draw-layer-select");
  if (!select) return;
  const drawable = layers.filter((l) => l.kind !== "auto" || true);
  select.innerHTML = layers
    .map((l) => `<option value="${l.id}">${l.name}</option>`)
    .join("");
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
    getMap().removeLayer(leafletLayer);
    await loadMapData();
    return created;
  } catch (err) {
    showToast(err.message, true);
  }
}

export function startCreateArea() {
  const map = getMap();
  const drawer = new L.Draw.Polygon(map, { allowIntersection: false, showArea: true });
  drawer.enable();
  map.once(L.Draw.Event.CREATED, async (e) => {
    await persistDrawnLayer(e.layer);
  });
}

export function startAoiSelection() {
  enableAoiDraw(() => showToast("Область выделена"));
}

let mergePicks = [];

export function startMergePolygonsMode() {
  mergePicks = [];
  $("merge-mode-panel").style.display = "block";
  $("merge-mode-hint").textContent = "Выбрано: 0 из 2";
  const group = getFeatureGroup();
  group.eachLayer((layer) => {
    layer.on("click", onMergeClick);
  });
}

function onMergeClick(e) {
  L.DomEvent.stop(e);
  const part = e.target;
  const obj = part.avObject;
  if (!obj) return;
  if (mergePicks.find((item) => item.id === obj.id)) return;
  if (mergePicks.length && mergePicks[0].layer_id !== obj.layer_id) {
    showToast("Объединять можно только области одного слоя", true);
    return;
  }
  if (mergePicks.length >= 2) {
    showToast("За раз можно объединить только 2 области", true);
    return;
  }
  mergePicks.push(obj);
  $("merge-mode-hint").textContent = `Выбрано: ${mergePicks.length} из 2`;
  $("merge-confirm-btn").disabled = mergePicks.length < 2;
}

export async function confirmMergePolygons() {
  if (mergePicks.length < 2) return;
  try {
    await layersApi.mergeObjects(mergePicks.map((o) => o.id));
    showToast("Объекты объединены");
    cancelMergeMode();
    await loadMapData();
  } catch (err) {
    showToast(err.message, true);
  }
}

export function cancelMergeMode() {
  mergePicks = [];
  $("merge-mode-panel").style.display = "none";
  $("merge-confirm-btn").disabled = true;
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
    .filter((l) => l.is_visible !== false)
    .map((l) => `<span class="legend-item"><i style="background:${l.color}"></i>${l.name}</span>`)
    .join("");
}

export function bindMapClicksForDetails() {
  getFeatureGroup().on("click", async (e) => {
    const obj = e.layer?.avObject;
    if (!obj) return;
    try {
      const fresh = await layersApi.getObject(obj.id);
      $("field-detail-panel").style.display = "block";
      $("field-name-input").value = fresh.name || "";
      $("field-name-input").dataset.objectId = fresh.id;
      $("field-area-value").textContent = fresh.unit ? `${fresh.area} ${fresh.unit}` : "—";
    } catch (err) {
      showToast(err.message, true);
    }
  });
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
