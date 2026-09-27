import { describe, expect, it } from "vitest";
import { CLASS_CHECKBOXES, selectedClassIds } from "./store.js";
import { escapeHtml, validatePassword } from "../ui.js";

function fakeDocument(checked) {
  return {
    getElementById: (id) => (id in CLASS_CHECKBOXES ? { checked: checked.includes(id) } : null),
  };
}

describe("selectedClassIds", () => {
  it("maps the settings category checkboxes to recognition class ids", () => {
    expect(selectedClassIds(fakeDocument(["opt-crops", "opt-flood", "opt-obstacle"]))).toEqual([2, 4, 5, 6]);
    expect(selectedClassIds(fakeDocument([]))).toEqual([]);
  });

  it("covers every YOLO category of the model", () => {
    const all = selectedClassIds(fakeDocument(Object.keys(CLASS_CHECKBOXES)));
    for (const id of [2, 4, 21, 22, 23, 24, 25, 26, 27, 28]) expect(all).toContain(id);
  });
});

describe("ui helpers", () => {
  it("escapes markup coming from names and file names", () => {
    expect(escapeHtml(`<img src=x onerror="alert(1)">`)).toBe("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
    expect(escapeHtml(null)).toBe("");
  });

  it("uses the backend password rule (incl. ё/Ё)", () => {
    expect(validatePassword("Aa!aaaaa")).toBe(true);
    expect(validatePassword("ёжик-Пароль")).toBe(true);
    expect(validatePassword("aaaaaaa!")).toBe(false);
    expect(validatePassword("AAAAAAA!")).toBe(false);
    expect(validatePassword("Aaaaaaaa")).toBe(false);
    expect(validatePassword("Aa!")).toBe(false);
  });
});
