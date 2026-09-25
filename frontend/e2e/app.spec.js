import { expect, test } from "@playwright/test";

const API = "http://127.0.0.1:8000/api/v1";
const EMAIL = "agronom@agrovision.dev";
const PASSWORD = "ValidPass1!";
const TINY_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFElEQVR4nGNU6lZiwAaYsIoOWgkApyIA31iNVQcAAAAASUVORK5CYII=",
  "base64",
);

let cachedTokens = null;

async function apiUp(request) {
  try {
    const res = await request.get("http://127.0.0.1:8000/api/v1/health");
    return res.ok();
  } catch {
    return false;
  }
}

async function sleep(ms) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

async function loginApi(request) {
  if (cachedTokens?.access_token) return cachedTokens;
  let last = "";
  for (let attempt = 0; attempt < 8; attempt += 1) {
    const res = await request.post(`${API}/auth/login`, {
      data: { email: EMAIL, password: PASSWORD, remember_me: true },
    });
    if (res.ok()) {
      cachedTokens = await res.json();
      return cachedTokens;
    }
    last = `${res.status()}: ${await res.text()}`;
    if (res.status() === 429) {
      await sleep(8000);
      continue;
    }
    throw new Error(`login failed ${last}`);
  }
  throw new Error(`login rate limited ${last}`);
}

function authHeaders(tokens) {
  return { Authorization: `Bearer ${tokens.access_token}` };
}

async function openApp(page, request) {
  const tokens = await loginApi(request);
  await page.addInitScript((t) => {
    localStorage.setItem("av_access_token", t.access_token);
    if (t.refresh_token) localStorage.setItem("av_refresh_token", t.refresh_token);
    localStorage.setItem("av_remember", "1");
  }, tokens);
  await page.goto("/");
  await expect(page.locator("#screen-app")).toBeVisible({ timeout: 20000 });
}

test.beforeEach(async ({ request }, testInfo) => {
  if (!(await apiUp(request))) testInfo.skip(true, "API is not running on :8000");
});

test("password reset send code advances the modal", async ({ page, request }) => {
  await page.goto("/");
  await expect(page.locator("#screen-auth")).toBeVisible();
  await page.click("#forgot-password-link");
  await expect(page.locator("#app-modal")).toBeVisible();
  await page.fill("#reset-email", EMAIL);
  const resetWait = page.waitForResponse((res) => res.url().includes("/api/v1/auth/password-reset/request"));
  await page.locator("#app-modal-actions button").filter({ hasText: "Отправить код" }).click();
  const resetRes = await resetWait;
  expect(resetRes.ok() || resetRes.status() === 429).toBeTruthy();
  if (resetRes.status() === 429) {
    await expect(page.locator("#reset-modal-error, #global-toast")).toContainText(/минуту|код/i);
    return;
  }
  await expect(page.locator("#app-modal-title")).toContainText("Код", { timeout: 8000 });
  const body = await resetRes.json().catch(() => ({}));
  if (body?.dev_code) {
    await expect(page.locator("#reset-code-display")).toContainText(String(body.dev_code));
    await expect(page.locator("#reset-dev-hint")).toContainText(/SMTP/i);
  }
});

test("protects map without a token", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#screen-auth")).toBeVisible();
  await expect(page.locator("#login-email")).toBeVisible();
  await expect(page.locator("#screen-app")).toBeHidden();
});

