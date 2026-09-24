import "./styles/style.css";
import { getAccessToken } from "./api/client.js";
import {
  handleLogin,
  handleLogout,
  handleRegister,
  openForgotPasswordModal,
  restoreSession,
  setAuthCallbacks,
  toggleMode,
} from "./auth/session.js";
import { bindPasswordToggles, closeAppModal, $, showToast } from "./ui.js";
import {
  bindMapClicksForDetails,
  cancelMergeMode,
  confirmMergePolygons,
  createFolder,
  filterLayers,
  importLayerFile,
  loadMapData,
  saveFieldName,
  startAoiSelection,
  startCreateArea,
  startMergePolygonsMode,
  toggleCreateLayerForm,
} from "./layers/store.js";
import { clearAoi, initMap, setBasemap } from "./map/map.js";
import { activateMapTool } from "./map/tools.js";
import {
  handleUploadFile,
  onSegArchitectureChange,
  onSegThresholdInput,
  refreshMlHealth,
  runSegmentation,
  startUploadProcessing,
} from "./tasks/runner.js";
import {
  disconnectDzz,
  goToDzzTileFromForm,
  loadWmtsCatalog,
  onBasemapSelectChange,
  startDzzPolling,
  stopDzzPolling,
  testDzzAccess,
} from "./dzz/panel.js";
import { exportLayers } from "./export/download.js";
import { deleteAccount, renderHistoryFeed, saveProfile } from "./account/profile.js";

function switchSidebar(name) {
  document.querySelectorAll(".sidebar-icons .icon-btn[data-panel]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.panel === name);
  });
  document.querySelectorAll(".panel-content").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `panel-${name}`);
  });
}

function switchMainTab(name) {
  $("view-map").style.display = name === "map" ? "flex" : "none";
  $("view-account").style.display = name === "account" ? "flex" : "none";
  $("view-map").classList.toggle("active", name === "map");
  $("view-account").classList.toggle("active", name === "account");
  if (name === "account") renderHistoryFeed();
  if (name === "map") setTimeout(() => initMap().invalidateSize(), 50);
}

function toggleSidebarPanel() {
  $("sidebar-panel-wrap")?.classList.toggle("collapsed");
}

function toggleSegPanel() {
  $("map-seg-panel")?.classList.toggle("collapsed");
}

function toggleMoreMenu(event) {
  event?.stopPropagation();
  $("more-menu")?.classList.toggle("active");
  positionMoreMenu();
}

function positionMoreMenu() {
  const menu = $("more-menu");
  const stack = document.querySelector(".map-right-stack");
  if (!menu || !stack || !menu.classList.contains("active")) return;
  const box = stack.getBoundingClientRect();
  menu.style.top = `${Math.max(12, box.top)}px`;
  menu.style.right = `${Math.max(12, window.innerWidth - box.left + 10)}px`;
  menu.style.left = "auto";
}

function setTool(name) {
  document.querySelectorAll(".tool-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tool === name);
  });
  const mapArea = $("map-area");
  if (mapArea) {
    mapArea.classList.remove("tool-select", "tool-ruler", "tool-compass", "tool-text", "tool-freehand", "tool-brush", "tool-eraser");
    if (name) mapArea.classList.add(`tool-${name}`);
  }
  activateMapTool(name);
}

window.addEventListener("resize", positionMoreMenu);

function toggleHistoryFilterMenu() {
  const menu = $("history-filter-menu");
  menu.style.display = menu.style.display === "none" ? "block" : "none";
}

function toggleHistoryFilterAll(checked) {
  document.querySelectorAll(".history-filter-cat").forEach((el) => {
    el.checked = checked;
  });
  renderHistoryFeed();
}

function onHistoryFilterCatChange() {
  const cats = [...document.querySelectorAll(".history-filter-cat")];
  $("history-filter-all").checked = cats.every((el) => el.checked);
  renderHistoryFeed();
}

