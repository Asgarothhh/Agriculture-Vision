import "./styles/style.css";
import { handleAvatarFile, onAvatarClick } from "./account/avatar.js";
import { getAccessToken } from "./api/client.js";
import { logAction } from "./api/activity.js";
import { restoreDzzSession } from "./dzz/session.js";
import {
  handleLogin,
  handleLogout,
  getCurrentUser,
  handleRegister,
  openForgotPasswordModal,
  restoreSession,
  setAuthCallbacks,
  toggleMode,
} from "./auth/session.js";
import { bindPasswordToggles, closeAppModal, $, showToast } from "./ui.js";
import {
  importLayerFile,
  loadDisplaySettings,
  loadMapData,
  readDisplayForm,
  saveDisplaySettings,
  setMapDisplayOption,
  startAoiSelection,
} from "./layers/store.js";
import {
  closeFolderPicker,
  createFolder,
  filterLayers,
  initLayersPanel,
  onFieldCropSelect,
  saveFieldName,
  toggleCreateLayerForm,
} from "./layers/panel.js";
import { clearAoi, initMap, setBasemap, setDzzTileGrid } from "./map/map.js";
import {
  activateMapTool,
  cancelMergeMode,
  confirmMergePolygons,
  finishEditAreaMode,
  onDrawLayerSelect,
  openEditAreaMode,
  resetTools,
  setEditDrawMode,
  startCreateArea,
  startManualConnectMode,
  startMergePolygonsMode,
  startPolygonMode,
} from "./map/tools.js";
import { bindHotkeys, bindSidebarResize } from "./map/hotkeys.js";
import { initMoreMenu } from "./map/moreMenu.js";
import { clearUndo, redoLast, undoLast } from "./map/undo.js";
import {
  handleUploadFile,
  onSegArchitectureChange,
  onSegThresholdInput,
  runSegmentation,
  startMlHealthPolling,
  startUploadProcessing,
  stopMlHealthPolling,
} from "./tasks/runner.js";
import {
  applyWmtsSelection,
  customBasemapProblem,
  disconnectDzz,
  goToDzzTileFromForm,
  initDzzRecovery,
  loadWmtsCatalog,
  onBasemapSelectChange,
  onDzzPillClick,
  onWmtsLayerChange,
  onWmtsMatrixChange,
  resetDzzClient,
  startDzzPolling,
  stopDzzPolling,
  testDzzAccess,
  warnIfCustomTileFails,
} from "./dzz/panel.js";
import { exportLayers } from "./export/download.js";
import { initDzzDock, setDzzDockMode, toggleDzzDock } from "./dzz/dock.js";
import { deleteAccount, refreshAccountStats, renderHistoryFeed, saveProfile } from "./account/profile.js";
import { CLASS_CHECKBOXES } from "./layers/store.js";

function toggleSidebarPanel() {
  const wrap = $("sidebar-panel-wrap");
  wrap?.classList.toggle("collapsed");
  $("sidebar-panel")?.classList.toggle("collapsed");
  const collapsed = wrap?.classList.contains("collapsed");
  const btn = $("sidebar-edge-toggle");
  if (btn) {
    btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
    btn.title = collapsed ? "Показать панель" : "Свернуть панель";
  }
  setTimeout(() => initMap()?.invalidateSize(), 220);
}

function switchSidebar(name) {
  const wrap = $("sidebar-panel-wrap");
  if (wrap?.classList.contains("collapsed")) {
    wrap.classList.remove("collapsed");
    $("sidebar-panel")?.classList.remove("collapsed");
    const btn = $("sidebar-edge-toggle");
    if (btn) {
      btn.setAttribute("aria-expanded", "true");
      btn.title = "Свернуть панель";
    }
    setTimeout(() => initMap()?.invalidateSize(), 220);
  }
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
  if (name === "account") {
    renderHistoryFeed();
    refreshAccountStats();
  }
  if (name === "map") setTimeout(() => initMap().invalidateSize(), 50);
}

function toggleSegPanel() {
  $("map-seg-panel")?.classList.toggle("collapsed");
}

function toggleMoreMenu(event) {
  event?.stopPropagation();
  const menu = $("more-menu");
  if (!menu) return;
  const open = !menu.classList.contains("active");
  // Every opening starts expanded, not folded as last time (reference).
  if (open) menu.classList.remove("collapsed");
  menu.classList.toggle("active", open);
}

function toggleMoreMenuBody() {
  $("more-menu")?.classList.toggle("collapsed");
}

function setTool(name) {
  activateMapTool(name);
}