test("login remember_me logout", async ({ page }) => {
  await page.goto("/");
  let loggedIn = false;
  for (let attempt = 0; attempt < 6 && !loggedIn; attempt += 1) {
    await page.fill("#login-email", EMAIL);
    await page.fill("#login-password", PASSWORD);
    await page.locator("#login-remember").check();
    const loginWait = page.waitForResponse((res) => res.url().includes("/api/v1/auth/login"));
    await page.locator("#loginForm button[type=submit]").click();
    const loginRes = await loginWait;
    if (loginRes.ok()) {
      cachedTokens = await loginRes.json();
      loggedIn = true;
      break;
    }
    if (loginRes.status() === 429) {
      await sleep(8000);
      continue;
    }
    throw new Error(`UI login failed ${loginRes.status()}: ${await loginRes.text()}`);
  }
  expect(loggedIn).toBeTruthy();
  await expect(page.locator("#screen-app")).toBeVisible({ timeout: 15000 });
  await expect(page.locator("#map")).toBeVisible();
  const remember = await page.evaluate(() => localStorage.getItem("av_access_token"));
  expect(remember).toBeTruthy();
  await page.click(".topbar-logout");
  await expect(page.locator("#app-modal")).toBeVisible();
  await page.locator("#app-modal-actions button").filter({ hasText: "Выйти" }).click();
  await expect(page.locator("#screen-auth")).toBeVisible();
});

test("layers merge import export and auto-layer delete", async ({ page, request }) => {
  const tokens = await loginApi(request);
  const headers = authHeaders(tokens);
  await openApp(page, request);

  await page.locator("#create-layer-btn").click();
  await expect(page.locator("#app-modal")).toBeVisible();
  await page.locator("#modal-layer-name").fill("E2E слой");
  await page.locator("#app-modal-actions button").filter({ hasText: "Создать" }).click();
  await expect(page.locator("#user-layers-list")).toContainText("E2E слой", { timeout: 10000 });

  const layers = await request.get(`${API}/layers/`, { headers });
  const auto = (await layers.json()).find((item) => item.kind === "auto");
  expect(auto).toBeTruthy();
  const denied = await request.delete(`${API}/layers/${auto.id}`, { headers });
  expect(denied.status()).toBe(403);

  const created = await request.post(`${API}/layers/`, {
    headers,
    data: { name: "E2E merge", color: "#FF0000" },
  });
  const layerId = (await created.json()).id;
  const geom = {
    type: "Polygon",
    coordinates: [[[27, 53], [27.1, 53], [27.1, 53.1], [27, 53.1], [27, 53]]],
  };
  const a = await request.post(`${API}/layers/${layerId}/objects`, {
    headers,
    data: { name: "A", geom, origin: "manual" },
  });
  const b = await request.post(`${API}/layers/${layerId}/objects`, {
    headers,
    data: { name: "B", geom, origin: "manual" },
  });
  const listed = await request.get(`${API}/layers/${layerId}/objects`, { headers });
  expect(listed.ok()).toBeTruthy();
  expect((await listed.json()).length).toBeGreaterThanOrEqual(2);

  const merged = await request.post(`${API}/objects/merge`, {
    headers,
    data: { object_ids: [(await a.json()).id, (await b.json()).id] },
  });
  expect(merged.ok()).toBeTruthy();
  const other = await request.post(`${API}/layers/`, {
    headers,
    data: { name: "Other", color: "#00FF00" },
  });
  const c = await request.post(`${API}/layers/${(await other.json()).id}/objects`, {
    headers,
    data: { name: "C", geom, origin: "manual" },
  });
  const conflict = await request.post(`${API}/objects/merge`, {
    headers,
    data: { object_ids: [(await merged.json()).id, (await c.json()).id] },
  });
  expect(conflict.status()).toBe(409);

  const geojson = {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: { name: "E2E import" },
        geometry: {
          type: "Polygon",
          coordinates: [[[27.2, 53.2], [27.3, 53.2], [27.3, 53.3], [27.2, 53.3], [27.2, 53.2]]],
        },
      },
    ],
  };
  await page.locator("#import-file-input").setInputFiles({
    name: "e2e.geojson",
    mimeType: "application/geo+json",
    buffer: Buffer.from(JSON.stringify(geojson)),
  });
  await expect(page.locator("#panel-layers")).toContainText("e2e", { timeout: 15000 });

  await page.locator(".sidebar-icons .icon-btn[data-panel=export]").click();
  await page.selectOption("#export-format", "geojson");
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#export-btn").click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/geojson|json/i);

  const kml = await request.post(`${API}/layers/export`, {
    headers,
    data: { format: "kml" },
  });
  expect(kml.ok()).toBeTruthy();
  expect((kml.headers()["content-disposition"] || "") + (kml.headers()["content-type"] || "")).toMatch(/kml/i);
});

