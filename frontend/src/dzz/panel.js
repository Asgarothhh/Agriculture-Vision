import * as dzzApi from "../api/dzz.js";
import { logAction } from "../api/activity.js";
import { $, showToast } from "../ui.js";
import { getBasemapKind, getMap, redrawDzzLayer, setBasemap, setDzzCoverageBounds, setDzzTileGrid } from "../map/map.js";
import { restoreDzzSession } from "./session.js";
import {
  isWebMercatorMatrix,
  pickWebMercatorMatrix,
  probeTileTemplate,
  resolveTileTemplate,
} from "../map/tileTemplate.js";
import { clearDzzTileCache, dzzFetchResilient } from "./tiles.js";
import { getDzzSitesCount, setDzzSites } from "./dock.js";
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
let recoveryTimer = 0;
let tilesFailing = false;
const RECOVERY_CHECK_MS = 10000;

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
    clearDzzTileCache();
    dzzSession.connected = true;
    dzzSession.serviceRoot = result.service_url || result.url || normalizeServiceRoot(url);
    dzzSession.url = dzzSession.serviceRoot;
    dzzSession.wmtsTemplate = "";
    if ($("opt-dzz-url") && result.service_url) $("opt-dzz-url").value = result.service_url;
    if ($("opt-basemap")) $("opt-basemap").value = "dzz";
    if ($("dzz-conn-status")) $("dzz-conn-status").textContent = "Подключено";
    showToast("dzz.by подключён");
    setBasemap("dzz");
    redrawDzzLayer();
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
    stopRecoveryChecks();
    tilesFailing = false;
    dzzSession.connected = false;
    dzzSession.wmtsTemplate = "";
    dzzSession.bounds = null;
    clearDzzTileCache();
    if ($("opt-dzz-login")) $("opt-dzz-login").value = "";
    if ($("opt-dzz-password")) $("opt-dzz-password").value = "";
    setDzzSites([]);
    setDzzCoverageBounds(null);
    setDzzTileGrid(false);
    if ($("opt-dzz-tile-grid")) $("opt-dzz-tile-grid").checked = false;
    if ($("opt-basemap")) $("opt-basemap").value = "satellite";
    showToast("Вышли из dzz.by. Открыта обычная карта");
    logAction("tool", "Выход из dzz.by, возврат к обычной карте");
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
      fillSavedConnection(status);
      if (connected) setDzzPill("status-online", "dzz.by · Онлайн");
      else setDzzPill("status-idle", "dzz.by · Не подключено");
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

function setConnStatus(text) {
  if ($("dzz-conn-status")) $("dzz-conn-status").textContent = text || "";
}

function reportSites(count) {
  setConnStatus(count ? `Подключено: ${count} участок(ов) ортофото` : "Подключение есть, но каталог участков пуст");
}

/** URL of the active dzz.by connection in the settings form (after a page reload). */
function fillSavedConnection(status) {
  if (!status?.connected) return;
  const urlEl = $("opt-dzz-url");
  const url = status.service_url || status.url;
  if (urlEl && url && document.activeElement !== urlEl) urlEl.value = url;
}

function stopRecoveryChecks() {
  clearTimeout(recoveryTimer);
  recoveryTimer = 0;
}

/**
 * Tiles stopped loading: check dzz.by in the background (the header status is left as is)
 * and, once it answers again, re-request the failed tiles and the site list.
 */
function scheduleRecoveryCheck() {
  if (recoveryTimer) return;
  recoveryTimer = setTimeout(async () => {
    recoveryTimer = 0;
    if (!tilesFailing || !dzzSession.connected) return;
    let health = null;
    try {
      health = await dzzApi.dzzCheck();
    } catch {
      health = null;
    }
    if (health?.connected) onDzzRecovered();
    else {
      if (health && health.status === "bad_credentials") {
        setConnStatus("Учётные данные dzz.by больше не подходят — подключитесь заново");
      } else if (health && !health.connected && health.status !== "bad_credentials") {
        setConnStatus("Сервис dzz.by недоступен. Повторная проверка каждые 10 с.");
      }
      scheduleRecoveryCheck();
    }
  }, RECOVERY_CHECK_MS);
}

