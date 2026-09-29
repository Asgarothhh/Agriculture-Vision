// «Слои карты» sidebar, ported from the reference UI (renderLayersList / renderFoldersList /
// folder picker / object properties), on top of the server-synced model in store.js.
import { $, closeAppModal, confirmModal, escapeHtml, openAppModal, showToast } from "../ui.js";
import { logAction } from "../api/activity.js";
import {
  allObjectRecords,
  createFolderOnServer,
  createLayerOnServer,
  getFolder,
  getFolders,
  getLayer,
  getLayers,
  getObjectRecord,
  isStandardLayer,
  layerHomeFolderId,
  layerObjectCount,
  moveToFolderOnServer,
  objectFolderId,
  onViewsRefresh,
  patchFolderOnServer,
  patchLayerOnServer,
  patchObjectOnServer,
  recordsOfLayer,
  setLayerVisibility,
} from "./store.js";
import { deleteFolderTracked, deleteLayerTracked, deleteTracked, setFolderVisibility } from "./ops.js";
import { addCustomCrop, cropOptionsHtml, deleteCustomCrop, getCustomCrops } from "./crops.js";

const ICON_PLUS = `<svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2.2" fill="none"><path d="M12 5v14M5 12h14"/></svg>`;
const ICON_FOLDER = `<svg viewBox="0 0 24 24" width="15" height="15" stroke="currentColor" stroke-width="2" fill="none"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`;
const ICON_FOLDER_OUT = `<svg viewBox="0 0 24 24" width="12" height="12" stroke="currentColor" stroke-width="2" fill="none"><path d="M9 14l-4-4 4-4"/><path d="M5 10h11a4 4 0 0 1 0 8h-1"/></svg>`;

const expandedLayers = new Set();
const collapsedFolders = new Set();
let activeLayerId = null;
let selectedIds = [];
let bound = false;
let layerClickTimer = 0;
// Wait this long after a click on a layer name: a double click renames the layer instead.
const LAYER_CLICK_DELAY_MS = 250;

function searchText() {
  return ($("layer-search")?.value || "").toLowerCase();
}

/** Reference isLayerListedInSidebar: recognition categories only once they have objects. */
export function isLayerListed(layer) {
  if (!layer) return false;
  if (!isStandardLayer(layer)) return true;
  return layerObjectCount(layer) > 0;
}

/* ---------------------------------------------------------------- rendering */

function objectRow(record, { inFolderContext, tagLayer = false }) {
  const { obj, layer } = record;
  const active = selectedIds.includes(obj.id) ? " active" : "";
  const inFolder = inFolderContext || !!objectFolderId(record);
  const folderBtn = inFolder
    ? `<button class="layer-action" type="button" title="Убрать из папки" data-act="obj-out" data-id="${obj.id}">${ICON_FOLDER_OUT}</button>`
    : `<button class="layer-action layer-action-plus" type="button" title="Добавить в папку" data-act="obj-in" data-id="${obj.id}">${ICON_PLUS}</button>`;
  const name = escapeHtml(obj.name || "Объект");
  if (tagLayer) {
    return `<div class="field-item field-item-in-folder${active}" data-field-id="${obj.id}">
      <span class="color-swatch-readonly" style="background:${escapeHtml(layer.color)}" title="${escapeHtml(layer.name)}"></span>
      <span class="field-item-name" data-act="obj-select" data-id="${obj.id}"><span class="field-layer-tag">${escapeHtml(layer.name)}</span> ${name}</span>
      ${folderBtn}
      <button class="layer-action layer-action-danger" type="button" title="Удалить объект" data-act="obj-del" data-id="${obj.id}">✕</button>
    </div>`;
  }
  return `<div class="field-item${active}" data-layer-id="${layer.id}" data-field-id="${obj.id}">
    <span class="field-item-name" data-act="obj-select" data-id="${obj.id}">${name}</span>
    ${folderBtn}
    <button class="layer-action layer-action-danger" type="button" title="Удалить объект" data-act="obj-del" data-id="${obj.id}">✕</button>
  </div>`;
}

