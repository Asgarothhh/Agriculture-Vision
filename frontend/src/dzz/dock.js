// Bottom dzz.by dock («Участки» / «Тайлы») and the «Участки ортофото» list in settings.
// Behaviour follows the reference UI: the dock is shown only while the dzz.by basemap
// is on the map; tabs switch or collapse it; the collapsed line summarises the state.
import { $, escapeHtml, showToast } from "../ui.js";
import { getBasemapKind, getMap, getMapTileCoords } from "../map/map.js";
import { getCurrentUser } from "../auth/session.js";
import { formatDzzCoords, humanizeDzzSiteName } from "./urls.js";
import { logAction } from "../api/activity.js";

const DZZ_VIEW_ZOOM = 16;

let sites = [];
let activeSiteId = "";
let dockMode = "sites";
let dockOpen = false;
let bound = false;

function dockStorageKey() {
  return `ttz_dzz_dock_${getCurrentUser()?.email || "anon"}`;
}

function loadDockState() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(dockStorageKey()) || "null");
    if (!saved) return;
    dockMode = saved.mode === "tiles" ? "tiles" : "sites";
    dockOpen = !!saved.open;
  } catch {
    /* storage unavailable: defaults */
  }
}

function persistDockState() {
  try {
    sessionStorage.setItem(dockStorageKey(), JSON.stringify({ mode: dockMode, open: dockOpen }));
  } catch {
    /* storage unavailable */
  }
}

/** Normalises a site from ImageServer/query or GET /dzz/sites to {id,title,lat,lng,bounds}. */
export function normalizeDzzSite(site, index = 0) {
  const center = site?.center || [];
  const lat = Number(center[0]);
  const lng = Number(center[1]);
  if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  const name = site?.name || site?.title || `Участок ${index + 1}`;
  return {
    id: String(site?.id ?? name),
    name,
    title: humanizeDzzSiteName(name),
    lat,
    lng,
    bounds: site?.bounds || null,
  };
}

/** Text of the collapsed dock line. */
export function dzzDockSummaryText({ mode, tile, activeSite, count }) {
  if (mode === "tiles" && tile) return `${tile.z}/${tile.x}/${tile.y}`;
  if (activeSite) return activeSite.title;
  return count ? `${count} участок(ов)` : "dzz.by";
}

function updateDockSummary() {
  const el = $("dzz-dock-summary");
  if (!el) return;
  const activeSite = sites.find((item) => item.id === activeSiteId);
  const tile = dockMode === "tiles" && getMap() ? getMapTileCoords() : null;
  el.textContent = dzzDockSummaryText({ mode: dockMode, tile, activeSite, count: sites.length });
  el.title = dockOpen ? "Свернуть панель" : tile ? `Тайл ${el.textContent}` : el.textContent;
}

function applyDockUi() {
  const bar = $("dzz-sites-bar");
  if (!bar) return;
  bar.classList.toggle("is-open", dockOpen);
  const sitesOn = dockOpen && dockMode === "sites";
  const tilesOn = dockOpen && dockMode === "tiles";
  const sitesTab = $("dzz-tab-sites");
  const tilesTab = $("dzz-tab-tiles");
  if (sitesTab) {
    sitesTab.classList.toggle("is-active", sitesOn);
    sitesTab.setAttribute("aria-selected", sitesOn ? "true" : "false");
  }
  if (tilesTab) {
    tilesTab.classList.toggle("is-active", tilesOn);
    tilesTab.setAttribute("aria-selected", tilesOn ? "true" : "false");
  }
  if ($("dzz-sites-pane")) $("dzz-sites-pane").hidden = !sitesOn;
  if ($("dzz-tiles-pane")) $("dzz-tiles-pane").hidden = !tilesOn;
  const toggle = $("dzz-dock-toggle");
  if (toggle) {
    toggle.setAttribute("aria-expanded", dockOpen ? "true" : "false");
    toggle.title = dockOpen ? "Свернуть панель" : "Развернуть панель";
  }
  updateDockSummary();
  // The dock takes height from the map column: let Leaflet re-measure after the animation.
  setTimeout(() => getMap()?.invalidateSize(), 240);
}

