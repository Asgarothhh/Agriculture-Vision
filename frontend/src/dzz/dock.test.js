import { describe, expect, it } from "vitest";
import { dzzDockSummaryText, normalizeDzzSite } from "./dock.js";
import { humanizeDzzSiteName, parseDzzSites } from "./urls.js";

describe("dzz sites", () => {
  it("humanizes catalogue names like the reference", () => {
    expect(humanizeDzzSiteName("berestovica_polya")).toBe("Берестовица");
    expect(humanizeDzzSiteName("Some_rn_district_polya")).toBe("Some р-н district");
    expect(humanizeDzzSiteName("")).toBe("Участок");
  });

  it("parses ImageServer query results with human titles", () => {
    const sites = parseDzzSites({
      features: [
        { attributes: { OBJECTID: 7, Name: "Smolevichy_polya" }, geometry: { rings: [[[27, 53], [28, 53], [28, 54], [27, 53]]] } },
      ],
    });
    expect(sites[0]).toMatchObject({ id: 7, title: "Смолевичи", center: [53.5, 27.5] });
  });

  it("normalizes sites from both sources and drops ones without a centre", () => {
    expect(normalizeDzzSite({ id: 3, name: "myadel_polya", center: [54.8, 26.9] })).toMatchObject({
      id: "3",
      title: "Мядель",
      lat: 54.8,
      lng: 26.9,
    });
    expect(normalizeDzzSite({ id: 4, name: "x" })).toBeNull();
  });

  it("summarises the collapsed dock", () => {
    const site = { title: "Берестовица" };
    expect(dzzDockSummaryText({ mode: "tiles", tile: { z: 14, x: 9345, y: 5271 } })).toBe("14/9345/5271");
    expect(dzzDockSummaryText({ mode: "sites", activeSite: site, count: 4 })).toBe("Берестовица");
    expect(dzzDockSummaryText({ mode: "sites", count: 4 })).toBe("4 участок(ов)");
    expect(dzzDockSummaryText({ mode: "sites", count: 0 })).toBe("dzz.by");
  });
});
