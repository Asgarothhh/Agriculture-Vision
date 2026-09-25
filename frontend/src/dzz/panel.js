import * as dzzApi from "../api/dzz.js";
import { $, showToast } from "../ui.js";
import { getMap, setBasemap, setDzzCoverageBounds, setDzzTileGrid } from "../map/map.js";
import { restoreDzzSession } from "./session.js";
import { clearDzzTileCache } from "./tiles.js";
import {
  DZZ_DEFAULT_SERVICE,
  dzzSession,
  normalizeServiceRoot,
  parseDzzSites,
  toSameOriginDzzUrl,
  unionSiteBounds,
} from "./urls.js";

let pollTimer = 0;
let inflight = null;
let lastAt = 0;
let connecting = false;
const wmtsCatalogs = { dzz: null, custom: null };

function setDzzPill(kind, text) {
  const el = $("status-dzz");
  if (!el) return;
  el.classList.remove("status-online", "status-idle", "status-offline", "offline");
  el.classList.add(kind);
  el.textContent = text;
}

function prefix(source) {
  return source === "custom" ? "custom" : "dzz";
}

function field(source, name) {
  return $(`opt-${prefix(source)}-${name}`);
}

export async function testDzzAccess() {
  if (connecting) return;
  connecting = true;
  const login = $("opt-dzz-login")?.value.trim() || "";
  const password = $("opt-dzz-password")?.value || "";
  const url = $("opt-dzz-url")?.value.trim() || DZZ_DEFAULT_SERVICE;
  if (!login || !password) {
    showToast("Укажите логин и пароль dzz.by", true);
    connecting = false;
    return;
  }
  setDzzPill("status-idle", "dzz.by · Проверка…");
  if ($("dzz-conn-status")) $("dzz-conn-status").textContent = "Проверка…";
  showToast("Проверяем dzz.by…");
  try {
    const result = await dzzApi.connectDzz({ login, password, url });
    if ($("opt-dzz-password")) $("opt-dzz-password").value = "";
    dzzSession.connected = true;
    dzzSession.serviceRoot = result.service_url || result.url || normalizeServiceRoot(url);
    dzzSession.url = dzzSession.serviceRoot;
    dzzSession.wmtsTemplate = "";
    if ($("opt-dzz-url") && result.service_url) $("opt-dzz-url").value = result.service_url;
    if ($("opt-basemap")) $("opt-basemap").value = "dzz";
    if ($("dzz-conn-status")) $("dzz-conn-status").textContent = "Подключено";
    showToast("dzz.by подключён");
    setBasemap("dzz");
    await refreshDzzStatus(true);
    loadWmtsCatalog("dzz", { silent: true });
    loadDzzSites();
  } catch (err) {
    dzzSession.connected = false;
    if ($("dzz-conn-status")) $("dzz-conn-status").textContent = err.message;
    setDzzPill("status-offline", "dzz.by · Ошибка");
    showToast(err.message, true);
  } finally {
    connecting = false;
  }
}

export function onDzzPillClick() {
  $("sidebar-panel-wrap")?.classList.remove("collapsed");
  $("sidebar-panel")?.classList.remove("collapsed");
  const toggle = $("sidebar-edge-toggle");
  if (toggle) {
    toggle.setAttribute("aria-expanded", "true");
    toggle.title = "Свернуть панель";
  }
  document.querySelectorAll(".sidebar-icons .icon-btn[data-panel]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.panel === "settings");
  });
  document.querySelectorAll(".panel-content").forEach((panel) => {
    panel.classList.toggle("active", panel.id === "panel-settings");
  });
  $("basemap-dzz-block")?.scrollIntoView({ block: "nearest" });
  if ($("opt-basemap")) $("opt-basemap").value = "dzz";
  testDzzAccess();
}