/** Tab click: open that tab, or collapse the dock when the open tab is clicked again. */
export function setDzzDockMode(mode) {
  const next = mode === "tiles" ? "tiles" : "sites";
  if (dockOpen && dockMode === next) dockOpen = false;
  else {
    dockMode = next;
    dockOpen = true;
  }
  persistDockState();
  applyDockUi();
}

export function toggleDzzDock() {
  dockOpen = !dockOpen;
  persistDockState();
  applyDockUi();
}

export function revealDzzDock(mode) {
  dockMode = mode === "tiles" ? "tiles" : "sites";
  dockOpen = true;
  persistDockState();
  applyDockUi();
}

function chipHtml(site) {
  const active = site.id === activeSiteId ? " is-active" : "";
  return `<button type="button" class="dzz-site-chip${active}" data-dzz-site="${escapeHtml(site.id)}" title="${escapeHtml(site.title)}">
    <strong>${escapeHtml(site.title)}</strong>
    <small>${escapeHtml(formatDzzCoords(site.lat, site.lng))}</small>
  </button>`;
}

function rowHtml(site) {
  const active = site.id === activeSiteId ? " is-active" : "";
  return `<div class="dzz-site-row${active}" data-dzz-site="${escapeHtml(site.id)}">
    <div class="dzz-site-row-text">
      <strong>${escapeHtml(site.title)}</strong>
      <small>${escapeHtml(formatDzzCoords(site.lat, site.lng))}</small>
    </div>
    <span class="dzz-site-row-go">Перейти</span>
  </div>`;
}

export function renderDzzSites() {
  const bar = $("dzz-sites-bar");
  const visible = getBasemapKind() === "dzz";
  if (bar) {
    bar.hidden = !visible;
    bar.classList.toggle("is-visible", visible);
    if (visible) {
      if (!bar.dataset.dockReady) {
        loadDockState();
        bar.dataset.dockReady = "1";
      }
      applyDockUi();
    } else {
      bar.classList.remove("is-open");
      delete bar.dataset.dockReady;
    }
  }
  const list = $("dzz-sites-list");
  if (list) {
    list.innerHTML = sites.length
      ? sites.map(chipHtml).join("")
      : '<span class="dzz-dock-empty">Участки появятся после загрузки покрытия</span>';
  }
  const settingsWrap = $("dzz-sites-settings");
  if (settingsWrap) settingsWrap.hidden = sites.length === 0;
  const settingsList = $("dzz-sites-settings-list");
  if (settingsList) settingsList.innerHTML = sites.map(rowHtml).join("");
  document.querySelectorAll("[data-dzz-site]").forEach((el) => {
    el.onclick = () => goToDzzSite(el.dataset.dzzSite);
  });
  updateDockSummary();
  if (visible) setTimeout(() => getMap()?.invalidateSize(), 50);
}

/** Replaces the site list (after loading the dzz.by catalogue, or [] on disconnect). */
export function setDzzSites(list) {
  sites = (list || []).map(normalizeDzzSite).filter(Boolean);
  if (!sites.some((site) => site.id === activeSiteId)) activeSiteId = "";
  renderDzzSites();
}

export function getDzzSitesCount() {
  return sites.length;
}

export function goToDzzSite(siteId, silent = false) {
  const site = sites.find((item) => item.id === String(siteId));
  const map = getMap();
  if (!site || !map) return;
  activeSiteId = site.id;
  renderDzzSites();
  if (!silent) revealDzzDock("sites");
  const zoom = Math.min(18, Math.max(DZZ_VIEW_ZOOM, Math.round(map.getZoom())));
  map.flyTo([site.lat, site.lng], zoom, { duration: 0.75 });
  if (!silent) {
    showToast(`Переход: ${site.title}`);
    logAction("tool", `Переход к участку dzz.by: ${site.title}`);
  }
}

/** Wires map/basemap events once (the map must exist). */
export function initDzzDock() {
  if (bound) return;
  const map = getMap();
  if (!map) return;
  bound = true;
  document.addEventListener("av:basemap", renderDzzSites);
  map.on("zoomend moveend", () => {
    if (dockMode === "tiles") updateDockSummary();
  });
  renderDzzSites();
}
