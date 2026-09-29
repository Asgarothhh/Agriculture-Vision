import { describe, expect, it } from "vitest";
import { CLASS_CHECKBOXES, legendItems, selectedClassIds } from "./store.js";
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

describe("legendItems", () => {
  const count = (l) => l.n;
  const folders = [{ id: "F1", name: "Поле Север" }, { id: "F2", name: "Пустая папка" }];

  it("groups layers of a folder under the folder name and skips empty layers", () => {
    const layers = [
      { id: "a", name: "Культурные растения", color: "#43A047", folder_id: null, n: 3 },
      { id: "b", name: "Сорняки", color: "#C62828", folder_id: "F1", n: 2 },
      { id: "c", name: "Водоток", color: "#00ACC1", folder_id: "F1", n: 1 },
      { id: "d", name: "Пустой", color: "#000000", folder_id: null, n: 0 },
      { id: "e", name: "В пустой папке", color: "#111111", folder_id: "F2", n: 0 },
    ];
    expect(legendItems(layers, folders, count)).toEqual([
      { name: "Поле Север", color: "#C62828" },
      { name: "Культурные растения", color: "#43A047" },
    ]);
  });

  it("keeps hidden layers and hidden folders, like the reference", () => {
    const layers = [
      { id: "a", name: "Скрытый", color: "#111111", folder_id: null, n: 2, is_visible: false },
      { id: "b", name: "В скрытой папке", color: "#222222", folder_id: "F1", n: 2 },
    ];
    const hiddenFolder = [{ id: "F1", name: "Поле Север", is_visible: false }];
    expect(legendItems(layers, hiddenFolder, count)).toEqual([
      { name: "Поле Север", color: "#222222" },
      { name: "Скрытый", color: "#111111" },
    ]);
  });

  it("keeps a layer whose folder no longer exists", () => {
    const layers = [{ id: "x", name: "Слой", color: "#123456", folder_id: "gone", n: 1 }];
    expect(legendItems(layers, folders, count)).toEqual([{ name: "Слой", color: "#123456" }]);
  });
});

describe("display settings per email (reference ttz_display_<email>)", () => {
  it("keeps known fields within the slider ranges and fills gaps with defaults", async () => {
    const { normalizeDisplay, DISPLAY_DEFAULTS } = await import("./store.js");
    expect(normalizeDisplay(null)).toEqual({ ...DISPLAY_DEFAULTS });
    // a legacy set with only the line width must not turn the others into minimums
    expect(normalizeDisplay({ lineWidth: "4", pointSize: null, fillOpacity: null, coordColor: null, basemap: null })).toEqual({
      ...DISPLAY_DEFAULTS,
      lineWidth: 4,
    });
    expect(normalizeDisplay({ fillOpacity: 5, pointSize: 99, coordColor: "red", basemap: "google" })).toEqual({
      ...DISPLAY_DEFAULTS,
      fillOpacity: 0.9,
      pointSize: 30,
    });
  });
});