function layerRow(layer, folderContextId = null) {
  const records = recordsOfLayer(layer.id);
  const home = layerHomeFolderId(layer);
  const shown = records.filter((record) => {
    const of = objectFolderId(record);
    return folderContextId ? home === folderContextId || of === folderContextId : !of;
  });
  const expanded = expandedLayers.has(layer.id);
  const locked = isStandardLayer(layer);
  const colorControl = locked
    ? `<span class="color-swatch-readonly" style="background:${escapeHtml(layer.color)}"></span>`
    : `<input type="color" class="color-box" value="${escapeHtml(layer.color)}" data-act="color" data-id="${layer.id}">`;
  const folderBtn = folderContextId
    ? `<button class="layer-action" type="button" title="Убрать слой из папки" data-act="layer-out" data-id="${layer.id}">${ICON_FOLDER_OUT}</button>`
    : `<button class="layer-action layer-action-plus" type="button" title="Добавить слой в папку" data-act="layer-in" data-id="${layer.id}">${ICON_PLUS}</button>`;
  const renameBtn = locked
    ? ""
    : `<button class="layer-action" type="button" title="Переименовать" data-act="layer-rename" data-id="${layer.id}">✎</button>`;
  const deleteBtn = locked
    ? ""
    : `<button class="layer-action layer-action-danger" type="button" title="Удалить слой" data-act="layer-del" data-id="${layer.id}">✕</button>`;
  const fields =
    expanded && shown.length
      ? `<div class="folder-children">${shown.map((r) => objectRow(r, { inFolderContext: !!folderContextId })).join("")}</div>`
      : "";
  return `
    <div class="layer-item${layer.id === activeLayerId ? " selected" : ""}${locked ? " locked" : ""}" data-layer-id="${layer.id}">
      <button class="layer-expand" type="button" data-act="expand" data-id="${layer.id}">${expanded ? "▾" : "▸"}</button>
      <input type="checkbox" data-act="vis" data-id="${layer.id}" ${layer.is_visible === false ? "" : "checked"}>
      ${colorControl}
      <span class="layer-name" data-act="layer-active" data-id="${layer.id}">${escapeHtml(layer.name)}</span>
      <span class="layer-count">${shown.length}</span>
      <div class="layer-item-actions">${folderBtn}${renameBtn}${deleteBtn}</div>
      ${fields}
    </div>`;
}

function folderRow(folder) {
  const query = searchText();
  const kids = getLayers().filter(
    (l) => isLayerListed(l) && layerHomeFolderId(l) === folder.id && l.name.toLowerCase().includes(query),
  );
  // Objects put into the folder one by one (their layer is not wholly in it).
  const partial = allObjectRecords().filter(
    (r) => isLayerListed(r.layer) && layerHomeFolderId(r.layer) !== folder.id && objectFolderId(r) === folder.id,
  );
  const collapsed = collapsedFolders.has(folder.id);
  return `
    <div class="folder-item" data-folder-id="${folder.id}">
      <button class="folder-toggle" type="button" data-act="folder-toggle" data-id="${folder.id}">${collapsed ? "▸" : "▾"}</button>
      <input type="checkbox" data-act="folder-vis" data-id="${folder.id}" ${folder.is_visible === false ? "" : "checked"}>
      <span class="folder-icon" title="Папка">${ICON_FOLDER}</span>
      <span class="folder-name" data-act="folder-name" data-id="${folder.id}">${escapeHtml(folder.name)}</span>
      <button class="layer-action layer-action-danger" type="button" title="Удалить папку" data-act="folder-del" data-id="${folder.id}">✕</button>
      ${
        collapsed
          ? ""
          : `<div class="folder-children">${kids.map((l) => layerRow(l, folder.id)).join("")}${partial
              .map((r) => objectRow(r, { inFolderContext: true, tagLayer: true }))
              .join("")}</div>`
      }
    </div>`;
}

function pluralObjects(n) {
  return `${n} объект${n === 1 ? "" : "ов"}`;
}

export function renderLayersList() {
  const list = $("layers-list");
  if (!list) return;
  bindPanel();
  const query = searchText();
  const listed = getLayers().filter(isLayerListed);
  const total = listed.reduce((n, l) => n + layerObjectCount(l), 0);
  const root = listed.filter((l) => !layerHomeFolderId(l) && l.name.toLowerCase().includes(query));
  list.innerHTML = root.map((l) => layerRow(l)).join("");
  const foldersBox = $("folders-list");
  if (foldersBox) foldersBox.innerHTML = getFolders().map(folderRow).join("");
  if ($("layers-count-badge")) $("layers-count-badge").textContent = pluralObjects(total);
}

export function filterLayers() {
  renderLayersList();
}

/** Tools report the current selection: highlight those objects in the list (no re-render). */
function syncSelectionHighlight(ids) {
  selectedIds = ids || [];
  document.querySelectorAll("#panel-layers .field-item.active").forEach((el) => el.classList.remove("active"));
  selectedIds.forEach((id) => {
    document.querySelectorAll(`#panel-layers .field-item[data-field-id="${id}"]`).forEach((el) => el.classList.add("active"));
  });
}

