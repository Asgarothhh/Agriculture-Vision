import { api, apiForm } from "./client.js";

export function mapModelCode(architecture) {
  if (architecture === "yolo" || architecture === "yolo_seg_26") return "yolo_seg_26";
  return "segformer";
}

export function createTask({ file, model, confidence, aoi, geoBounds }) {
  const form = new FormData();
  form.append("file", file, file.name || "upload.png");
  form.append("model", mapModelCode(model));
  form.append("confidence", String(confidence));
  if (aoi) form.append("aoi", JSON.stringify(aoi));
  if (geoBounds) form.append("geo_bounds", JSON.stringify(geoBounds));
  return apiForm("/api/v1/tasks/", form);
}

export function getTask(id) {
  return api(`/api/v1/tasks/${id}`);
}

export function listTasks() {
  return api("/api/v1/tasks/");
}

export function taskResult(id) {
  return api(`/api/v1/tasks/${id}/result`);
}

export function publishToLayers(id, classIds) {
  return api(`/api/v1/tasks/${id}/to-layers`, {
    method: "POST",
    body: JSON.stringify({ class_ids: classIds?.length ? classIds : null }),
  });
}

export function modelsHealth() {
  return api("/api/v1/models/health");
}

export function listClasses() {
  return api("/api/v1/classes/");
}

export async function pollTask(id, { intervalMs = 1500, timeoutMs = 180000, onProgress } = {}) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const task = await getTask(id);
    onProgress?.(task);
    if (task.status === "COMPLETED" || task.status === "FAILED") return task;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error("Истекло время ожидания обработки");
}
