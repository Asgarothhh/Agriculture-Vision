import { afterEach, describe, expect, it, vi } from "vitest";
import {
  api,
  clearTokens,
  formatDetail,
  getAccessToken,
  setTokens,
} from "./client.js";
import { mapModelCode } from "./tasks.js";
import { dzzTileUrl, toSameOriginDzzUrl } from "./dzz.js";
import { DZZ_DEFAULT_SERVICE, getActiveBasemapTileUrl, dzzSession } from "../dzz/urls.js";

afterEach(() => {
  clearTokens();
  vi.unstubAllGlobals();
});

describe("formatDetail", () => {
  it("reads string detail", () => {
    expect(formatDetail({ detail: "Нет доступа" })).toBe("Нет доступа");
  });

  it("joins validation array", () => {
    expect(formatDetail({ detail: [{ msg: "a" }, { msg: "b" }] })).toBe("a; b");
  });
});

describe("tokens", () => {
  it("stores remember_me in localStorage", () => {
    setTokens({ access_token: "a", refresh_token: "r" }, true);
    expect(localStorage.getItem("av_access_token")).toBe("a");
    expect(sessionStorage.getItem("av_access_token")).toBeNull();
  });

  it("stores session tokens in sessionStorage", () => {
    setTokens({ access_token: "a", refresh_token: "r" }, false);
    expect(sessionStorage.getItem("av_access_token")).toBe("a");
    expect(localStorage.getItem("av_access_token")).toBeNull();
  });
});

describe("mapModelCode", () => {
  it("maps UI yolo to API yolo_seg_26", () => {
    expect(mapModelCode("yolo")).toBe("yolo_seg_26");
    expect(mapModelCode("segformer")).toBe("segformer");
  });
});

describe("dzzTileUrl", () => {
  it("rewrites dzz.by tiles to the same-origin proxy without credentials", () => {
    dzzSession.serviceRoot = DZZ_DEFAULT_SERVICE;
    dzzSession.wmtsTemplate = "";
    const url = dzzTileUrl(12, 2400, 1309);
    expect(url).toBe(
      "/api/v1/dzz/arcgis/rest/services/georesursDDZ/Polya_all/ImageServer/tile/4/1309/2400",
    );
    expect(url).not.toMatch(/password|login|token=/i);
    expect(
      toSameOriginDzzUrl(
        "https://www.dzz.by/arcgis/rest/services/georesursDDZ/Polya_all/ImageServer/tile/4/1309/2400",
      ),
    ).toBe(url);
  });

  it("uses exportImage outside the cached zoom range", () => {
    dzzSession.serviceRoot = DZZ_DEFAULT_SERVICE;
    dzzSession.wmtsTemplate = "";
    const url = getActiveBasemapTileUrl(8, 140, 85);
    expect(url).toContain("/exportImage?");
    expect(toSameOriginDzzUrl(url).startsWith("/api/v1/dzz/arcgis/")).toBe(true);
  });
});

describe("api refresh", () => {
  it("retries once after 401 with refresh token", async () => {
    setTokens({ access_token: "old", refresh_token: "ref" }, false);
    const fetchMock = vi.fn(async (url, options) => {
      if (String(url).includes("/auth/refresh")) {
        return {
          ok: true,
          status: 200,
          headers: new Headers({ "content-type": "application/json" }),
          text: async () => JSON.stringify({ access_token: "new", refresh_token: "ref2" }),
        };
      }
      const auth = options.headers.get("Authorization");
      if (auth === "Bearer old") {
        return {
          ok: false,
          status: 401,
          headers: new Headers({ "content-type": "application/json" }),
          text: async () => JSON.stringify({ detail: "expired" }),
        };
      }
      return {
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "application/json" }),
        text: async () => JSON.stringify({ ok: true }),
      };
    });
    vi.stubGlobal("fetch", fetchMock);
    const result = await api("/api/v1/users/me");
    expect(result).toEqual({ ok: true });
    expect(getAccessToken()).toBe("new");
  });

  it("does not refresh when password is wrong", async () => {
    setTokens({ access_token: "old", refresh_token: "ref" }, false);
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 401,
      headers: new Headers({ "content-type": "application/json" }),
      text: async () => JSON.stringify({ detail: "Неверный пароль" }),
      json: async () => ({ detail: "Неверный пароль" }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(api("/api/v1/users/me", { method: "DELETE", body: "{}" })).rejects.toThrow("Неверный пароль");
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes("/auth/refresh"))).toBe(false);
  });
});