function onDzzRecovered() {
  tilesFailing = false;
  stopRecoveryChecks();
  if (getBasemapKind() !== "dzz") return;
  redrawDzzLayer();
  if (!getDzzSitesCount()) loadDzzSites();
  setConnStatus("Связь с dzz.by восстановлена");
  showToast("Связь с dzz.by восстановлена");
}

/** App logout: the next user of this browser must not see this user's dzz.by tiles. */
export function resetDzzClient() {
  stopRecoveryChecks();
  tilesFailing = false;
  dzzSession.connected = false;
  dzzSession.wmtsTemplate = "";
  dzzSession.bounds = null;
  clearDzzTileCache();
  setDzzSites([]);
  if ($("opt-dzz-login")) $("opt-dzz-login").value = "";
  if ($("opt-dzz-password")) $("opt-dzz-password").value = "";
  setConnStatus("");
}

let recoveryBound = false;

export function initDzzRecovery() {
  if (recoveryBound) return;
  recoveryBound = true;
  document.addEventListener("av:dzz-tiles-failing", (event) => {
    if (tilesFailing) return;
    tilesFailing = true;
    if (event.detail?.reason === "session") {
      dzzSession.connected = false;
      setConnStatus("Подключение к dzz.by отключено — подключитесь заново");
      showToast("Подключение к dzz.by отключено — подключитесь заново в настройках", true);
      return;
    }
    setConnStatus("Тайлы dzz.by не загружаются — проверяем связь…");
    scheduleRecoveryCheck();
  });
  document.addEventListener("av:dzz-tiles-ok", () => {
    if (tilesFailing) onDzzRecovered();
  });
}

