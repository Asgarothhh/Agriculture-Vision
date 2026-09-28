import { isSecurityError } from "../ui.js";

// Share of the whole segmentation run shown by the progress bar at each client stage.
export const SEG_STAGES = {
  health: { percent: 5, text: "Проверка ML-сервера…" },
  capture: { percent: 15, text: "Захват карты…" },
  upload: { percent: 30, text: "Отправка снимка на сервер…" },
  publish: { percent: 93, text: "Публикация результатов на карту…" },
  done: { percent: 100, text: "Готово" },
};

// Server-side task progress (0–100) is mapped into this part of the bar.
const TASK_FROM = 35;
const TASK_TO = 90;

export function clampPercent(value) {
  return Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
}

export function taskStage(task) {
  const progress = clampPercent(task?.progress);
  if (task?.status === "PENDING") {
    return { percent: TASK_FROM, text: "В очереди на обработку…" };
  }
  if (task?.status === "PROCESSING") {
    const done = Number(task?.info?.windows_done) || 0;
    const total = Number(task?.info?.windows_total) || 0;
    return {
      percent: TASK_FROM + Math.round((progress * (TASK_TO - TASK_FROM)) / 100),
      text:
        total > 1 && done > 0
          ? `Сегментация на сервере: окно ${Math.min(done, total)} из ${total}`
          : `Сегментация на сервере… ${progress}%`,
    };
  }
  return { percent: TASK_TO, text: "Обработка на сервере завершена" };
}

function formatMpp(value) {
  return Number(value).toFixed(2).replace(".", ",");
}

/**
 * The models are trained at ~0.1 m/px. When the server had to process a large area at a
 * noticeably coarser scale (window budget on CPU), tell the user how to get sharper edges.
 */
export function scaleHint(info) {
  const work = Number(info?.work_m_per_px);
  const target = Number(info?.target_m_per_px) || 0.1;
  if (!work || work <= target * 1.5) return "";
  const size = Array.isArray(info?.work_size) ? Math.max(...info.work_size.map(Number)) : 0;
  // Area that fits the same window budget at ~1.5× the training scale.
  const sideM = size ? size * target * 1.5 : 0;
  const ha = sideM ? Math.max(1, Math.round((sideM * sideM) / 10000)) : 0;
  return (
    `Большая область: обработано в масштабе ${formatMpp(work)} м/пикс (модель обучена на ${formatMpp(target)}).` +
    (ha ? ` Для точных границ выделите поле поменьше — до ~${ha} га.` : " Для точных границ выделите поле поменьше.")
  );
}

/** Rough ground size of the segmentation area (km on its longer side). */
export function areaSideKm(bounds) {
  if (!bounds) return 0;
  const lat = ((bounds.north + bounds.south) / 2) * (Math.PI / 180);
  const w = Math.abs(bounds.east - bounds.west) * 111.32 * Math.cos(lat);
  const h = Math.abs(bounds.north - bounds.south) * 111.32;
  return Math.max(w, h);
}

/**
 * Header pill for the ML server (spec 4): «ML <models>» when ready, «ML недоступен»
 * when the server does not answer, «ML оффлайн» when the user has no internet.
 */
export function mlPillState(health, { online = true, failed = false } = {}) {
  if (!online) return { text: "ML оффлайн", cls: "status-offline" };
  if (failed || !health) return { text: "ML недоступен", cls: "status-idle" };
  if (health.status === "loading") return { text: "ML · загрузка моделей", cls: "status-idle" };
  if (health.status !== "ready") return { text: "ML недоступен", cls: "status-idle" };
  const loaded = (health.models || []).filter((m) => m.loaded).map((m) => m.code);
  return { text: `ML · ${loaded.join(", ") || "готов"}`, cls: "status-online" };
}

export function mlPillTitle(health) {
  const models = health?.models || [];
  const lines = models.map((m) => `${m.code}: ${m.loaded ? "загружена" : m.error || "не загружена"}`);
  return lines.join("\n") || "Нет данных от ML-сервера";
}

export function humanizeSegError(err) {
  if (isSecurityError(err)) {
    return "Браузер запретил чтение изображения карты (SecurityError). Обновите страницу с очисткой кэша (Ctrl+F5); если ошибка повторится — смените подложку.";
  }
  if (err?.status === 401) return "Сессия истекла — войдите снова";
  if (err instanceof TypeError && /fetch/i.test(String(err.message || ""))) {
    return "Нет связи с сервером";
  }
  return err?.message || "Сегментация не удалась";
}