/* ---------------------------------------------------------------- actions */

/** Opens a layer's object list (also after drawing a new object, as in the reference). */
export function expandLayer(id) {
  if (!id || expandedLayers.has(id)) return;
  expandedLayers.add(id);
  renderLayersList();
}

/** Objects of a layer as the row in that place of the list shows them. */
function rowRecords(layer, folderContextId) {
  const home = layerHomeFolderId(layer);
  return recordsOfLayer(layer.id).filter((record) => {
    const of = objectFolderId(record);
    return folderContextId ? home === folderContextId || of === folderContextId : !of;
  });
}

/**
 * Click on a layer name: the layer becomes active, its objects list opens and the
 * properties of one of its objects are shown (the selected one stays selected).
 */
function openLayer(layer, folderContextId) {
  selectLayerAsActive(layer.id);
  const records = rowRecords(layer, folderContextId);
  expandLayer(layer.id);
  if (!records.length) return;
  const current = records.find((r) => selectedIds.includes(r.obj.id)) || records[0];
  document.dispatchEvent(new CustomEvent("av:select-object", { detail: { id: current.obj.id, zoom: "auto" } }));
}

function selectLayerAsActive(id) {
  activeLayerId = id;
  const sel = $("draw-layer-select");
  if (sel && [...sel.options].some((o) => o.value === id)) sel.value = id;
  document.querySelectorAll("#panel-layers .layer-item.selected").forEach((el) => el.classList.remove("selected"));
  document.querySelectorAll(`#panel-layers .layer-item[data-layer-id="${id}"]`).forEach((el) => el.classList.add("selected"));
}

function openFolderPicker(title, onPick) {
  const panel = $("folder-picker");
  const list = $("folder-picker-list");
  if (!panel || !list) return;
  if ($("folder-picker-title")) $("folder-picker-title").textContent = title || "Выберите папку";
  list.innerHTML = [
    '<button type="button" class="folder-picker-item" data-id="">— Без папки —</button>',
    ...getFolders().map(
      (f) => `<button type="button" class="folder-picker-item" data-id="${f.id}">${escapeHtml(f.name)}</button>`,
    ),
  ].join("");
  list.querySelectorAll(".folder-picker-item").forEach((btn) => {
    btn.onclick = () => {
      closeFolderPicker();
      onPick(btn.getAttribute("data-id") || null);
    };
  });
  panel.style.display = "flex";
}

export function closeFolderPicker() {
  const panel = $("folder-picker");
  if (panel) panel.style.display = "none";
}

async function assignLayerToFolder(layer) {
  if (!getFolders().length) {
    showToast("Сначала создайте папку", true);
    return;
  }
  openFolderPicker("Папка для слоя", async (folderId) => {
    try {
      if (folderId) await moveToFolderOnServer({ layerId: layer.id, folderId });
      else await removeLayerFromFolder(layer, { silent: true });
      showToast(folderId ? "Слой добавлен в папку" : "Слой убран из папки");
    } catch (err) {
      showToast(err.message, true);
    }
  });
}

/** Out of the folder: the layer and every object of it (reference removeLayerFromFolder). */
async function removeLayerFromFolder(layer, { silent = false } = {}) {
  if (layer.folder_id) await moveToFolderOnServer({ layerId: layer.id, folderId: null, fromFolderId: layer.folder_id });
  for (const record of recordsOfLayer(layer.id)) {
    if (record.obj.folder_id) {
      await moveToFolderOnServer({ objectId: record.obj.id, folderId: null, fromFolderId: record.obj.folder_id });
    }
  }
  if (!silent) showToast("Слой убран из папки");
}

/**
 * One object into / out of a folder. When its whole layer sits in a folder, the other
 * objects keep that folder object by object first, so only this one moves.
 */
async function assignObjectToFolder(record, folderId) {
  const layer = record.layer;
  if (layer.folder_id) {
    const layerFolder = layer.folder_id;
    for (const other of recordsOfLayer(layer.id)) {
      if (other.obj.id !== record.obj.id && !other.obj.folder_id) {
        await moveToFolderOnServer({ objectId: other.obj.id, folderId: layerFolder });
      }
    }
    await moveToFolderOnServer({ layerId: layer.id, folderId: null, fromFolderId: layerFolder });
    if (!folderId && record.obj.folder_id) {
      await moveToFolderOnServer({ objectId: record.obj.id, folderId: null, fromFolderId: record.obj.folder_id });
    }
  }
  if (folderId) await moveToFolderOnServer({ objectId: record.obj.id, folderId });
  else if (record.obj.folder_id) {
    await moveToFolderOnServer({ objectId: record.obj.id, folderId: null, fromFolderId: record.obj.folder_id });
  }
  showToast(folderId ? "Объект добавлен в папку (слой закреплён)" : "Объект убран из папки");
}

