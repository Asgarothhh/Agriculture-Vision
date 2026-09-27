import { describe, expect, it } from "vitest";
import { hasTaskResult, historyCategories, passwordChangeError } from "./profile.js";

describe("passwordChangeError", () => {
  it("allows saving the profile without touching the password", () => {
    expect(passwordChangeError({ current: "", password: "", repeat: "" })).toBeNull();
  });

  it("requires the current password for any password change", () => {
    expect(passwordChangeError({ current: "", password: "NewPass1!", repeat: "NewPass1!" })).toMatch(/текущий/);
    expect(passwordChangeError({ current: "", password: "", repeat: "NewPass1!" })).toMatch(/текущий/);
  });

  it("does not silently ignore a filled current password without a new one", () => {
    expect(passwordChangeError({ current: "OldPass1!", password: "", repeat: "" })).toMatch(/новый/i);
  });

  it("checks strength, match and difference from the current password", () => {
    expect(passwordChangeError({ current: "OldPass1!", password: "short", repeat: "short" })).toMatch(/8 символов/);
    expect(passwordChangeError({ current: "OldPass1!", password: "NewPass1!", repeat: "NewPass2!" })).toBe(
      "Пароли не совпадают",
    );
    expect(passwordChangeError({ current: "OldPass1!", password: "OldPass1!", repeat: "OldPass1!" })).toMatch(
      /совпадает/,
    );
    expect(passwordChangeError({ current: "OldPass1!", password: "Ёжик-пароль1", repeat: "Ёжик-пароль1" })).toBeNull();
  });
});

describe("historyCategories", () => {
  it("sends every checked category, nothing for «Все», and marks an empty choice", () => {
    expect(historyCategories(["account", "export"], false)).toEqual(["account", "export"]);
    expect(historyCategories(["tool", "process", "export"], false)).toEqual(["map_tools", "upload_processing", "export"]);
    expect(historyCategories(["account", "tool", "export", "process"], true)).toEqual([]);
    expect(historyCategories([], false)).toBeNull();
  });
});

describe("hasTaskResult", () => {
  it("offers open/download only for finished processing", () => {
    expect(hasTaskResult({ action: "Обработка снимка завершена", payload: { task_id: "t", status: "COMPLETED" } })).toBe(
      true,
    );
    expect(hasTaskResult({ action: "Обработка снимка завершена", payload: { task_id: "t" } })).toBe(true);
    expect(hasTaskResult({ action: "Загрузка снимка a.png", payload: { task_id: "t" } })).toBe(false);
    expect(hasTaskResult({ action: "Ошибка обработки снимка", payload: { task_id: "t", status: "FAILED" } })).toBe(
      false,
    );
    expect(hasTaskResult({ action: "Вход в систему", payload: null })).toBe(false);
  });
});