async function onAppReady() {
  initMap();
  bindHotkeys();
  bindSidebarResize();
  initMoreMenu();
  const saved = loadDisplaySettings(getCurrentUser()?.email);
  activateMapTool("select", { silent: true });
  initLayersPanel();
  await loadMapData();
  startMlHealthPolling();
  initDzzDock();
  initDzzRecovery();
  startDzzPolling();
  restoreClassCheckboxes();
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
  await restoreBasemap(saved);
}

/**
 * Basemap saved for this account. dzz.by only when its connection is alive (otherwise the
 * satellite, no tile errors at login); a custom basemap with its saved URL (7.12).
 */
async function restoreBasemap({ display, extra }) {
  let kind = display.basemap;
  if (kind === "dzz" && !(await restoreDzzSession())) kind = "satellite";
  if (kind === "custom" && !extra.customUrl) kind = "satellite";
  if ($("opt-basemap")) $("opt-basemap").value = kind;
  if ($("basemap-custom-block")) $("basemap-custom-block").style.display = kind === "custom" ? "block" : "none";
  // Always set it (also the satellite): the previous account's basemap must not stay on the map.
  if (kind === "custom") setBasemap("custom", extra.customUrl);
  else setBasemap(kind);
}

function onAppLogout() {
  stopDzzPolling();
  resetDzzClient();
  stopMlHealthPolling();
  resetTools();
  clearUndo();
}

const CLASS_STORAGE_KEY = "ttz_class_checkboxes";

/** Recognition categories (settings) survive a reload, like the other settings. */
function restoreClassCheckboxes() {
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(CLASS_STORAGE_KEY) || "null");
  } catch {
    saved = null;
  }
  Object.keys(CLASS_CHECKBOXES).forEach((id) => {
    const box = $(id);
    if (!box) return;
    if (saved && typeof saved[id] === "boolean") box.checked = saved[id];
    box.onchange = saveClassCheckboxes;
  });
}