function pickFolderForObject(record) {
  if (!getFolders().length) {
    showToast("Сначала создайте папку", true);
    return;
  }
  openFolderPicker("Папка для объекта", (folderId) =>
    assignObjectToFolder(record, folderId).catch((err) => showToast(err.message, true)),
  );
}

async function deleteObjectFromList(record) {
  const ok = await confirmModal({
    title: "Удалить объект?",
    bodyHtml: `<p>Удалить «${escapeHtml(record.obj.name || "объект")}»? Действие можно отменить (Ctrl+Z).</p>`,
    confirmLabel: "Удалить",
    danger: true,
  });
  if (!ok) return;
  await deleteTracked([record]);
  showToast("Объект удалён");
}

function nameModal({ title, label = "Название", value = "", placeholder = "", confirmLabel, onSave }) {
  openAppModal({
    title,
    bodyHtml: `<label class="modal-label" for="modal-name-input">${escapeHtml(label)}</label>
      <input type="text" id="modal-name-input" class="search-input modal-input" maxlength="255"
        value="${escapeHtml(value)}" placeholder="${escapeHtml(placeholder)}">`,
    actions: [
      {
        label: confirmLabel,
        className: "mini-btn mini-btn-red",
        onClick: async () => {
          const next = $("modal-name-input")?.value.trim();
          if (!next) return;
          closeAppModal();
          try {
            await onSave(next);
          } catch (err) {
            showToast(err.message, true);
          }
        },
      },
      { label: "Отмена", className: "mini-btn", onClick: closeAppModal },
    ],
  });
  const input = $("modal-name-input");
  input?.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      document.querySelector("#app-modal-actions .mini-btn-red")?.click();
    }
  });
  setTimeout(() => input?.focus(), 30);
}

export function toggleCreateLayerForm() {
  const folderOptions = getFolders()
    .map((f) => `<option value="${f.id}">${escapeHtml(f.name)}</option>`)
    .join("");
  openAppModal({
    title: "Новый слой",
    bodyHtml: `<label class="modal-label" for="modal-layer-name">Название</label>
      <input type="text" id="modal-layer-name" class="search-input modal-input" placeholder="Название слоя" maxlength="255">
      <label class="modal-label" for="modal-layer-color">Цвет</label>
      <input type="color" id="modal-layer-color" value="#3388ff" class="color-input modal-input">
      <label class="modal-label" for="modal-layer-folder">Папка</label>
      <select id="modal-layer-folder" class="search-input modal-input">
        <option value="">— Без папки —</option>${folderOptions}
      </select>`,
    actions: [
      {
        label: "Создать",
        className: "mini-btn mini-btn-red",
        onClick: async () => {
          const name = $("modal-layer-name")?.value.trim();
          if (!name) return;
          const color = $("modal-layer-color")?.value || "#3388ff";
          const folderId = $("modal-layer-folder")?.value || null;
          closeAppModal();
          try {
            const layer = await createLayerOnServer({ name, color, folderId });
            selectLayerAsActive(layer.id);
            const folder = folderId ? getFolder(folderId) : null;
            showToast(folder ? `Слой «${name}» создан в папке «${folder.name}»` : `Слой «${name}» создан`);
          } catch (err) {
            showToast(err.message, true);
          }
        },
      },
      { label: "Отмена", className: "mini-btn", onClick: closeAppModal },
    ],
  });
  setTimeout(() => $("modal-layer-name")?.focus(), 30);
}

export function createFolder() {
  nameModal({
    title: "Новая папка",
    placeholder: "Например: Поле Север",
    confirmLabel: "Создать",
    onSave: async (name) => {
      await createFolderOnServer(name);
      showToast("Папка создана");
    },
  });
}

function renameLayer(layer) {
  if (isStandardLayer(layer)) {
    showToast("Стандартные слои нельзя переименовывать", true);
    return;
  }
  nameModal({
    title: "Переименовать слой",
    value: layer.name,
    confirmLabel: "Сохранить",
    onSave: async (name) => {
      await patchLayerOnServer(layer.id, { name });
      logAction("tool", `Переименован слой «${name}»`);
    },
  });
}

