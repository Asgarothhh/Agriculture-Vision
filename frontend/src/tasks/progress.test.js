import { describe, expect, it } from "vitest";
import { SEG_STAGES, humanizeSegError, mlPillState, mlPillTitle, taskStage } from "./progress.js";
import { withTimeout } from "../ui.js";

describe("taskStage", () => {
  it("maps server task states onto a monotonic bar", () => {
    const pending = taskStage({ status: "PENDING", progress: 0 });
    const early = taskStage({ status: "PROCESSING", progress: 10 });
    const late = taskStage({ status: "PROCESSING", progress: 70 });
    const done = taskStage({ status: "COMPLETED", progress: 100 });
    const seq = [
      SEG_STAGES.health.percent,
      SEG_STAGES.capture.percent,
      SEG_STAGES.upload.percent,
      pending.percent,
      early.percent,
      late.percent,
      done.percent,
      SEG_STAGES.publish.percent,
      SEG_STAGES.done.percent,
    ];
    expect([...seq].sort((a, b) => a - b)).toEqual(seq);
    expect(late.text).toContain("70%");
    expect(pending.text).toMatch(/очеред/i);
  });

  it("clamps bogus progress values", () => {
    expect(taskStage({ status: "PROCESSING", progress: 500 }).percent).toBe(90);
    expect(taskStage({ status: "PROCESSING", progress: "x" }).percent).toBe(35);
  });
});

describe("humanizeSegError", () => {
  it("explains Firefox tainted-canvas errors instead of the raw text", () => {
    const err = new Error("The operation is insecure.");
    err.name = "SecurityError";
    const text = humanizeSegError(err);
    expect(text).not.toBe("The operation is insecure.");
    expect(text).toContain("SecurityError");
  });

  it("maps network failures and keeps ordinary messages", () => {
    expect(humanizeSegError(new TypeError("NetworkError when attempting to fetch resource."))).toBe(
      "Нет связи с сервером",
    );
    expect(humanizeSegError(new Error("Модель недоступна"))).toBe("Модель недоступна");
  });
});

describe("withTimeout", () => {
  it("rejects with the given message when the promise hangs", async () => {
    await expect(withTimeout(new Promise(() => {}), 10, "timeout!")).rejects.toThrow("timeout!");
  });

  it("resolves when the promise settles in time", async () => {
    await expect(withTimeout(Promise.resolve(42), 1000, "timeout!")).resolves.toBe(42);
  });
});

describe("mlPillState", () => {
  const ready = {
    status: "ready",
    models: [
      { code: "segformer", loaded: true },
      { code: "yolo_seg_26", loaded: false, error: "weights file not found" },
    ],
  };

  it("shows loaded models, loading, unavailable and offline states", () => {
    expect(mlPillState(ready)).toEqual({ text: "ML · segformer", cls: "status-online" });
    expect(mlPillState({ status: "loading", models: [] }).text).toBe("ML · загрузка моделей");
    expect(mlPillState({ status: "unavailable", models: [] }).text).toBe("ML недоступен");
    expect(mlPillState(null, { failed: true }).text).toBe("ML недоступен");
    expect(mlPillState(ready, { online: false }).text).toBe("ML оффлайн");
  });

  it("puts the reason of each model into the tooltip", () => {
    expect(mlPillTitle(ready)).toBe("segformer: загружена\nyolo_seg_26: weights file not found");
  });
});

describe("scale-matched segmentation hints", () => {
  it("shows the window being processed", async () => {
    const { taskStage } = await import("./progress.js");
    const stage = taskStage({ status: "PROCESSING", progress: 50, info: { windows_done: 7, windows_total: 49 } });
    expect(stage.text).toBe("Сегментация на сервере: окно 7 из 49");
    expect(taskStage({ status: "PROCESSING", progress: 50, info: {} }).text).toContain("50%");
  });

  it("hints to select a smaller area when the server had to go coarser", async () => {
    const { scaleHint } = await import("./progress.js");
    expect(scaleHint({ work_m_per_px: 0.12, target_m_per_px: 0.1 })).toBe("");
    expect(scaleHint(null)).toBe("");
    const hint = scaleHint({ work_m_per_px: 0.238, target_m_per_px: 0.1, work_size: [2646, 2646] });
    expect(hint).toContain("0,24 м/пикс");
    expect(hint).toContain("до ~16 га");
  });

  it("measures the area size in km", async () => {
    const { areaSideKm } = await import("./progress.js");
    const km = areaSideKm({ west: 27.0, east: 27.03, south: 53.9, north: 53.91 });
    expect(km).toBeGreaterThan(1.9);
    expect(km).toBeLessThan(2.1);
  });
});