export async function loadDzzSites() {
  const root = dzzSession.serviceRoot || DZZ_DEFAULT_SERVICE;
  const queryUrl = `${root}/query?where=1%3D1&outFields=Name&returnGeometry=true&outSR=4326&f=json`;
  try {
    const res = await dzzFetchResilient(toSameOriginDzzUrl(queryUrl), 20000);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const payload = await res.json();
    const sites = parseDzzSites(payload);
    setDzzSites(sites);
    reportSites(sites.length);
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
      const list = Array.isArray(sites) ? sites : [];
      setDzzSites(list);
      reportSites(list.length);
    } catch {
      setDzzSites([]);
      setConnStatus("Не удалось загрузить участки dzz.by");
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
    const previous = matrixSelect.value;
    matrixSelect.innerHTML = matrixIds
      .map((id) => {
        const item = byId[id] || { id, supported: true };
        const mark = isWebMercatorMatrix(item) ? "" : " (градусы — не поддерживается)";
        const reach = item.reachable === false ? ` (ответ ${item.status || "ошибка"})` : "";
        return `<option value="${id}">${id}${mark}${reach}</option>`;
      })
      .join("");
    const suggested = catalog.suggested?.matrix;
    const usable = pickWebMercatorMatrix(matrixIds, byId);
    if (previous && matrixIds.includes(previous)) matrixSelect.value = previous;
    else if (suggested && matrixIds.includes(suggested) && isWebMercatorMatrix(byId[suggested] || { id: suggested })) {
      matrixSelect.value = suggested;
    } else if (usable) matrixSelect.value = usable.id;
  }
  if (styleSelect) {
    const styles = layer?.styles || ["default"];
    styleSelect.innerHTML = styles.map((id) => `<option value="${id}">${id}</option>`).join("");
    const suggestedStyle = catalog.suggested?.style || layer?.defaultStyle;
    if (suggestedStyle) styleSelect.value = suggestedStyle;
  }
  const matrix = byId[matrixSelect?.value] || { id: matrixSelect?.value };
  if (hint) {
    if (!pickWebMercatorMatrix(matrixIds, byId)) {
      hint.textContent = "У этого слоя нет набора в Web Mercator — применить его на карте нельзя.";
    } else if (!isWebMercatorMatrix(matrix)) {
      hint.textContent = "Набор в градусах (EPSG:4326) — карта работает в Web Mercator, выберите другой набор.";
    } else if (source === "dzz" && matrix.wellKnown === "GoogleMapsCompatible" && matrix.reachable === false) {
      hint.textContent = "Матрица GoogleMapsCompatible у dzz.by отвечает 520. Выбран запасной набор.";
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
  const chosen = (catalog.tileMatrixSets || []).find((item) => item.id === matrixId) || { id: matrixId };
  if (!isWebMercatorMatrix(chosen)) {
    showToast("Набор в градусах (EPSG:4326) не поддерживается — выберите набор Web Mercator", true);
    return;
  }
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
  if (!applyCustomBasemap(template)) return;
  showToast("Слой WMTS применён");
}

/** Why a custom basemap URL cannot be used at all ("" — it can). */
export function customBasemapProblem(url) {
  if (!String(url || "").trim()) return "Укажите URL шаблон дополнительной подложки";
  if (!resolveTileTemplate(url)) {
    return "В адресе нет {z}/{x}/{y} — вставьте шаблон тайлов или загрузите WMTSCapabilities";
  }
  return "";
}

/** One test tile at the current view: warns, the basemap stays applied (7.11, decision 29.09). */
export async function warnIfCustomTileFails(url) {
  const map = getMap();
  if (!map) return true;
  const center = map.getCenter();
  const ok = await probeTileTemplate(resolveTileTemplate(url), center.lat, center.lng, map.getZoom());
  if (!ok) {
    showToast(
      "Тайл по этому адресу не загрузился — проверьте шаблон {z}/{x}/{y}, доступ к сервису и покрытие в этом месте",
      true,
    );
  }
  return ok;
}

/** Applies the custom basemap (after the URL checks). Returns false if the URL is unusable. */
export function applyCustomBasemap(url) {
  const problem = customBasemapProblem(url);
  if (problem) {
    showToast(problem, true);
    return false;
  }
  setBasemap("custom", url);
  warnIfCustomTileFails(url);
  return true;
}

/** Selecting a basemap in settings that cannot be shown: back to the one on the map. */
function revertBasemapSelect() {
  const select = $("opt-basemap");
  if (select) select.value = getBasemapKind();
  $("basemap-custom-block").style.display = getBasemapKind() === "custom" ? "block" : "none";
}

export function onBasemapSelectChange(value) {
  $("basemap-dzz-block").style.display = "";
  $("basemap-custom-block").style.display = value === "custom" ? "block" : "none";
  if (value === "dzz") {
    refreshDzzStatus().then(async (status) => {
      if (status?.connected) {
        setBasemap("dzz");
        // The catalogue may have failed at connect time; retry now that dzz.by is shown.
        if (!getDzzSitesCount()) loadDzzSites();
        return;
      }
      const login = $("opt-dzz-login")?.value.trim();
      const password = $("opt-dzz-password")?.value;
      if (!login || !password) {
        showToast("Укажите логин, пароль и адрес, затем «Проверить подключение»", true);
        revertBasemapSelect();
        return;
      }
      await testDzzAccess();
      if (!dzzSession.connected) revertBasemapSelect();
    });
    return;
  }
  if (value === "custom") {
    // The block with the URL stays open; an empty URL only gets a hint.
    const url = $("opt-custom-basemap-url")?.value.trim();
    if (!url) showToast("Укажите URL шаблон дополнительной подложки", true);
    else applyCustomBasemap(url);
    return;
  }
  setBasemap(value);
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