function renameFolder(folder) {
  nameModal({
    title: "Переименовать папку",
    value: folder.name,
    confirmLabel: "Сохранить",
    onSave: async (name) => {
      await patchFolderOnServer(folder.id, { name });
      showToast("Папка переименована");
    },
  });
}

async function deleteLayer(layer) {
  if (isStandardLayer(layer)) {
    showToast("Стандартные слои нельзя удалять", true);
    return;
  }
  const ok = await confirmModal({
    title: "Удалить слой?",
    bodyHtml: `<p>Удалить слой «${escapeHtml(layer.name)}» со всеми объектами?</p>`,
    confirmLabel: "Удалить",
    danger: true,
  });
  if (!ok) return;
  await deleteLayerTracked(layer.id);
  if (activeLayerId === layer.id) activeLayerId = null;
  showToast("Слой удалён — можно вернуть кнопкой «Отменить»");
}

async function deleteFolder(folder) {
  const ok = await confirmModal({
    title: "Удалить папку?",
    bodyHtml: `<p>Удалить папку «${escapeHtml(folder.name)}»? Слои и объекты останутся на карте.</p>`,
    confirmLabel: "Удалить",
    danger: true,
  });
  if (!ok) return;
  await deleteFolderTracked(folder.id);
  showToast("Папка удалена — можно вернуть кнопкой «Отменить»");
}

async function changeLayerColor(layer, color) {
  if (isStandardLayer(layer)) {
    showToast("Цвет стандартных слоёв нельзя менять", true);
    return;
  }
  await patchLayerOnServer(layer.id, { color });
  logAction("tool", `Изменён цвет слоя «${layer.name}»`);
}

async function onPanelClick(event) {
  const el = event.target.closest("[data-act]");
  if (!el || !$("panel-layers")?.contains(el)) return;
  const act = el.dataset.act;
  const id = el.dataset.id;
  if (["vis", "folder-vis", "color"].includes(act)) return; // handled on change
  event.stopPropagation();
  const layer = getLayer(id);
  const record = getObjectRecord(id);
  const folder = getFolder(id);
  try {
    if (act === "expand") {
      if (expandedLayers.has(id)) expandedLayers.delete(id);
      else expandedLayers.add(id);
      renderLayersList();
    } else if (act === "layer-active" && layer) {
      const folderContextId = el.closest(".folder-item")?.dataset.folderId || null;
      clearTimeout(layerClickTimer);
      layerClickTimer = setTimeout(() => openLayer(layer, folderContextId), LAYER_CLICK_DELAY_MS);
    }
    else if (act === "layer-in" && layer) await assignLayerToFolder(layer);
    else if (act === "layer-out" && layer) await removeLayerFromFolder(layer);
    else if (act === "layer-rename" && layer) renameLayer(layer);
    else if (act === "layer-del" && layer) await deleteLayer(layer);
    else if (act === "obj-select" && record) {
      document.dispatchEvent(new CustomEvent("av:select-object", { detail: { id, zoom: true } }));
    } else if (act === "obj-in" && record) pickFolderForObject(record);
    else if (act === "obj-out" && record) await assignObjectToFolder(record, null);
    else if (act === "obj-del" && record) await deleteObjectFromList(record);
    else if (act === "folder-toggle") {
      if (collapsedFolders.has(id)) collapsedFolders.delete(id);
      else collapsedFolders.add(id);
      renderLayersList();
    } else if (act === "folder-del" && folder) await deleteFolder(folder);
  } catch (err) {
    showToast(err.message, true);
  }
}

function onPanelDblClick(event) {
  const el = event.target.closest("[data-act]");
  if (!el) return;
  if (el.dataset.act === "layer-active") {
    clearTimeout(layerClickTimer);
    const layer = getLayer(el.dataset.id);
    if (layer && !isStandardLayer(layer)) renameLayer(layer);
  } else if (el.dataset.act === "folder-name") {
    const folder = getFolder(el.dataset.id);
    if (folder) renameFolder(folder);
  }
}

async function onPanelChange(event) {
  const el = event.target.closest("[data-act]");
  if (!el) return;
  const id = el.dataset.id;
  try {
    if (el.dataset.act === "vis") await setLayerVisibility(id, el.checked);
    else if (el.dataset.act === "folder-vis") await setFolderVisibility(id, el.checked);
    else if (el.dataset.act === "color") {
      const layer = getLayer(id);
      if (layer) await changeLayerColor(layer, el.value);
    }
  } catch (err) {
    showToast(err.message, true);
  }
}

