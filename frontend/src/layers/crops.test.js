import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../auth/session.js", () => ({ getCurrentUser: () => ({ email: "user@example.test" }) }));

const crops = await import("./crops.js");

describe("crops (reference «Культура» behaviour)", () => {
  beforeEach(() => localStorage.clear());

  it("keeps own crops per email in the reference format {key: label}", () => {
    expect(crops.addCustomCrop("  Гречиха ")).toBe("Гречиха");
    const stored = JSON.parse(localStorage.getItem("ttz_custom_crops_user@example.test"));
    expect(Object.values(stored)).toEqual(["Гречиха"]);
    expect(Object.keys(stored)[0]).toMatch(/^custom_/);
  });

  it("reuses built-in and existing names instead of duplicating", () => {
    expect(crops.addCustomCrop("пшеница")).toBe("Пшеница");
    crops.addCustomCrop("Гречиха");
    expect(crops.addCustomCrop("гречиха")).toBe("Гречиха");
    expect(Object.keys(crops.getCustomCrops())).toHaveLength(1);
    expect(crops.addCustomCrop("   ")).toBeNull();
  });

  it("marks own crops with a star, built-in ones without", () => {
    crops.addCustomCrop("Гречиха");
    expect(crops.isCustomCrop("Гречиха")).toBe(true);
    expect(crops.isCustomCrop("Пшеница")).toBe(false);
    expect(crops.formatCropHtml("Гречиха")).toContain("crop-star");
    expect(crops.formatCropHtml("Пшеница")).toBe("Пшеница");
    expect(crops.formatCropHtml("<b>")).toBe("&lt;b&gt;");
  });

  it("builds the select: placeholder, built-ins, own ✦, the object's unknown crop, manage item", () => {
    crops.addCustomCrop("Гречиха");
    const html = crops.cropOptionsHtml("Лён");
    expect(html.startsWith('<option value="">— Выберите культуру —</option>')).toBe(true);
    expect(html).toContain(">Гречиха ✦<");
    expect(html).toContain('value="Лён"');
    expect(html.endsWith('<option value="__manage__">⚙ Свои культуры…</option>')).toBe(true);
  });

  it("deletes an own crop by key", () => {
    crops.addCustomCrop("Гречиха");
    const [key] = Object.keys(crops.getCustomCrops());
    expect(crops.deleteCustomCrop(key)).toBe(true);
    expect(crops.getCustomCrops()).toEqual({});
    expect(crops.deleteCustomCrop("missing")).toBe(false);
  });
});
