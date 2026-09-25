import { restoreDzzSession } from "./session.js";
import { getActiveBasemapTileUrl, toSameOriginDzzUrl } from "./urls.js";

export const DZZ_TILE_CACHE_MAX = 480;
export const DZZ_MAX_INFLIGHT = 6;
export const DZZ_PREFETCH_SLOTS = 2;

const tileCache = new Map();
let inflight = 0;
const queue = [];
let prefetchBusy = 0;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function rememberBlob(url, blob) {
  if (!blob || blob.size < 400) return;
  if (tileCache.has(url)) tileCache.delete(url);
  tileCache.set(url, blob);
  while (tileCache.size > DZZ_TILE_CACHE_MAX) {
    const first = tileCache.keys().next().value;
    tileCache.delete(first);
  }
}

async function withInflight(fn) {
  if (inflight >= DZZ_MAX_INFLIGHT) {
    await new Promise((resolve) => queue.push(resolve));
  }
  inflight += 1;
  try {
    return await fn();
  } finally {
    inflight -= 1;
    const next = queue.shift();
    if (next) next();
  }
}

export async function dzzFetchResilient(url, ms = 12000, signal, attempts = 3) {
  const delays = [400, 800];
  let lastErr;
  for (let i = 0; i < attempts; i += 1) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), ms);
    const merged = signal || ctrl.signal;
    try {
      const res = await fetch(url, { credentials: "same-origin", signal: merged });
      clearTimeout(timer);
      if (res.status === 401) {
        const restored = await restoreDzzSession();
        if (restored) {
          lastErr = new Error("HTTP 401");
          continue;
        }
      }
      if (res.ok) return res;
      lastErr = new Error(`HTTP ${res.status}`);
    } catch (err) {
      clearTimeout(timer);
      lastErr = err;
    }
    if (i < attempts - 1) await sleep(delays[i] || 400);
  }
  throw lastErr || new Error("dzz tile failed");
}

export async function dzzEnsureTileBlob(url) {
  if (tileCache.has(url)) return tileCache.get(url);
  return withInflight(async () => {
    if (tileCache.has(url)) return tileCache.get(url);
    const res = await dzzFetchResilient(url);
    const blob = await res.blob();
    rememberBlob(url, blob);
    return blob;
  });
}

export function dzzPrefetch(coords) {
  if (!coords || prefetchBusy >= DZZ_PREFETCH_SLOTS) return;
  const neighbors = [
    [coords.z, coords.x + 1, coords.y],
    [coords.z, coords.x - 1, coords.y],
    [coords.z, coords.x, coords.y + 1],
    [coords.z, coords.x, coords.y - 1],
    [coords.z + 1, coords.x * 2, coords.y * 2],
  ];
  neighbors.forEach(([z, x, y]) => {
    if (prefetchBusy >= DZZ_PREFETCH_SLOTS) return;
    const url = toSameOriginDzzUrl(getActiveBasemapTileUrl(z, x, y));
    if (tileCache.has(url)) return;
    prefetchBusy += 1;
    dzzEnsureTileBlob(url)
      .catch(() => {})
      .finally(() => {
        prefetchBusy = Math.max(0, prefetchBusy - 1);
      });
  });
}

export function clearDzzTileCache() {
  tileCache.clear();
}
