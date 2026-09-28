// Crops of objects («Культура» in object properties), as in the reference UI.
// The object keeps the crop *name* on the server (field `crop`); the list of the user's
// own crops is a personal dictionary kept in the browser per email, in the reference
// format {key: label} under `ttz_custom_crops_<email>`.
import { escapeHtml } from "../ui.js";
import { getCurrentUser } from "../auth/session.js";

export const BUILTIN_CROP_LABELS = {
  soybean: "Соя",
  sugar_beet: "Сахарная свёкла",
  barley: "Ячмень",
  rapeseed: "Рапс",
  oat: "Овёс",
  corn: "Кукуруза",
  rice: "Рис",
  wheat: "Пшеница",
  sunflower: "Подсолнечник",
  potato: "Картофель",
};

const CROP_STAR_SVG = `<span class="crop-star" title="Своя культура" aria-label="своя культура"><svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M12 3L13.4302 8.31181C13.6047 8.96 13.692 9.28409 13.8642 9.54905C14.0166 9.78349 14.2165 9.98336 14.451 10.1358C14.7159 10.308 15.04 10.3953 15.6882 10.5698L21 12L15.6882 13.4302C15.04 13.6047 14.7159 13.692 14.451 13.8642C14.2165 14.0166 14.0166 14.2165 13.8642 14.451C13.692 14.7159 13.6047 15.04 13.4302 15.6882L12 21L10.5698 15.6882C10.3953 15.04 10.308 14.7159 10.1358 14.451C9.98336 14.2165 9.78349 14.0166 9.54905 13.8642C9.28409 13.692 8.96 13.6047 8.31181 13.4302L3 12L8.31181 10.5698C8.96 10.3953 9.28409 10.308 9.54905 10.1358C9.78349 9.98336 9.98336 9.78349 10.1358 9.54905C10.308 9.28409 10.3953 8.96 10.5698 8.31181L12 3Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></span>`;

function storageKey() {
  return `ttz_custom_crops_${getCurrentUser()?.email || "anon"}`;
}

export function getCustomCrops() {
  try {
    const value = JSON.parse(localStorage.getItem(storageKey()) || "{}");
    return value && typeof value === "object" ? value : {};
  } catch {
    return {};
  }
}

function saveCustomCrops(map) {
  try {
    localStorage.setItem(storageKey(), JSON.stringify(map || {}));
  } catch {
    /* storage unavailable: the list lives until reload */
  }
}

const sameName = (a, b) => String(a).trim().toLowerCase() === String(b).trim().toLowerCase();

export function isBuiltinCrop(label) {
  return Object.values(BUILTIN_CROP_LABELS).some((v) => sameName(v, label));
}

export function isCustomCrop(label) {
  return !!label && !isBuiltinCrop(label) && Object.values(getCustomCrops()).some((v) => sameName(v, label));
}

/** Built-in crops, then the user's own ones (marked ✦ in the select, as in the reference). */
export function getAllCropOptions() {
  const list = Object.values(BUILTIN_CROP_LABELS).map((label) => ({ label, custom: false }));
  Object.values(getCustomCrops()).forEach((label) => {
    if (!list.some((item) => sameName(item.label, label))) list.push({ label, custom: true });
  });
  return list;
}

/** Adds an own crop; returns its name (an existing one with the same name is reused). */
export function addCustomCrop(label) {
  const name = String(label || "").trim();
  if (!name) return null;
  const builtin = Object.values(BUILTIN_CROP_LABELS).find((v) => sameName(v, name));
  if (builtin) return builtin;
  const map = getCustomCrops();
  const existing = Object.values(map).find((v) => sameName(v, name));
  if (existing) return existing;
  map[`custom_${Date.now().toString(36)}`] = name;
  saveCustomCrops(map);
  return name;
}

export function deleteCustomCrop(key) {
  const map = getCustomCrops();
  if (!(key in map)) return false;
  delete map[key];
  saveCustomCrops(map);
  return true;
}

/** Crop for captions on the map: own crops get a star. */
export function formatCropHtml(label) {
  if (!label) return "";
  return isCustomCrop(label) ? `${escapeHtml(label)}${CROP_STAR_SVG}` : escapeHtml(label);
}

export function cropOptionsHtml(current) {
  const options = getAllCropOptions();
  const known = options.some((o) => sameName(o.label, current || ""));
  const extra = current && !known ? [{ label: current, custom: false }] : [];
  return (
    '<option value="">— Выберите культуру —</option>' +
    [...options, ...extra]
      .map((o) => `<option value="${escapeHtml(o.label)}">${escapeHtml(o.label)}${o.custom ? " ✦" : ""}</option>`)
      .join("") +
    '<option value="__manage__">⚙ Свои культуры…</option>'
  );
}