export async function disconnectDzz() {
  try {
    await dzzApi.disconnectDzz();
    dzzSession.connected = false;
    dzzSession.wmtsTemplate = "";
    dzzSession.bounds = null;
    clearDzzTileCache();
    if ($("opt-dzz-login")) $("opt-dzz-login").value = "";
    if ($("opt-dzz-password")) $("opt-dzz-password").value = "";
    if ($("dzz-sites-list")) $("dzz-sites-list").innerHTML = "";
    if ($("dzz-sites-settings-list")) $("dzz-sites-settings-list").innerHTML = "";
    setDzzCoverageBounds(null);
    setDzzTileGrid(false);
    if ($("opt-dzz-tile-grid")) $("opt-dzz-tile-grid").checked = false;
    if ($("opt-basemap")) $("opt-basemap").value = "satellite";
    showToast("dzz.by отключён");
    await refreshDzzStatus(true);
    setBasemap("satellite");
  } catch (err) {
    showToast(err.message, true);
  }
}

export async function refreshDzzStatus(force = false) {
  if (inflight) return inflight;
  const wait = force ? 0 : Math.max(0, 1000 - (Date.now() - lastAt));
  inflight = (async () => {
    if (wait) await new Promise((resolve) => setTimeout(resolve, wait));
    const el = $("status-dzz");
    try {
      const status = await dzzApi.dzzStatus();
      const connected = !!status.connected;
      if (connected && !dzzSession.connected) {
        await restoreDzzSession();
        loadWmtsCatalog("dzz", { silent: true });
        loadDzzSites();
      }
      dzzSession.connected = connected;
      if (connected && (status.service_url || status.url)) {
        dzzSession.serviceRoot = status.service_url || status.url;
      }
      if (connected) setDzzPill("status-online", "dzz.by · Онлайн");
      else setDzzPill("status-idle", "dzz.by · Не подключено");
      if ($("dzz-sites-bar")) $("dzz-sites-bar").hidden = !connected;
      return status;
    } catch {
      setDzzPill("status-offline", "dzz.by · Ошибка");
      if (el) el.classList.add("offline");
      return null;
    } finally {
      lastAt = Date.now();
    }
  })();
  try {
    return await inflight;
  } finally {
    inflight = null;
  }
}

export function startDzzPolling() {
  stopDzzPolling();
  const tick = async () => {
    const status = await refreshDzzStatus();
    const failed = !status || !status.connected;
    pollTimer = setTimeout(tick, failed ? 5000 : 30000);
  };
  tick();
}

export function stopDzzPolling() {
  clearTimeout(pollTimer);
}

function renderSiteButtons(sites) {
  const html = (sites || [])
    .map(
      (site) =>
        `<button type="button" class="dzz-site-chip" data-lat="${site.center[0]}" data-lon="${site.center[1]}">${site.name}</button>`,
    )
    .join("");
  const list = $("dzz-sites-list");
  const settings = $("dzz-sites-settings-list");
  if (list) list.innerHTML = html;
  if (settings) settings.innerHTML = html;
  $("dzz-sites-settings")?.removeAttribute("hidden");
  document.querySelectorAll(".dzz-site-chip").forEach((btn) => {
    btn.onclick = () => {
      getMap()?.setView([Number(btn.dataset.lat), Number(btn.dataset.lon)], 14);
    };
  });
}