function saveClassCheckboxes() {
  const state = {};
  Object.keys(CLASS_CHECKBOXES).forEach((id) => {
    if ($(id)) state[id] = $(id).checked;
  });
  try {
    localStorage.setItem(CLASS_STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* storage unavailable: the choice lives until reload */
  }
}

setAuthCallbacks({ ready: onAppReady, logout: onAppLogout });


/** «Сохранить настройки»: applied to the map and remembered for this email (5.1 / 5.2). */
function saveSettings() {
  const values = readDisplayForm();
  const extra = {
    customName: $("opt-custom-basemap-name")?.value.trim() || "",
    customUrl: $("opt-custom-basemap-url")?.value.trim() || "",
  };
  if (values.basemap === "custom") {
    const problem = customBasemapProblem(extra.customUrl);
    if (problem) {
      showToast(problem, true);
      return;
    }
  }
  saveDisplaySettings(getCurrentUser()?.email, values, extra);
  if (values.basemap === "custom") {
    setBasemap("custom", extra.customUrl);
    warnIfCustomTileFails(extra.customUrl);
  } else if (values.basemap !== "dzz") setBasemap(values.basemap);
  logAction("account", "Обновлены настройки");
  showToast("Настройки сохранены");
}

function toggleLayerGroup(id) {
  $(id)?.classList.toggle("collapsed");
}
function toggleFieldDetailPanel() {
  $("field-detail-body")?.classList.toggle("collapsed");
}
function shiftDzzTile(dx, dy) {
  const source = $("dzz-bar-z") ? "bar" : "opt";
  const zEl = $(source === "bar" ? "dzz-bar-z" : "opt-dzz-tile-z");
  const xEl = $(source === "bar" ? "dzz-bar-x" : "opt-dzz-tile-x");
  const yEl = $(source === "bar" ? "dzz-bar-y" : "opt-dzz-tile-y");
  if (!xEl || !yEl) return;
  xEl.value = String(Number(xEl.value || 0) + dx);
  yEl.value = String(Number(yEl.value || 0) + dy);
  if (zEl && !zEl.value) zEl.value = "13";
  goToDzzTileFromForm(source);
}

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
  // The number follows the slider at once; the map changes only on «Сохранить настройки».
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
  $("status-dzz")?.addEventListener("click", onDzzPillClick);
  $("dzz-connect-btn")?.addEventListener("click", onDzzPillClick);
  $("dzz-logout-btn")?.addEventListener("click", disconnectDzz);
  $("dzz-wmts-load-btn")?.addEventListener("click", () => loadWmtsCatalog("dzz"));
  $("dzz-wmts-apply-btn")?.addEventListener("click", () => applyWmtsSelection("dzz"));
  $("opt-dzz-wmts-layer")?.addEventListener("change", () => onWmtsLayerChange("dzz"));
  $("opt-dzz-wmts-matrix")?.addEventListener("change", () => onWmtsMatrixChange("dzz"));
  $("custom-wmts-load-btn")?.addEventListener("click", () => loadWmtsCatalog("custom"));
  $("custom-wmts-apply-btn")?.addEventListener("click", () => applyWmtsSelection("custom"));
  $("opt-custom-wmts-layer")?.addEventListener("change", () => onWmtsLayerChange("custom"));
  $("opt-custom-wmts-matrix")?.addEventListener("change", () => onWmtsMatrixChange("custom"));
  $("dzz-tile-go-opt")?.addEventListener("click", () => goToDzzTileFromForm("opt"));
  $("dzz-tile-go-bar")?.addEventListener("click", () => goToDzzTileFromForm("bar"));
  $("opt-dzz-tile-grid")?.addEventListener("change", (event) => setDzzTileGrid(event.target.checked));
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
  $("more-menu-toggle")?.addEventListener("click", (event) => {
    event.stopPropagation();
    toggleMoreMenuBody();
  });
  $("create-area-item")?.addEventListener("click", (event) => {
    event.stopPropagation();
    startCreateArea();
  });
  $("polygon-area-item")?.addEventListener("click", (event) => {
    event.stopPropagation();
    startPolygonMode();
  });
  $("edit-area-item")?.addEventListener("click", (event) => {
    event.stopPropagation();
    openEditAreaMode();
  });
  $("merge-menu-item")?.addEventListener("click", (event) => {
    event.stopPropagation();
    startMergePolygonsMode();
  });
  $("merge-confirm-btn")?.addEventListener("click", confirmMergePolygons);
  $("manual-connect-menu-item")?.addEventListener("click", (event) => {
    event.stopPropagation();
    startManualConnectMode();
  });
  $("draw-layer-select")?.addEventListener("change", (event) => onDrawLayerSelect(event.target.value));
  $("merge-cancel-btn")?.addEventListener("click", () => {
    cancelMergeMode();
  });
  $("edit-brush-btn")?.addEventListener("click", () => setEditDrawMode("brush"));
  $("edit-polygon-btn")?.addEventListener("click", () => setEditDrawMode("polygon"));
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
  $("dzz-grid-toggle")?.addEventListener("click", () => {
    const on = $("opt-dzz-tile-grid");
    if (on) on.checked = !on.checked;
    setDzzTileGrid(!!on?.checked);
  });
  const shiftMap = { Север: [0, -1], Запад: [-1, 0], Восток: [1, 0], Юг: [0, 1] };
  document.querySelectorAll(".dzz-tile-nav button, .dzz-tile-nav-settings button").forEach((btn) => {
    const delta = shiftMap[btn.getAttribute("title")];
    if (delta) btn.addEventListener("click", () => shiftDzzTile(...delta));
  });
  $("history-filter-btn")?.addEventListener("click", () => {
    const menu = $("history-filter-menu");
    menu.style.display = menu.style.display === "none" ? "block" : "none";
  });
  $("history-filter-all")?.addEventListener("change", (event) => {
    document.querySelectorAll(".history-filter-cat").forEach((el) => {
      el.checked = event.target.checked;
    });
    renderHistoryFeed();
  });
  document.querySelectorAll(".history-filter-cat").forEach((el) => {
    el.addEventListener("change", () => {
      const cats = [...document.querySelectorAll(".history-filter-cat")];
      $("history-filter-all").checked = cats.every((c) => c.checked);
      renderHistoryFeed();
    });
  });
  $("history-search")?.addEventListener("input", renderHistoryFeed);
  $("history-sort")?.addEventListener("change", renderHistoryFeed);
  $("save-profile-btn")?.addEventListener("click", saveProfile);
  $("card-avatar")?.addEventListener("click", onAvatarClick);
  if ($("card-avatar")) $("card-avatar").title = "Нажмите: загрузить или удалить аватарку";
  $("avatar-file-input")?.addEventListener("change", (event) => {
    handleAvatarFile(event.target.files?.[0]);
    event.target.value = "";
  });
  $("delete-account-btn")?.addEventListener("click", deleteAccount);
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
bindHotkeys();

if (!getAccessToken()) {
  document.getElementById("screen-auth").style.display = "";
}

restoreSession();