async function onAppReady() {
  initMap();
  await loadMapData();
  bindMapClicksForDetails();
  await refreshMlHealth();
  startDzzPolling();
  const savedArch = localStorage.getItem("ttz_ml_architecture");
  if (savedArch) {
    const radio = document.querySelector(`input[name="seg-architecture"][value="${savedArch}"]`);
    if (radio) radio.checked = true;
  }
  const savedThr = localStorage.getItem("ttz_seg_threshold");
  if (savedThr && $("seg-threshold")) {
    $("seg-threshold").value = savedThr;
    $("seg-threshold-value").innerText = `${savedThr}%`;
  }
}

function onAppLogout() {
  stopDzzPolling();
}

setAuthCallbacks({ ready: onAppReady, logout: onAppLogout });

function closeFolderPicker() {
  $("folder-picker").style.display = "none";
}

function saveSettings() {
  const value = $("opt-basemap")?.value;
  if (value && value !== "custom") setBasemap(value);
  showToast("Настройки сохранены");
}

function undoLast() {
  showToast("Отмена: правки сохраняются на сервере");
}

function redoLast() {}

function openEditAreaMode() {
  $("edit-area-controls").style.display = "block";
  $("more-menu")?.classList.add("active");
  positionMoreMenu();
  setEditDrawMode("brush");
}

function finishEditAreaMode() {
  $("edit-area-controls").style.display = "none";
  $("map-area")?.classList.remove("tool-freehand", "tool-brush", "tool-eraser");
  activateMapTool("select");
}

function setEditDrawMode(mode) {
  $("edit-brush-btn")?.classList.toggle("active", mode === "brush");
  $("edit-eraser-btn")?.classList.toggle("active", mode === "eraser");
  const mapArea = $("map-area");
  mapArea?.classList.add("tool-freehand");
  mapArea?.classList.toggle("tool-brush", mode === "brush");
  mapArea?.classList.toggle("tool-eraser", mode === "eraser");
  activateMapTool(mode);
}
function onDrawLayerSelect() {}
function toggleLayerGroup(id) {
  $(id)?.classList.toggle("collapsed");
}
function toggleFieldDetailPanel() {
  $("field-detail-body")?.classList.toggle("collapsed");
}
function setMapDisplayOption() {}
function onFieldCropSelect() {}
function setDzzTileGrid() {}
function toggleDzzTileGrid() {}
function shiftDzzTile(dx, dy) {
  const source = $("dzz-bar-z") ? "bar" : "opt";
  const zEl = $(source === "bar" ? "dzz-bar-z" : "opt-dzz-tile-z");
  const xEl = $(source === "bar" ? "dzz-bar-x" : "opt-dzz-tile-x");
  const yEl = $(source === "bar" ? "dzz-bar-y" : "opt-dzz-tile-y");
  if (!xEl || !yEl) return;
  xEl.value = String(Number(xEl.value || 0) + dx);
  yEl.value = String(Number(yEl.value || 0) + dy);
  if (zEl && !zEl.value) zEl.value = "8";
  goToDzzTileFromForm(source);
}
function setDzzDockMode(mode) {
  $("dzz-sites-pane").hidden = mode !== "sites";
  $("dzz-tiles-pane").hidden = mode !== "tiles";
}
function toggleDzzDock() {
  $("dzz-sites-bar")?.classList.toggle("open");
}
function applyWmtsSelection() {}
function onWmtsLayerChange() {}
function onWmtsMatrixChange() {}
function handleAvatarFile() {}

