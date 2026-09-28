import { describe, expect, it, vi } from "vitest";

vi.mock("../dzz/tiles.js", () => ({ dzzEnsureTileBlob: vi.fn(), dzzFetchResilient: vi.fn(), dzzPrefetch: vi.fn() }));

const { chooseCaptureZoom, CAPTURE_MAX_EDGE, CAPTURE_MAX_ZOOM } = await import("./map.js");

// Area whose size in pixels doubles with every zoom level: `px0` pixels at zoom 0.
const area = (px0w, px0h = px0w) => (z) => ({ w: px0w * 2 ** z, h: px0h * 2 ** z });

describe("chooseCaptureZoom (reference snapshot quality)", () => {
  it("takes the highest zoom that still fits into the max edge, whatever the screen zoom", () => {
    const edgeAt = area(CAPTURE_MAX_EDGE / 2 ** 17); // exactly the max edge at z17
    expect(chooseCaptureZoom(edgeAt, 12)).toBe(17);
    expect(chooseCaptureZoom(edgeAt, 17)).toBe(17);
    expect(chooseCaptureZoom(edgeAt, 21)).toBe(17);
  });

  it("never goes above the native maximum (z18) for small areas", () => {
    const edgeAt = area(300 / 2 ** 18);
    expect(chooseCaptureZoom(edgeAt, 20)).toBe(CAPTURE_MAX_ZOOM);
  });

  it("zooms out for areas larger than one snapshot", () => {
    const edgeAt = area((CAPTURE_MAX_EDGE * 1.9) / 2 ** 15); // too big at z15, fits at z14
    expect(chooseCaptureZoom(edgeAt, 15)).toBe(14);
    const { w } = edgeAt(14);
    expect(w).toBeLessThanOrEqual(CAPTURE_MAX_EDGE);
  });

  it("keeps at least one tile of pixels on the short side", () => {
    const edgeAt = area(2000 / 2 ** 16, 100 / 2 ** 16); // long thin strip
    const z = chooseCaptureZoom(edgeAt, 16);
    expect(edgeAt(z).h).toBeGreaterThanOrEqual(100);
    expect(z).toBeLessThanOrEqual(CAPTURE_MAX_ZOOM);
  });
});
