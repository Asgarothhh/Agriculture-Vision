import * as tasksApi from "../api/tasks.js";
import { $, confirmModal, showToast, dbg } from "../ui.js";
import { captureMapJpeg, clearAoi, getAoiGeoJson, getViewBounds } from "../map/map.js";
import { loadMapData, selectedClassIds } from "../layers/store.js";
import { clearUndo } from "../map/undo.js";

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
  clearUndo();
  return task;
}

export async function startUploadProcessing() {
  if (!uploadFile) return;
  const bounds = getViewBounds();
  const aoi = getAoiGeoJson();
  if (!aoi) {
    const ok = await confirmModal({
      title: "Область не выделена",
      bodyHtml:
        "<p>Область на карте не выделена. Результат распознавания разместится по текущему виду карты, а не по реальному расположению снимка — координаты будут географически неверными.</p>",
      confirmLabel: "Продолжить всё равно",
      cancelLabel: "Отмена, выделю область",
    });
    if (!ok) return;
  }
  try {
    $("upload-process-btn").disabled = true;
    setProgress("upload-progress-bar", "upload-progress", 8);
    await runTask({ file: uploadFile, geoBounds: bounds, aoi, architecture: selectedArchitecture() });
    showToast("Обработка завершена");
  } catch (err) {
    showToast(err.message, true);
  } finally {
    setProgress("upload-progress-bar", "upload-progress", null);
    $("upload-process-btn").disabled = !uploadFile;
  }
}

export async function runSegmentation(architecture) {
  // #region agent log
  dbg("H3", "seg-start", { architecture, status: $("map-seg-status")?.textContent });
  // #endregion
  setProgress("map-seg-progress-bar", "map-seg-progress", 8);
  try {
    if ($("map-seg-status")) $("map-seg-status").textContent = "Захват карты…";
    const health = await tasksApi.modelsHealth();
    const loaded = (health.models || []).filter((m) => m.loaded).map((m) => m.code);
    // #region agent log
    dbg("H4", "seg-health", { status: health.status, loaded, architecture });
    // #endregion
    const code = architecture === "yolo" ? "yolo_seg_26" : "segformer";
    if (health.status !== "ready") throw new Error(health.detail || "На ML-сервере нет весов моделей");
    if (!loaded.includes(code) && loaded.length) {
      throw new Error(`Модель «${architecture}» недоступна. Есть: ${loaded.join(", ")}`);
    }
    setProgress("map-seg-progress-bar", "map-seg-progress", 18);
    const file = await captureMapJpeg();
    // #region agent log
    dbg("H3", "seg-captured", { bytes: file?.size, type: file?.type });
    // #endregion
    setProgress("map-seg-progress-bar", "map-seg-progress", 30);
    if ($("map-seg-status")) $("map-seg-status").textContent = "Отправка на сервер…";
    const geoBounds = getViewBounds();
    const aoi = getAoiGeoJson();
    await runTask({ file, geoBounds, aoi, architecture });
    setProgress("map-seg-progress-bar", "map-seg-progress", 100);
    showToast("Сегментация завершена");
    clearAoi();
  } catch (err) {
    // #region agent log
    dbg("H3", "seg-error", { message: err?.message, stuck: $("map-seg-status")?.textContent });
    // #endregion
    showToast(err.message, true);
    if ($("map-seg-status")) $("map-seg-status").textContent = err.message;
  } finally {
    setTimeout(() => setProgress("map-seg-progress-bar", "map-seg-progress", null), 600);
    if ($("map-seg-status") && $("map-seg-status").textContent === "Захват карты…") {
      $("map-seg-status").textContent = "Выделите область на карте или сегментируйте весь кадр";
    }
  }
}

export async function refreshMlHealth() {
  const el = $("status-ml");
  try {
    const health = await tasksApi.modelsHealth();
    const loaded = (health.models || []).filter((m) => m.loaded).map((m) => m.code);
    el.classList.remove("status-online", "status-idle", "status-offline", "offline");
    if (health.status === "ready") {
      el.textContent = `ML · ${loaded.join(",") || "ready"}`;
      el.classList.add("status-online");
    } else {
      el.textContent = "ML недоступен";
      el.classList.add("status-idle");
    }
    el.title = JSON.stringify(health);
    // #region agent log
    dbg("H4", "ml-health", { status: health.status, loaded, text: el.textContent, className: el.className });
    // #endregion
  } catch (err) {
    // #region agent log
    dbg("H4", "ml-health-fail", { message: err?.message });
    // #endregion
    el.textContent = "ML недоступен";
    el.classList.remove("status-online");
    el.classList.add("status-idle");
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