function bindUi() {
  $("loginForm")?.addEventListener("submit", handleLogin);
  $("registerForm")?.addEventListener("submit", handleRegister);
  $("forgot-password-link")?.addEventListener("click", (event) => {
    event.preventDefault();
    openForgotPasswordModal();
  });
  $("switch-to-register")?.addEventListener("click", (event) => {
    event.preventDefault();
    toggleMode("register");
  });
  $("switch-to-login")?.addEventListener("click", (event) => {
    event.preventDefault();
    toggleMode("login");
  });
  document.querySelectorAll(".link-red").forEach((el) => {
    el.addEventListener("click", (event) => event.preventDefault());
  });
  document.querySelector(".topbar-logout")?.addEventListener("click", handleLogout);
  $("sidebar-account-btn")?.addEventListener("click", () => switchMainTab("account"));
  $("account-back-btn")?.addEventListener("click", () => switchMainTab("map"));
  document.querySelectorAll(".sidebar-icons .icon-btn[data-panel]").forEach((btn) => {
    btn.addEventListener("click", () => switchSidebar(btn.dataset.panel));
  });
  $("layer-search")?.addEventListener("input", (event) => filterLayers(event.target.value));
  $("create-layer-btn")?.addEventListener("click", toggleCreateLayerForm);
  $("create-folder-btn")?.addEventListener("click", createFolder);
  document.querySelector(".layer-group-toggle")?.addEventListener("click", () => toggleLayerGroup("categories-group"));
  $("opt-field-labels")?.addEventListener("change", (event) => setMapDisplayOption("labels", event.target.checked));
  $("opt-field-coords")?.addEventListener("change", (event) => setMapDisplayOption("coords", event.target.checked));
  document.querySelector(".field-detail-header")?.addEventListener("click", toggleFieldDetailPanel);
  $("field-name-input")?.addEventListener("change", saveFieldName);
  $("field-crop-select")?.addEventListener("change", (event) => onFieldCropSelect(event.target.value));
  $("import-file-input")?.addEventListener("change", (event) => importLayerFile(event.target.files?.[0]));
  $("upload-file-input")?.addEventListener("change", (event) => handleUploadFile(event.target.files?.[0]));
  $("upload-process-btn")?.addEventListener("click", startUploadProcessing);
  $("opt-point-size")?.addEventListener("input", (event) => {
    $("point-size-value").innerText = event.target.value;
  });
  $("opt-line-width")?.addEventListener("input", (event) => {
    $("line-width-value").innerText = event.target.value;
  });
  $("opt-fill-opacity")?.addEventListener("input", (event) => {
    $("fill-opacity-value").innerText = event.target.value;
  });
  $("opt-basemap")?.addEventListener("change", (event) => onBasemapSelectChange(event.target.value));
  $("dzz-test-btn")?.addEventListener("click", testDzzAccess);
  $("dzz-logout-btn")?.addEventListener("click", disconnectDzz);
  $("dzz-wmts-load-btn")?.addEventListener("click", () => loadWmtsCatalog("dzz"));
  $("dzz-wmts-apply-btn")?.addEventListener("click", () => applyWmtsSelection("dzz"));
  $("opt-dzz-wmts-layer")?.addEventListener("change", () => onWmtsLayerChange("dzz"));
  $("opt-dzz-wmts-matrix")?.addEventListener("change", () => onWmtsMatrixChange("dzz"));
  $("dzz-tile-go-opt")?.addEventListener("click", () => goToDzzTileFromForm("opt"));
  $("dzz-tile-go-bar")?.addEventListener("click", () => goToDzzTileFromForm("bar"));
  $("opt-dzz-tile-grid")?.addEventListener("change", (event) => setDzzTileGrid(event.target.checked));
  $("custom-wmts-load-btn")?.addEventListener("click", () => loadWmtsCatalog("custom"));
  $("custom-wmts-apply-btn")?.addEventListener("click", () => applyWmtsSelection("custom"));
  $("opt-custom-wmts-layer")?.addEventListener("change", () => onWmtsLayerChange("custom"));
  $("opt-custom-wmts-matrix")?.addEventListener("change", () => onWmtsMatrixChange("custom"));
  $("save-settings-btn")?.addEventListener("click", saveSettings);
  $("export-btn")?.addEventListener("click", exportLayers);
  $("sidebar-edge-toggle")?.addEventListener("click", toggleSidebarPanel);
  $("undo-btn")?.addEventListener("click", undoLast);
  $("redo-btn")?.addEventListener("click", redoLast);
  $("seg-panel-toggle")?.addEventListener("click", toggleSegPanel);
  $("map-btn-aoi")?.addEventListener("click", startAoiSelection);
  $("map-btn-clear-aoi")?.addEventListener("click", clearAoi);
  document.querySelectorAll('input[name="seg-architecture"]').forEach((el) => {
    el.addEventListener("change", onSegArchitectureChange);
  });
  $("seg-threshold")?.addEventListener("input", (event) => onSegThresholdInput(event.target.value));
  $("btn-segment-yolo")?.addEventListener("click", () => runSegmentation("yolo"));
  $("btn-segment-segformer")?.addEventListener("click", () => runSegmentation("segformer"));
  document.querySelectorAll(".tool-btn[data-tool]").forEach((btn) => {
    btn.addEventListener("click", () => setTool(btn.dataset.tool));
  });
  $("tool-more-btn")?.addEventListener("click", toggleMoreMenu);
  $("more-menu-toggle")?.addEventListener("click", toggleMoreMenu);
  $("create-area-item")?.addEventListener("click", startCreateArea);
  $("edit-area-item")?.addEventListener("click", openEditAreaMode);
  $("merge-menu-item")?.addEventListener("click", startMergePolygonsMode);
  $("merge-confirm-btn")?.addEventListener("click", confirmMergePolygons);
  $("merge-cancel-btn")?.addEventListener("click", cancelMergeMode);
  $("draw-layer-select")?.addEventListener("change", (event) => onDrawLayerSelect(event.target.value));
  $("edit-brush-btn")?.addEventListener("click", () => setEditDrawMode("brush"));
  $("edit-eraser-btn")?.addEventListener("click", () => setEditDrawMode("eraser"));
  $("brush-size")?.addEventListener("input", (event) => {
    $("brush-size-value").innerText = event.target.value;
  });
  $("finish-edit-btn")?.addEventListener("click", finishEditAreaMode);
  $("dzz-tab-sites")?.addEventListener("click", () => setDzzDockMode("sites"));
  $("dzz-tab-tiles")?.addEventListener("click", () => setDzzDockMode("tiles"));
  $("dzz-dock-summary")?.addEventListener("click", toggleDzzDock);
  $("dzz-dock-toggle")?.addEventListener("click", toggleDzzDock);
  $("dzz-exit-normal-map")?.addEventListener("click", disconnectDzz);
  $("dzz-grid-toggle")?.addEventListener("click", toggleDzzTileGrid);
  const shiftMap = { Север: [0, -1], Запад: [-1, 0], Восток: [1, 0], Юг: [0, 1] };
  document.querySelectorAll(".dzz-tile-nav button, .dzz-tile-nav-settings button").forEach((btn) => {
    const delta = shiftMap[btn.getAttribute("title")];
    if (delta) btn.addEventListener("click", () => shiftDzzTile(...delta));
  });
  $("history-filter-btn")?.addEventListener("click", toggleHistoryFilterMenu);
  $("history-filter-all")?.addEventListener("change", (event) => toggleHistoryFilterAll(event.target.checked));
  document.querySelectorAll(".history-filter-cat").forEach((el) => {
    el.addEventListener("change", onHistoryFilterCatChange);
  });
  $("history-search")?.addEventListener("input", renderHistoryFeed);
  $("history-sort")?.addEventListener("change", renderHistoryFeed);
  $("save-profile-btn")?.addEventListener("click", saveProfile);
  $("delete-account-btn")?.addEventListener("click", deleteAccount);
  $("avatar-file-input")?.addEventListener("change", (event) => handleAvatarFile(event.target.files?.[0]));
  document.querySelectorAll(".folder-picker-backdrop").forEach((el) => {
    el.addEventListener("click", () => {
      if (el.parentElement?.id === "app-modal") closeAppModal();
      else closeFolderPicker();
    });
  });
  document.querySelector("#folder-picker .mini-btn")?.addEventListener("click", closeFolderPicker);
}

bindPasswordToggles();
bindUi();

if (!getAccessToken()) {
  document.getElementById("screen-auth").style.display = "";
}

restoreSession();
