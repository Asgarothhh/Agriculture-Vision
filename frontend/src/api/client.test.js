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

  it("drops the pydantic «Value error,» prefix", () => {
    expect(formatDetail({ detail: [{ msg: "Value error, Пароли не совпадают" }] })).toBe("Пароли не совпадают");
  });

  it("explains slowapi rate limit answers", () => {
    expect(formatDetail({ error: "Rate limit exceeded: 5 per 1 minute" })).toMatch(/подождите/);
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

describe("authFetch (dzz.by tiles with the app token)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    clearTokens();
  });

  const json = (status, body) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

  it("sends the token and refreshes it once when it has expired", async () => {
    const { authFetch } = await import("./client.js");
    setTokens({ access_token: "old", refresh_token: "r1" });
    const seen = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url, init) => {
        seen.push([url, new Headers(init.headers).get("Authorization")]);
        if (url === "/api/v1/auth/refresh") return json(200, { access_token: "new", refresh_token: "r2" });
        if (new Headers(init.headers).get("Authorization") === "Bearer old") return json(401, { detail: "Invalid token" });
        return new Response(new Blob(["tile"]), { status: 200 });
      }),
    );
    const res = await authFetch("/api/v1/dzz/tiles/1/1/1");
    expect(res.status).toBe(200);
    expect(seen.map(([u, a]) => `${u} ${a}`)).toEqual([
      "/api/v1/dzz/tiles/1/1/1 Bearer old",
      "/api/v1/auth/refresh null",
      "/api/v1/dzz/tiles/1/1/1 Bearer new",
    ]);
  });

  it("leaves dzz.by's own 401 to the caller (no token refresh)", async () => {
    const { authFetch } = await import("./client.js");
    setTokens({ access_token: "tok", refresh_token: "r1" });
    const fetchMock = vi.fn(async () => json(401, { detail: "Нет сессии dzz.by" }));
    vi.stubGlobal("fetch", fetchMock);
    const res = await authFetch("/api/v1/dzz/tiles/1/1/1");
    expect(res.status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