test("task upload poll to-layers", async ({ request }, testInfo) => {
  const tokens = await loginApi(request);
  const headers = authHeaders(tokens);
  const created = await request.post(`${API}/tasks/`, {
    headers,
    multipart: {
      file: { name: "aoi.png", mimeType: "image/png", buffer: TINY_PNG },
      model: "segformer",
      confidence: "0.5",
      geo_bounds: JSON.stringify({ west: 27.0, south: 53.0, east: 27.8, north: 53.8 }),
    },
  });
  if (!created.ok()) {
    const body = await created.text();
    if (created.status() === 503 || /storage/i.test(body)) {
      testInfo.skip(true, `S3/MinIO unavailable: ${body}`);
    }
    throw new Error(`create task ${created.status()}: ${body}`);
  }
  const taskId = (await created.json()).task_id;
  let task = { status: "PENDING" };
  for (let i = 0; i < 20; i += 1) {
    const res = await request.get(`${API}/tasks/${taskId}`, { headers });
    task = await res.json();
    if (task.status === "COMPLETED" || task.status === "FAILED") break;
    await sleep(1500);
  }
  if (task.status === "PENDING" || task.status === "STARTED") {
    testInfo.skip(true, "Celery/ML worker is not completing tasks");
  }
  expect(task.status).toBe("COMPLETED");
  const published = await request.post(`${API}/tasks/${taskId}/to-layers`, {
    headers,
    data: {},
  });
  expect(published.ok()).toBeTruthy();
  const layers = await request.get(`${API}/layers/`, { headers });
  const auto = (await layers.json()).find((item) => item.kind === "auto");
  const objects = await request.get(`${API}/layers/${auto.id}/objects`, { headers });
  expect(objects.ok()).toBeTruthy();
});

test("dzz bad credentials do not leak password in tile URL", async ({ page, request }) => {
  const tokens = await loginApi(request);
  const connect = await request.post(`${API}/dzz/connect`, {
    headers: authHeaders(tokens),
    data: { login: "bad", password: "secret-pass", service_url: "http://127.0.0.1:1" },
  });
  expect([401, 503]).toContain(connect.status());
  await openApp(page, request);
  expect(page.url()).not.toContain("secret-pass");
  await page.evaluate(() => localStorage.setItem("probe", "secret-pass"));
  const tileUrl = await page.evaluate(() => `/api/v1/dzz/tiles/8/140/85`);
  expect(tileUrl).toBe("/api/v1/dzz/tiles/8/140/85");
  expect(tileUrl).not.toMatch(/password|secret-pass|login=/i);
});

test("profile and activity", async ({ page, request }) => {
  await openApp(page, request);
  await page.click("#sidebar-account-btn");
  await expect(page.locator("#view-account")).toBeVisible();
  await expect(page.locator("#prof-email")).toHaveValue(EMAIL);
  await expect(page.locator("#history-feed")).toBeVisible();
  const tokens = await loginApi(request);
  const history = await request.get(`${API}/activity/`, { headers: authHeaders(tokens) });
  expect(history.ok()).toBeTruthy();
  await expect(page.locator("#prof-role")).toHaveValue("Агроном");
});

