import * as dzzApi from "../api/dzz.js";
import { $, showToast } from "../ui.js";
import { getMap, setBasemap } from "../map/map.js";

let pollTimer = 0;

export async function testDzzAccess() {
  const login = $("opt-dzz-login").value.trim();
  const password = $("opt-dzz-password").value;
  const service_url = $("opt-dzz-url").value.trim() || undefined;
  try {
    await dzzApi.connectDzz({ login, password, service_url });
    $("opt-dzz-password").value = "";
    $("dzz-conn-status").textContent = "Подключено";
    showToast("dzz.by подключён");
    await refreshDzzStatus();
    await loadRegions();
  } catch (err) {
    $("dzz-conn-status").textContent = err.message;
    showToast(err.message, true);
  }
}

export async function disconnectDzz() {
  try {
    await dzzApi.disconnectDzz();
    showToast("dzz.by отключён");
    await refreshDzzStatus();
  } catch (err) {
    showToast(err.message, true);
  }
}

export async function refreshDzzStatus() {
  const el = $("status-dzz");
  try {
    const status = await dzzApi.dzzStatus();
    const online = status.connected && status.status === "online";
    el.textContent = online ? "dzz.by · Онлайн" : "dzz.by · недоступен";
    el.classList.toggle("offline", !online);
    $("dzz-sites-bar").hidden = !status.connected;
    return status;
  } catch {
    el.textContent = "dzz.by · недоступен";
    el.classList.add("offline");
    return null;
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
  $("basemap-dzz-block").style.display = value === "dzz" || true ? "" : "";
  $("basemap-custom-block").style.display = value === "custom" ? "block" : "none";
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
