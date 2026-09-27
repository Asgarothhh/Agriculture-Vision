import * as tasksApi from "../api/tasks.js";
import { $, confirmModal, showToast, withTimeout } from "../ui.js";
import { captureMapJpeg, clearAoi, getAoiGeoJson, getViewBounds } from "../map/map.js";
import { loadMapData, selectedClassIds } from "../layers/store.js";
import { clearUndo } from "../map/undo.js";
import { SEG_STAGES, clampPercent, humanizeSegError, taskStage } from "./progress.js";

const HEALTH_TIMEOUT_MS = 10000;

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

let segRunning = false;
let segPercent = 0;

function segStatus(text) {
  const el = $("map-seg-status");
  if (el) el.textContent = text;
}

function segProgress(percent, { error = false } = {}) {
  const wrap = $("map-seg-progress");
  const summary = $("map-seg-summary");
  if (!wrap) return;
  if (percent == null) {
    wrap.hidden = true;
    wrap.classList.remove("error");
    if (summary) summary.textContent = "";
    return;
  }
  segPercent = clampPercent(percent);
  wrap.hidden = false;
  wrap.classList.toggle("error", error);
  wrap.setAttribute("aria-valuenow", String(segPercent));
  if ($("map-seg-progress-bar")) $("map-seg-progress-bar").style.width = `${segPercent}%`;
  if ($("map-seg-progress-pct")) $("map-seg-progress-pct").textContent = `${segPercent}%`;
  // Visible in the header when the panel is collapsed.
  if (summary) summary.textContent = error ? "ошибка" : `${segPercent}%`;
}

function segStage(stage) {
  segStatus(stage.text);
  segProgress(stage.percent);
}

function setSegButtonsDisabled(disabled) {
  ["btn-segment-yolo", "btn-segment-segformer", "map-btn-aoi", "map-btn-clear-aoi"].forEach((id) => {
    if ($(id)) $(id).disabled = disabled;
  });
}

export async function runTask({ file, geoBounds, aoi, architecture, onStage }) {
  const created = await tasksApi.createTask({
    file,
    model: architecture || selectedArchitecture(),
    confidence: threshold(),
    aoi,
    geoBounds,
  });
  const taskId = created.task_id || created.id;
  onStage?.(taskStage(created));
  const task = await tasksApi.pollTask(taskId, {
    onProgress: (item) => onStage?.(taskStage(item)),
  });
  if (task.status === "FAILED") {
    throw new Error(task.error ? `Ошибка обработки на сервере: ${task.error}` : "Обработка не удалась");
  }
  onStage?.(SEG_STAGES.publish);
  const published = await tasksApi.publishToLayers(taskId, selectedClassIds());
  await loadMapData();
  clearUndo();
  return { task, created: Number(published?.created) || 0 };
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
    setProgress("upload-progress-bar", "upload-progress", SEG_STAGES.upload.percent);
    await runTask({
      file: uploadFile,
      geoBounds: bounds,
      aoi,
      architecture: selectedArchitecture(),
      onStage: ({ percent }) => setProgress("upload-progress-bar", "upload-progress", percent),
    });
    showToast("Обработка завершена");
  } catch (err) {
    showToast(humanizeSegError(err), true);
  } finally {
    setProgress("upload-progress-bar", "upload-progress", null);
    $("upload-process-btn").disabled = !uploadFile;
  }
}

export async function runSegmentation(architecture) {
  if (segRunning) return;
  segRunning = true;
  setSegButtonsDisabled(true);
  let failed = false;
  try {
    segStage(SEG_STAGES.health);
    const health = await withTimeout(tasksApi.modelsHealth(), HEALTH_TIMEOUT_MS, "ML-сервер не ответил за 10 секунд");
    const models = health.models || [];
    const loaded = models.filter((m) => m.loaded).map((m) => m.code);
    const code = architecture === "yolo" ? "yolo_seg_26" : "segformer";
    if (!loaded.includes(code)) {
      if (health.status !== "ready") {
        const reason = models.find((m) => m.code === code)?.error;
        throw new Error(`ML-модели недоступны${reason ? `: ${reason}` : ""}`);
      }
      throw new Error(`Модель «${architecture}» недоступна. Есть: ${loaded.join(", ")}`);
    }
    segStage(SEG_STAGES.capture);
    const { file, geoBounds } = await captureMapJpeg();
    segStage(SEG_STAGES.upload);
    const { created } = await runTask({ file, geoBounds, aoi: getAoiGeoJson(), architecture, onStage: segStage });
    segProgress(SEG_STAGES.done.percent);
    const message = created
      ? `Сегментация завершена: добавлено объектов — ${created}`
      : "Сегментация завершена: объекты не найдены";
    segStatus(message);
    showToast(message);
    clearAoi();
  } catch (err) {
    failed = true;
    const message = humanizeSegError(err);
    segStatus(message);
    segProgress(segPercent, { error: true });
    showToast(message, true);
  } finally {
    segRunning = false;
    setSegButtonsDisabled(false);
    setTimeout(() => {
      if (!segRunning) segProgress(null);
    }, failed ? 5000 : 1500);
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
  } catch {
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
