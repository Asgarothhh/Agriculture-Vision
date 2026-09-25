import * as dzzApi from "../api/dzz.js";
import { $, showToast, dbg } from "../ui.js";
import { getMap, setBasemap, setDzzTileGrid } from "../map/map.js";

let pollTimer = 0;
let inflight = null;
let lastAt = 0;
let connecting = false;

function setDzzPill(kind, text) {
  const el = $("status-dzz");
  if (!el) return;
  el.classList.remove("status-online", "status-idle", "status-offline", "offline");
  el.classList.add(kind);
  el.textContent = text;
  // #region agent log
  dbg("H2", "dzz-pill", { kind, text, className: el.className });
  // #endregion
}

export async function testDzzAccess() {
  if (connecting) return;
  connecting = true;
  const login = $("opt-dzz-login")?.value.trim() || "";
  const password = $("opt-dzz-password")?.value || "";
  const service_url = $("opt-dzz-url")?.value.trim() || undefined;
  setDzzPill("status-idle", "dzz.by · Проверка…");
  if ($("dzz-conn-status")) $("dzz-conn-status").textContent = "Проверка…";
  showToast("Проверяем dzz.by…");
  try {
    await dzzApi.connectDzz({ login, password, service_url });
    if ($("opt-dzz-password")) $("opt-dzz-password").value = "";
    if ($("dzz-conn-status")) $("dzz-conn-status").textContent = "Подключено";
    showToast("dzz.by подключён");
    await refreshDzzStatus(true);
    await loadRegions();
    if ($("opt-basemap")?.value === "dzz") setBasemap("dzz");
  } catch (err) {
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
      const online = connected && status.status === "online";
      if (online) setDzzPill("status-online", "dzz.by · Онлайн");
      else if (connected) setDzzPill("status-offline", "dzz.by · Ошибка");
      else setDzzPill("status-idle", "dzz.by · Не подключено");
      $("dzz-sites-bar").hidden = !connected;
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
    const failed = !status || status.status !== "online";
    pollTimer = setTimeout(tick, failed ? 5000 : 30000);
  };
  tick();
}

export function stopDzzPolling() {
  clearTimeout(pollTimer);
}

export async function loadRegions() {
  try {
    const regions = await dzzApi.dzzRegions();
    const list = $("dzz-sites-list");
    const settings = $("dzz-sites-settings-list");
    const html = (regions || [])
      .map(
        ([name, lat, lon], idx) =>
          `<button type="button" class="dzz-site-chip" data-lat="${lat}" data-lon="${lon}">${name || idx}</button>`,
      )
      .join("");
    if (list) list.innerHTML = html;
    if (settings) settings.innerHTML = html;
    $("dzz-sites-settings")?.removeAttribute("hidden");
    document.querySelectorAll(".dzz-site-chip").forEach((btn) => {
      btn.onclick = () => {
        getMap()?.setView([Number(btn.dataset.lat), Number(btn.dataset.lon)], 14);
      };
    });
  } catch {
    /* ignore */
  }
}

export async function loadWmtsCatalog() {
  try {
    const items = await dzzApi.dzzCapabilities();
    $("dzz-wmts-status").textContent = items.length ? `Слоёв: ${items.length}` : "Каталог пуст";
    const select = $("opt-dzz-wmts-layer");
    select.innerHTML = items.map((i) => `<option value="${i.layer}">${i.layer}</option>`).join("");
    $("dzz-wmts-panel").hidden = !items.length;
  } catch (err) {
    $("dzz-wmts-status").textContent = err.message;
  }
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

export { setDzzTileGrid };