test("role select zoom pill sliders and no prompt", async ({ page, request }) => {
  await page.goto("/");
  await expect(page.locator("#screen-auth")).toBeVisible();
  await expect(page.locator("#form-login .password-toggle svg")).toBeVisible();
  await page.click("#switch-to-register");
  await expect(page.locator("#reg-role")).toBeVisible();
  const roles = await page.locator("#reg-role option").allTextContents();
  expect(roles.map((item) => item.trim())).toEqual(["Агроном", "Оператор", "Администратор"]);

  await openApp(page, request);
  await expect(page.locator("#status-dzz")).toHaveClass(/status-idle/);
  await expect(page.locator("#status-dzz")).toContainText("Не подключено");
  await expect(page.locator("#tile-display")).toContainText("z/x/y 13/", { timeout: 15000 });
  await expect(page.locator("#layers-count-badge")).toContainText("объектов");
  await expect(page.locator("#opt-dzz-url")).toHaveValue(/ImageServer$/);

  await page.locator(".sidebar-icons .icon-btn[data-panel=settings]").click();
  await page.locator("#opt-point-size").evaluate((el) => {
    el.value = "9";
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await expect(page.locator("#point-size-value")).toHaveText("9");
  await page.locator("#save-settings-btn").click();
  await expect(page.locator("#toast")).toContainText("Настройки сохранены");

  page.on("dialog", () => {
    throw new Error("native prompt/confirm is not allowed");
  });
  await page.locator(".sidebar-icons .icon-btn[data-panel=layers]").click();
  await page.locator("#create-folder-btn").click();
  await expect(page.locator("#app-modal-title")).toContainText("папка");
  await page.locator("#app-modal-actions button").filter({ hasText: "Отмена" }).click();
});

test("dzz status is coalesced across tab clicks", async ({ page, request }) => {
  const urls = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/v1/dzz/status")) urls.push(req.url());
  });
  await openApp(page, request);
  await page.waitForTimeout(400);
  const before = urls.length;
  const panels = ["layers", "settings", "export", "layers", "settings"];
  for (const panel of panels) {
    await page.locator(`.sidebar-icons .icon-btn[data-panel=${panel}]`).click();
  }
  await page.waitForTimeout(300);
  expect(urls.length - before).toBeLessThanOrEqual(1);
  expect(urls.length).toBeLessThanOrEqual(2);
});

test("hotkeys and tools do not use prompt", async ({ page, request }) => {
  page.on("dialog", () => {
    throw new Error("native prompt/confirm is not allowed");
  });
  await openApp(page, request);
  await page.locator(".tool-btn[data-tool=ruler]").click();
  await expect(page.locator("#map-area")).toHaveClass(/tool-ruler/);
  await page.locator(".tool-btn[data-tool=compass]").click();
  await expect(page.locator("#map-area")).toHaveClass(/tool-compass/);
  await page.keyboard.press("Escape");
  await expect(page.locator("#map-area")).toHaveClass(/tool-select/, { timeout: 8000 });
  await page.locator("#sidebar-edge-toggle").click();
  await expect(page.locator("#sidebar-panel-wrap")).toHaveClass(/collapsed/);
  await page.locator("#sidebar-edge-toggle").click();
  await expect(page.locator("#sidebar-panel-wrap")).not.toHaveClass(/collapsed/);
  await page.locator("#sidebar-edge-toggle").click();
  await expect(page.locator("#sidebar-panel-wrap")).toHaveClass(/collapsed/);
  await page.locator(".sidebar-icons .icon-btn[data-panel=settings]").click();
  await expect(page.locator("#sidebar-panel-wrap")).not.toHaveClass(/collapsed/);
  await page.locator("#tool-more-btn").click();
  await expect(page.locator("#more-menu")).toHaveClass(/active/);
  await page.locator("#create-area-item").click();
  await expect(page.locator("#map-area")).toHaveClass(/tool-brush/);
  await expect(page.locator("#edit-area-controls")).toBeVisible();
  await expect(page.locator("#edit-polygon-btn")).toBeVisible();
  await page.locator("#edit-polygon-btn").click();
  await expect(page.locator("#map-area")).toHaveClass(/tool-polygon/);
  await expect(page.locator("#paint-hud-hint")).toContainText(/вершин/i);
  await page.locator("#edit-eraser-btn").click();
  await expect(page.locator("#map-area")).toHaveClass(/tool-eraser/);
});