export async function loadDzzSites() {
  const root = dzzSession.serviceRoot || DZZ_DEFAULT_SERVICE;
  const queryUrl = `${root}/query?where=1%3D1&outFields=Name&returnGeometry=true&outSR=4326&f=json`;
  try {
    const res = await fetch(toSameOriginDzzUrl(queryUrl), { credentials: "same-origin" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = await res.json();
    const sites = parseDzzSites(payload);
    renderSiteButtons(sites);
    const union = unionSiteBounds(sites);
    dzzSession.bounds = union;
    if (union) {
      setDzzCoverageBounds([
        [union[1], union[0]],
        [union[3], union[2]],
      ]);
    }
  } catch {
    try {
      const sites = await dzzApi.dzzSites();
      if (Array.isArray(sites) && sites.length) renderSiteButtons(sites);
    } catch {
      /* ignore */
    }
  }
}

export async function loadRegions() {
  return loadDzzSites();
}

function selectedOption(select) {
  return select?.selectedOptions?.[0] || null;
}

function renderWmtsMatrixAndStyle(source) {
  const catalog = wmtsCatalogs[source];
  if (!catalog) return;
  const layerId = field(source, "wmts-layer")?.value;
  const layer = (catalog.layers || []).find((item) => item.id === layerId) || catalog.layers?.[0];
  const matrixSelect = field(source, "wmts-matrix");
  const styleSelect = field(source, "wmts-style");
  const hint = $(source === "custom" ? "opt-custom-wmts-hint" : "opt-dzz-wmts-hint");
  const matrixIds = layer?.tileMatrixSets || (catalog.tileMatrixSets || []).map((item) => item.id);
  const byId = Object.fromEntries((catalog.tileMatrixSets || []).map((item) => [item.id, item]));
  if (matrixSelect) {
    matrixSelect.innerHTML = matrixIds
      .map((id) => {
        const item = byId[id] || { id, supported: true };
        const mark = item.supported === false ? " (не поддерживается)" : "";
        const reach = item.reachable === false ? ` (ответ ${item.status || "ошибка"})` : "";
        return `<option value="${id}">${id}${mark}${reach}</option>`;
      })
      .join("");
    const suggested = catalog.suggested?.matrix;
    if (suggested && matrixIds.includes(suggested)) matrixSelect.value = suggested;
  }
  if (styleSelect) {
    const styles = layer?.styles || ["default"];
    styleSelect.innerHTML = styles.map((id) => `<option value="${id}">${id}</option>`).join("");
    const suggestedStyle = catalog.suggested?.style || layer?.defaultStyle;
    if (suggestedStyle) styleSelect.value = suggestedStyle;
  }
  const matrix = byId[matrixSelect?.value] || {};
  if (hint) {
    if (source === "dzz" && matrix.wellKnown === "GoogleMapsCompatible" && matrix.reachable === false) {
      hint.textContent = "Матрица GoogleMapsCompatible у dzz.by отвечает 520. Выбран запасной набор.";
    } else if (matrix.supported === false) {
      hint.textContent = "Эта матрица в проекции, которую карта не использует.";
    } else {
      hint.textContent = matrix.wellKnown ? `Набор: ${matrix.wellKnown}` : "";
    }
  }
}

function fillWmtsSelects(source) {
  const catalog = wmtsCatalogs[source];
  const layerSelect = field(source, "wmts-layer");
  if (!catalog || !layerSelect) return;
  layerSelect.innerHTML = (catalog.layers || [])
    .map((layer) => `<option value="${layer.id}">${layer.title || layer.id}</option>`)
    .join("");
  if (catalog.suggested?.layer) layerSelect.value = catalog.suggested.layer;
  renderWmtsMatrixAndStyle(source);
}

export function onWmtsLayerChange(source) {
  renderWmtsMatrixAndStyle(source);
}

export function onWmtsMatrixChange(source) {
  renderWmtsMatrixAndStyle(source);
  const catalog = wmtsCatalogs[source];
  const matrixId = field(source, "wmts-matrix")?.value;
  const matrix = (catalog?.tileMatrixSets || []).find((item) => item.id === matrixId);
  if (source === "dzz" && matrix?.wellKnown === "GoogleMapsCompatible") {
    const hint = $("opt-dzz-wmts-hint");
    if (hint) hint.textContent = "Матрица GoogleMapsCompatible у dzz.by часто отвечает 520 — лучше запасной набор.";
  }
}

export async function loadWmtsCatalog(source = "dzz", { silent = false } = {}) {
  const statusEl = $(source === "custom" ? "custom-wmts-status" : "dzz-wmts-status");
  const panel = $(source === "custom" ? "custom-wmts-panel" : "dzz-wmts-panel");
  try {
    const url =
      source === "custom"
        ? $("opt-custom-basemap-url")?.value.trim()
        : $("opt-dzz-url")?.value.trim() || dzzSession.serviceRoot;
    const body =
      source === "custom"
        ? {
            url,
            login: $("opt-custom-basemap-login")?.value.trim() || "",
            password: $("opt-custom-basemap-password")?.value || "",
          }
        : { url };
    const catalog = await dzzApi.dzzCapabilities(body);
    wmtsCatalogs[source] = catalog;
    const count = catalog?.layers?.length || 0;
    if (statusEl) statusEl.textContent = count ? `Слоёв: ${count}` : "Каталог пуст";
    if (panel) panel.hidden = !count;
    fillWmtsSelects(source);
    const suggested = catalog?.suggested;
    if (source === "dzz" && suggested?.wellKnown === "GoogleMapsCompatible") {
      const fallback = (catalog.tileMatrixSets || []).find(
        (item) => item.wellKnown !== "GoogleMapsCompatible" && item.supported !== false,
      );
      if (fallback && $("opt-dzz-wmts-hint")) {
        $("opt-dzz-wmts-hint").textContent = "Выбран запасной набор";
        if (field("dzz", "wmts-matrix")) field("dzz", "wmts-matrix").value = fallback.id;
      }
    }
  } catch (err) {
    if (statusEl && !silent) statusEl.textContent = err.message;
    if (!silent) showToast(err.message, true);
  }
}

export function applyWmtsSelection(source = "dzz") {
  const catalog = wmtsCatalogs[source];
  if (!catalog) {
    showToast("Сначала загрузите WMTSCapabilities", true);
    return;
  }
  const layerId = field(source, "wmts-layer")?.value;
  const matrixId = field(source, "wmts-matrix")?.value;
  const styleId = field(source, "wmts-style")?.value || "default";
  const layer = (catalog.layers || []).find((item) => item.id === layerId);
  let template = layer?.resourceUrl || catalog.tileUrlTemplate || catalog.suggested?.tileUrlTemplate || "";
  template = template
    .replaceAll("{Layer}", layerId || "")
    .replaceAll("{TileMatrixSet}", matrixId || "")
    .replaceAll("{Style}", styleId);
  if (!template) {
    showToast("Нет шаблона тайлов WMTS", true);
    return;
  }
  if (source === "dzz") {
    const matrix = (catalog.tileMatrixSets || []).find((item) => item.id === matrixId);
    if (matrix?.wellKnown === "GoogleMapsCompatible" && matrix.reachable === false) {
      showToast("GoogleMapsCompatible отвечает 520 — выбранный слой может не открыться", true);
    }
    dzzSession.wmtsTemplate = template;
    dzzSession.url = template;
    if ($("opt-dzz-url")) $("opt-dzz-url").value = template;
    clearDzzTileCache();
    setBasemap("dzz");
    showToast("Слой WMTS применён");
    return;
  }
  if ($("opt-custom-basemap-url")) $("opt-custom-basemap-url").value = template;
  setBasemap("custom", template);
  showToast("Слой WMTS применён");
}

export function onBasemapSelectChange(value) {
  $("basemap-dzz-block").style.display = "";
  $("basemap-custom-block").style.display = value === "custom" ? "block" : "none";
  if (value === "dzz") {
    refreshDzzStatus().then((status) => {
      if (status?.connected) setBasemap("dzz");
      else testDzzAccess();
    });
    return;
  }
  if (value !== "custom") setBasemap(value);
}

export function goToDzzTileFromForm(source) {
  const z = Number($(source === "bar" ? "dzz-bar-z" : "opt-dzz-tile-z").value);
  const x = Number($(source === "bar" ? "dzz-bar-x" : "opt-dzz-tile-x").value);
  const y = Number($(source === "bar" ? "dzz-bar-y" : "opt-dzz-tile-y").value);
  const map = getMap();
  if (!map || !Number.isFinite(z)) return;
  const n = 2 ** z;
  const lon = (x / n) * 360 - 180;
  const latRad = Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n)));
  const lat = (latRad * 180) / Math.PI;
  map.setView([lat, lon], z);
}

export { setDzzTileGrid, selectedOption };
