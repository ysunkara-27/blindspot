// Window / level: signed 16-bit voxel values → 8-bit grey (DICOM PS3.3 C.11.2.1.2 linear VOI LUT).
// A 65 536-entry lookup table makes a slice render one array read per pixel.
export type Window = { wc: number; ww: number };

/** 8-bit grey for one value. ww is clamped to ≥ 1. */
export function windowValue(v: number, wc: number, ww: number, invert = false): number {
  const w = Math.max(1, ww);
  let y = ((v - (wc - 0.5)) / (w - 1) + 0.5) * 255;
  y = y <= 0 ? 0 : y >= 255 ? 255 : Math.round(y);
  return invert ? 255 - y : y;
}

/** LUT indexed by (value + 32768). */
export function windowLut(wc: number, ww: number, invert = false): Uint8Array {
  const lut = new Uint8Array(65536);
  const w = Math.max(1, ww);
  const lo = wc - 0.5 - (w - 1) / 2;
  const k = 255 / (w - 1);
  for (let i = 0; i < 65536; i++) {
    const v = i - 32768;
    let y = (v - lo) * k;
    y = y <= 0 ? 0 : y >= 255 ? 255 : Math.round(y);
    lut[i] = invert ? 255 - y : y;
  }
  return lut;
}

/** Fill an RGBA buffer (4 bytes per voxel) from a slice through the LUT. */
export function paintSlice(slice: Int16Array, lut: Uint8Array, out: Uint8ClampedArray): void {
  const n = slice.length;
  for (let i = 0, o = 0; i < n; i++, o += 4) {
    const g = lut[slice[i] + 32768];
    out[o] = g;
    out[o + 1] = g;
    out[o + 2] = g;
    out[o + 3] = 255;
  }
}

/** W/L drag: horizontal movement changes the width (4 per px), vertical the level (2 per px, up = brighter). */
export const WL_DRAG = { widthPerPx: 4, levelPerPx: 2 };
export function dragWindow(start: Window, dxPx: number, dyPx: number): Window {
  return { wc: Math.round(start.wc - dyPx * WL_DRAG.levelPerPx), ww: Math.max(1, Math.round(start.ww + dxPx * WL_DRAG.widthPerPx)) };
}