/* ---------------------------------------------------------------- object properties */

/** Name is saved when the field loses focus / Enter (reference saveFieldName). */
export async function saveFieldName() {
  const input = $("field-name-input");
  const id = input?.dataset.objectId;
  if (!id) return;
  const name = input.value.trim();
  const record = getObjectRecord(id);
  if (!name || !record || name === record.obj.name) return;
  try {
    await patchObjectOnServer(id, { name });
    showToast("Название поля сохранено");
  } catch (err) {
    showToast(err.message, true);
  }
}

export function populateCropSelect(current) {
  const select = $("field-crop-select");
  if (!select) return;
  select.innerHTML = cropOptionsHtml(current || "");
  select.value = current || "";
}

/** Crop is applied at once to the selected object (PATCH crop). */
export async function onFieldCropSelect(value) {
  const id = $("field-name-input")?.dataset.objectId;
  const record = id ? getObjectRecord(id) : null;
  if (value === "__manage__") {
    populateCropSelect(record?.obj.crop);
    openManageCustomCropsModal();
    return;
  }
  if (!record) return;
  try {
    await patchObjectOnServer(id, { crop: value || null });
    showToast(value ? `Культура: ${value}` : "Культура сброшена");
  } catch (err) {
    populateCropSelect(record.obj.crop);
    showToast(err.message, true);
  }
}

function currentFieldCrop() {
  const id = $("field-name-input")?.dataset.objectId;
  return (id && getObjectRecord(id)?.obj.crop) || "";
}

function refreshModalCustomCropList() {
  const list = $("modal-custom-crop-list");
  if (!list) return;
  const customs = Object.entries(getCustomCrops());
  if (!customs.length) {
    list.innerHTML = '<div class="modal-hint-muted">Своих культур пока нет</div>';
    return;
  }
  list.innerHTML = customs
    .map(
      ([key, label]) => `<div class="custom-crop-row">
        <span>${escapeHtml(label)}</span>
        <button type="button" class="layer-action layer-action-danger" data-del-crop="${escapeHtml(key)}" title="Удалить">✕</button>
      </div>`,
    )
    .join("");
  list.querySelectorAll("[data-del-crop]").forEach((btn) => {
    btn.onclick = () => {
      deleteCustomCrop(btn.getAttribute("data-del-crop"));
      refreshModalCustomCropList();
      populateCropSelect(currentFieldCrop());
      showToast("Своя культура удалена");
    };
  });
}

/** Only the list of own crops (add / delete); the crop itself is chosen in the properties. */
export function openManageCustomCropsModal() {
  openAppModal({
    title: "Свои культуры",
    bodyHtml: `<label class="modal-label" for="modal-custom-crop-name">Своя культура (*)</label>
      <input type="text" id="modal-custom-crop-name" class="search-input modal-input" placeholder="Название новой культуры" maxlength="120">
      <button type="button" class="mini-btn mini-btn-blue modal-btn-block" id="modal-add-custom-crop">+ Добавить культуру</button>
      <div id="modal-custom-crop-list" class="custom-crop-list"></div>`,
    actions: [
      {
        label: "Готово",
        className: "mini-btn mini-btn-red",
        onClick: () => {
          closeAppModal();
          populateCropSelect(currentFieldCrop());
        },
      },
    ],
  });
  const add = () => {
    const input = $("modal-custom-crop-name");
    const name = addCustomCrop(input?.value);
    if (!name) {
      input?.focus();
      return;
    }
    if (input) input.value = "";
    refreshModalCustomCropList();
    populateCropSelect(currentFieldCrop());
    showToast("Своя культура добавлена");
  };
  $("modal-add-custom-crop")?.addEventListener("click", add);
  $("modal-custom-crop-name")?.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      add();
    }
  });
  refreshModalCustomCropList();
}

/* ---------------------------------------------------------------- wiring */

function bindPanel() {
  if (bound) return;
  const panel = $("panel-layers");
  if (!panel) return;
  bound = true;
  panel.addEventListener("click", onPanelClick);
  panel.addEventListener("dblclick", onPanelDblClick);
  panel.addEventListener("change", onPanelChange);
  document.addEventListener("av:selection", (e) => syncSelectionHighlight(e.detail?.ids));
}

export function initLayersPanel() {
  bindPanel();
  onViewsRefresh(renderLayersList);
  renderLayersList();
}
