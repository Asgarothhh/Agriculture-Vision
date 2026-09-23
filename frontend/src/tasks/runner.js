import * as tasksApi from "../api/tasks.js";
import { $, showToast } from "../ui.js";
import { captureMapJpeg, clearAoi, getAoiGeoJson, getViewBounds } from "../map/map.js";
import { loadMapData, selectedClassIds } from "../layers/store.js";

let uploadFile = null;

export function handleUploadFile(file) {
  uploadFile = file || null;
  $("upload-status").textContent = file ? file.name : "";
  $("upload-process-btn").disabled = !file;
}

function selectedArchitecture() {
  return document.querySelector('input[name="seg-architecture"]:checked')?.value || "segformer";
}

function threshold() {
  return Math.min(0.95, Math.max(0.05, Number($("seg-threshold")?.value || 40) / 100));
}

export function onSegArchitectureChange() {
  localStorage.setItem("ttz_ml_architecture", selectedArchitecture());
}

export function onSegThresholdInput(value) {
  $("seg-threshold-value").innerText = `${value}%`;
  localStorage.setItem("ttz_seg_threshold", String(value));
}

function setProgress(idBar, idWrap, value) {
  const wrap = $(idWrap);
  const bar = $(idBar);
  if (wrap) wrap.style.display = value == null ? "none" : "block";
  if (bar) bar.style.width = `${value || 0}%`;
}

export async function runTask({ file, geoBounds, aoi, architecture }) {
  const created = await tasksApi.createTask({
    file,
    model: architecture || selectedArchitecture(),
    confidence: threshold(),
    aoi,
    geoBounds,
  });
  const taskId = created.task_id || created.id;
  const task = await tasksApi.pollTask(taskId, {
    onProgress: (item) => {
      setProgress("map-seg-progress-bar", "map-seg-progress", item.progress || 10);
      setProgress("upload-progress-bar", "upload-progress", item.progress || 10);
      if ($("map-seg-status")) $("map-seg-status").textContent = `${item.status} ${item.progress || 0}%`;
    },
  });
  if (task.status === "FAILED") throw new Error(task.error || "Обработка не удалась");
  await tasksApi.publishToLayers(taskId, selectedClassIds());
  await loadMapData();
  return task;
}

export async function startUploadProcessing() {
  if (!uploadFile) return;
  try {
    $("upload-process-btn").disabled = true;
    await runTask({ file: uploadFile, architecture: selectedArchitecture() });
    showToast("Обработка завершена");
  } catch (err) {
    showToast(err.message, true);
  } finally {
    setProgress("upload-progress-bar", "upload-progress", null);
    $("upload-process-btn").disabled = !uploadFile;
  }
}

export async function runSegmentation(architecture) {
  try {
    if ($("map-seg-status")) $("map-seg-status").textContent = "Захват карты…";
    const file = await captureMapJpeg();
    const geoBounds = getViewBounds();
    const aoi = getAoiGeoJson();
    await runTask({ file, geoBounds, aoi, architecture });
    showToast("Сегментация завершена");
    clearAoi();
  } catch (err) {
    showToast(err.message, true);
  } finally {
    setProgress("map-seg-progress-bar", "map-seg-progress", null);
  }
}

export async function refreshMlHealth() {
  const el = $("status-ml");
  try {
    const health = await tasksApi.modelsHealth();
    const loaded = (health.models || []).filter((m) => m.loaded).map((m) => m.code);
    el.textContent = health.status === "ready" ? `ML · ${loaded.join(",") || "ready"}` : "ML · нет";
    el.title = JSON.stringify(health);
    el.classList.toggle("offline", health.status !== "ready");
  } catch {
    el.textContent = "ML · нет";
    el.classList.add("offline");
  }
}

export async function renderClassToggles() {
  try {
    const classes = await tasksApi.listClasses();
    const host = document.querySelector("#panel-settings .settings-section-title");
    if (!host) return;
    classes
      .filter((c) => !c.is_crop)
      .forEach((cls) => {
        const id = `opt-class-${cls.id}`;
        if ($(id)) return;
      });
  } catch {
    /* keep static checkboxes */
  }
}
