import { api, apiForm } from "./client.js";

export function listLayers(search) {
  const q = search ? `?search=${encodeURIComponent(search)}` : "";
  return api(`/api/v1/layers/${q}`);
}

export function createLayer(payload) {
  return api("/api/v1/layers/", { method: "POST", body: JSON.stringify(payload) });
}

export function patchLayer(id, payload) {
  return api(`/api/v1/layers/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function deleteLayer(id) {
  return api(`/api/v1/layers/${id}`, { method: "DELETE" });
}

export function listLayerObjects(layerId) {
  return api(`/api/v1/layers/${layerId}/objects`);
}

export function addObject(layerId, payload) {
  return api(`/api/v1/layers/${layerId}/objects`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getObject(id) {
  return api(`/api/v1/objects/${id}`);
}

export function patchObject(id, payload) {
  return api(`/api/v1/objects/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function deleteObject(id) {
  return api(`/api/v1/objects/${id}`, { method: "DELETE" });
}

export function mergeObjects(objectIds) {
  return api("/api/v1/objects/merge", {
    method: "POST",
    body: JSON.stringify({ object_ids: objectIds }),
  });
}

export function listFolders() {
  return api("/api/v1/folders/");
}

export function createFolder(name) {
  return api("/api/v1/folders/", { method: "POST", body: JSON.stringify({ name }) });
}

export function patchFolder(id, payload) {
  return api(`/api/v1/folders/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function deleteFolder(id) {
  return api(`/api/v1/folders/${id}`, { method: "DELETE" });
}

export function moveFolderItem(folderId, payload) {
  return api(`/api/v1/folders/${folderId}/items`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function importLayer(file) {
  const form = new FormData();
  form.append("file", file, file.name);
  return apiForm("/api/v1/layers/import", form);
}

export function exportLayers(format, layerIds) {
  const mapped = format === "shp" ? "shapefile" : format;
  return api("/api/v1/layers/export", {
    method: "POST",
    body: JSON.stringify({ format: mapped, layer_ids: layerIds || null }),
  });
}
