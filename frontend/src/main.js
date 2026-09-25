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
import { bindPasswordToggles, closeAppModal, $, showToast, dbg } from "./ui.js";
import {
  applyDisplaySettings,
  applyLiveStyles,
  createFolder,
  filterLayers,
  importLayerFile,
  loadMapData,
  onFieldCropSelect,
  populateCropSelect,
  restoreDisplaySettings,
  saveFieldName,
  startAoiSelection,
  startCreateArea,
  startPolygonArea,
  startMergePolygonsMode,
  toggleCreateLayerForm,
} from "./layers/store.js";
import { clearAoi, initMap, setBasemap, setDzzTileGrid } from "./map/map.js";
import { activateMapTool, cancelMergeMode, finishEditAreaMode, mergeSelectedPair, openEditAreaMode, setEditDrawMode } from "./map/tools.js";
import { bindHotkeys, bindSidebarResize } from "./map/hotkeys.js";
import { redoLast, undoLast } from "./map/undo.js";
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
  onDzzPillClick,
  startDzzPolling,
  stopDzzPolling,
  testDzzAccess,
} from "./dzz/panel.js";
import { exportLayers } from "./export/download.js";
import { deleteAccount, renderHistoryFeed, saveProfile } from "./account/profile.js";

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
  if (name === "account") renderHistoryFeed();
  if (name === "map") setTimeout(() => initMap().invalidateSize(), 50);
}

function toggleSegPanel() {
  $("map-seg-panel")?.classList.toggle("collapsed");
}

function toggleMoreMenu(event) {
  event?.stopPropagation();
  $("more-menu")?.classList.toggle("active");
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
  restoreDisplaySettings();
  activateMapTool("select");
  await loadMapData();
  populateCropSelect();
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
  const savedMap = localStorage.getItem("ttz_basemap");
  if (savedMap) {
    if ($("opt-basemap")) $("opt-basemap").value = savedMap;
    setBasemap(savedMap);
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
  localStorage.setItem("ttz_basemap", value || "satellite");
  if (value === "custom") {
    const url = $("opt-custom-basemap-url")?.value.trim();
    if (!url) {
      showToast("Укажите URL подложки", true);
      return;
    }
    setBasemap("custom", url);
  } else if (value && value !== "dzz") setBasemap(value);
  applyDisplaySettings();
  showToast("Настройки сохранены");
}

function toggleLayerGroup(id) {
  $(id)?.classList.toggle("collapsed");
}
function toggleFieldDetailPanel() {
  $("field-detail-body")?.classList.toggle("collapsed");
}
function setMapDisplayOption(key, checked) {
  localStorage.setItem(key === "labels" ? "ttz_field_labels" : "ttz_field_coords", checked ? "1" : "0");
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
    applyLiveStyles();
  });
  $("opt-line-width")?.addEventListener("input", (event) => {
    $("line-width-value").innerText = event.target.value;
    applyLiveStyles();
  });
  $("opt-fill-opacity")?.addEventListener("input", (event) => {
    $("fill-opacity-value").innerText = event.target.value;
    applyLiveStyles();
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
    startPolygonArea();
  });
  $("edit-area-item")?.addEventListener("click", (event) => {
    event.stopPropagation();
    openEditAreaMode();
  });
  $("merge-menu-item")?.addEventListener("click", (event) => {
    event.stopPropagation();
    startMergePolygonsMode();
  });
  $("merge-confirm-btn")?.addEventListener("click", () => {
    mergeSelectedPair();
  });
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

// #region agent log
document.addEventListener(
  "click",
  (event) => {
    const t = event.target?.closest?.("[id], .tool-btn, .icon-btn, button, a, select");
    if (!t) return;
    dbg("UI", "click", {
      id: t.id || "",
      cls: String(t.className || "").slice(0, 80),
      text: String(t.textContent || "").replace(/\s+/g, " ").trim().slice(0, 80),
      tool: t.dataset?.tool,
      panel: t.dataset?.panel,
      mapClass: document.getElementById("map-area")?.className,
      dzzClass: document.getElementById("status-dzz")?.className,
      dzzText: document.getElementById("status-dzz")?.textContent,
      mlText: document.getElementById("status-ml")?.textContent,
      zoom: document.getElementById("tile-display")?.textContent,
      sidebar: document.getElementById("sidebar-panel-wrap")?.className,
    });
  },
  true,
);
window.addEventListener("error", (event) => {
  dbg("H3", "window-error", { msg: event.message, src: event.filename, line: event.lineno });
});
window.addEventListener("unhandledrejection", (event) => {
  dbg("H3", "unhandledrejection", { msg: String(event.reason?.message || event.reason || "").slice(0, 200) });
});
["prompt", "confirm", "alert"].forEach((name) => {
  const orig = window[name];
  window[name] = function (...args) {
    dbg("H1", `native-${name}`, { args: args.map((a) => String(a).slice(0, 80)) });
    return orig.apply(this, args);
  };
});
// #endregion

if (!getAccessToken()) {
  document.getElementById("screen-auth").style.display = "";
}

restoreSession();
