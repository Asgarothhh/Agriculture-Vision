import { describe, expect, it } from "vitest";
import { SEG_STAGES, humanizeSegError, taskStage } from "./progress.js";
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
