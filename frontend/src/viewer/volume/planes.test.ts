import { describe, expect, it } from 'vitest';
import {
  clampSlice, displayLengthMm, displayToVoxel, fromVoxel, planeGeom, revealSlice, sliceVisibility, toVoxel, voxelDistanceMm, voxelToDisplay,
  PLANES, type Voxel,
} from './planes';
import { marchingSquares, ringArea, ringBounds } from './marching';
import { windowLut, windowValue, dragWindow, paintSlice } from './window';
import { decodeMask, decodeVolume, extractSlice } from './volume';
import { buildSliceDwell, dwellCells, sliceDwellFromTelemetry, sizeVerdictText } from './dwell';
import type { TelemetryEvent } from '../../types/contracts';

// Like the synthetic fixtures: 16 slices of 64×64, 3 mm between slices and 1.5 mm in-plane.
const meta = { shape: [16, 64, 64], spacing: [3, 1.5, 1.5] };

describe('plane geometry', () => {
  it('reads shape [nz, ny, nx] and spacing [sz, sy, sx] per plane', () => {
    const ax = planeGeom(meta, 'axial');
    expect([ax.w, ax.h, ax.n]).toEqual([64, 64, 16]);
    expect([ax.W, ax.H, ax.ax, ax.ay]).toEqual([64, 64, 1, 1]);
    const co = planeGeom(meta, 'coronal');
    expect([co.w, co.h, co.n]).toEqual([64, 16, 64]);
    expect([co.W, co.H]).toEqual([64, 32]); // 3 mm slices shown twice as tall as the 1.5 mm pixels
    expect(co.ay).toBe(2);
    const sa = planeGeom(meta, 'sagittal');
    expect([sa.w, sa.h, sa.n, sa.W, sa.H]).toEqual([64, 16, 64, 64, 32]);
    expect(sa.unit).toBe(1.5);
  });
  it('voxel ↔ in-plane round-trips on every plane', () => {
    const v: Voxel = [12.25, 40.5, 7];
    for (const p of PLANES) {
      const { u, v: vv, slice } = fromVoxel(p, v);
      expect(toVoxel(p, u, vv, slice)).toEqual(v);
    }
    expect(fromVoxel('coronal', v)).toEqual({ u: 12.25, v: 7, slice: 40.5 });
    expect(fromVoxel('sagittal', v)).toEqual({ u: 40.5, v: 7, slice: 12.25 });
  });
  it('display click → voxel → display round-trips, with the physical aspect applied', () => {
    for (const p of PLANES) {
      const g = planeGeom(meta, p);
      const vox = displayToVoxel(g, 5, 30.4, 21);
      const d = voxelToDisplay(g, vox);
      expect(d.x).toBeCloseTo(30.4, 9);
      expect(d.y).toBeCloseTo(21, 9);
      expect(d.slice).toBe(5);
    }
    // Coronal: 21 display px down = 10.5 slices of 3 mm → z = 10.5; the slice (y) is the coronal index.
    expect(displayToVoxel(planeGeom(meta, 'coronal'), 5, 30, 21)).toEqual([30, 5, 10.5]);
    // Sagittal: across = y, down = z, slice = x.
    expect(displayToVoxel(planeGeom(meta, 'sagittal'), 9, 30, 21)).toEqual([9, 30, 10.5]);
  });
  it('a mark placed on an axial slice lands on the matching coronal/sagittal slice', () => {
    const g = planeGeom(meta, 'axial');
    const vox = displayToVoxel(g, 8, 24, 36); // x 24, y 36, z 8
    const co = voxelToDisplay(planeGeom(meta, 'coronal'), vox);
    expect(co.slice).toBe(36);
    expect([co.x, co.y]).toEqual([24, 16]); // z 8 → 16 display px down (3 mm / 1.5 mm)
    const sa = voxelToDisplay(planeGeom(meta, 'sagittal'), vox);
    expect(sa.slice).toBe(24);
    expect([sa.x, sa.y]).toEqual([36, 16]);
  });
  it('caliper mm from display px uses the square display unit', () => {
    const co = planeGeom(meta, 'coronal');
    expect(displayLengthMm(co, [0, 0], [10, 0])).toBeCloseTo(15); // 10 px × 1.5 mm
    expect(displayLengthMm(co, [0, 0], [0, 10])).toBeCloseTo(15); // vertical display px are also 1.5 mm (5 slices)
    expect(voxelDistanceMm(meta, [0, 0, 0], [0, 0, 5])).toBeCloseTo(15);
    expect(voxelDistanceMm(meta, [0, 0, 0], [3, 4, 0])).toBeCloseTo(7.5);
  });
  it('slice helpers', () => {
    expect(clampSlice({ n: 16 }, -3)).toBe(0);
    expect(clampSlice({ n: 16 }, 15.6)).toBe(15);
    expect(sliceVisibility(8, 8)).toBe('full');
    expect(sliceVisibility(8, 9)).toBe('ghost');
    expect(sliceVisibility(8, 10)).toBe('hidden');
    expect(revealSlice([{ measure: { slice: 8 } }], 16)).toBe(8);
    expect(revealSlice([{ slice_range: [4, 12] }], 16)).toBe(8);
    expect(revealSlice([{ centroid3: [1, 2, 40] }], 16)).toBe(15);
    expect(revealSlice([], 16)).toBe(8);
  });
});

describe('window / level', () => {
  it('maps the DICOM linear VOI LUT', () => {
    expect(windowValue(-150, 50, 400)).toBe(0);
    expect(windowValue(250, 50, 400)).toBe(255);
    expect(windowValue(50, 50, 400)).toBe(128);
    expect(windowValue(50, 50, 400, true)).toBe(127);
    const lut = windowLut(50, 400);
    for (const v of [-2000, -150, -100, 0, 50, 100, 249, 250, 3000]) expect(lut[v + 32768]).toBe(windowValue(v, 50, 400));
    expect(windowValue(0, 0, 0)).toBe(windowValue(0, 0, 1)); // width clamps to 1
  });
  it('paints a slice through the LUT', () => {
    const out = new Uint8ClampedArray(8);
    paintSlice(new Int16Array([-150, 250]), windowLut(50, 400), out);
    expect(Array.from(out)).toEqual([0, 0, 0, 255, 255, 255, 255, 255]);
  });
  it('drag: horizontal = width 4 / px, vertical = level 2 / px', () => {
    expect(dragWindow({ wc: 50, ww: 400 }, 10, 0)).toEqual({ wc: 50, ww: 440 });
    expect(dragWindow({ wc: 50, ww: 400 }, 0, 10)).toEqual({ wc: 30, ww: 400 });
    expect(dragWindow({ wc: 50, ww: 10 }, -100, 0).ww).toBe(1);
  });
});

describe('volume decode and slices', () => {
  const small = { shape: [2, 3, 4], spacing: [1, 1, 1] };
  const vals = Array.from({ length: 24 }, (_, i) => i - 10); // (z*3 + y)*4 + x - 10
  const buf = new ArrayBuffer(48);
  const dv = new DataView(buf);
  vals.forEach((v, i) => dv.setInt16(i * 2, v, true));
  const vol = decodeVolume(buf, small);
  it('decodes little-endian int16 and the uint8 mask', () => {
    expect(Array.from(vol.data)).toEqual(vals);
    expect(vol.shape).toEqual([2, 3, 4]);
    const m = decodeMask(new Uint8Array(vals.map((v) => v + 10)).buffer, small);
    expect(m.data[23]).toBe(23);
    expect(() => decodeVolume(new ArrayBuffer(10), small)).toThrow();
  });
  it('extracts axial (x across, y down), coronal (x across, z down) and sagittal (y across, z down) slices', () => {
    const at = (x: number, y: number, z: number) => (z * 3 + y) * 4 + x - 10;
    const ax = extractSlice(vol.data, vol.shape, 'axial', 1);
    expect(ax.length).toBe(12);
    expect(ax[2 * 4 + 3]).toBe(at(3, 2, 1));
    const co = extractSlice(vol.data, vol.shape, 'coronal', 2);
    expect(co.length).toBe(8); // w = nx 4, h = nz 2
    expect(co[1 * 4 + 3]).toBe(at(3, 2, 1));
    const sa = extractSlice(vol.data, vol.shape, 'sagittal', 3);
    expect(sa.length).toBe(6); // w = ny 3, h = nz 2
    expect(sa[1 * 3 + 2]).toBe(at(3, 2, 1));
  });
});

describe('marching squares', () => {
  it('outlines a single pixel as a diamond through its edge midpoints', () => {
    const rings = marchingSquares(new Uint8Array([0, 0, 0, 0, 1, 0, 0, 0, 0]), 3, 3, (v) => v === 1);
    expect(rings).toHaveLength(1);
    const pts = rings[0].map(([x, y]) => `${x},${y}`).sort();
    expect(pts).toEqual(['1,1.5', '2,1.5', '1.5,1', '1.5,2'].sort());
    expect(ringArea(rings[0])).toBeCloseTo(0.5);
  });
  it('outlines a block with one closed ring whose bounds hug the block', () => {
    const w = 8, h = 6;
    const s = new Uint8Array(w * h);
    for (let y = 1; y <= 3; y++) for (let x = 2; x <= 5; x++) s[y * w + x] = 2;
    const rings = marchingSquares(s, w, h, (v) => v === 2);
    expect(rings).toHaveLength(1);
    expect(ringBounds(rings)).toEqual([2, 1, 6, 4]);
    // Area between the pixel area (12) and the outer corners: the 0.5 contour cuts the corners.
    expect(ringArea(rings[0])).toBeGreaterThan(10);
    expect(ringArea(rings[0])).toBeLessThan(12);
  });
  it('gives two rings for two separate blobs and none for an empty slice', () => {
    const w = 7, h = 3;
    const s = new Uint8Array(w * h);
    s[1 * w + 1] = 1;
    s[1 * w + 5] = 1;
    expect(marchingSquares(s, w, h, (v) => v > 0)).toHaveLength(2);
    expect(marchingSquares(new Uint8Array(w * h), w, h, (v) => v > 0)).toHaveLength(0);
  });
});

describe('slice dwell', () => {
  const ev = (t: number, slice: number | null, plane: TelemetryEvent['plane'] = 'axial'): TelemetryEvent =>
    ({ t, kind: 'move', zoom: 1, vp: [0, 0, 64, 64], loupe: false, plane, slice });
  it('sums the time each slice was on screen, capping gaps', () => {
    const d = sliceDwellFromTelemetry([ev(0, 3), ev(100, 3), ev(400, 4), ev(5000, 4), ev(5100, 5)], 'axial');
    expect(d.get(3)).toBe(400);
    expect(d.get(4)).toBe(1500 + 100); // 4600 ms gap capped at 1500
    expect(d.get(5)).toBeUndefined(); // the last event has no successor
    expect(sliceDwellFromTelemetry([ev(0, 3, 'coronal'), ev(100, 3)], 'axial').size).toBe(0);
    expect(sliceDwellFromTelemetry([ev(0, null), ev(100, null)], 'axial').size).toBe(0);
  });
  it('builds the server shape and the bar cells', () => {
    const rows = buildSliceDwell([ev(0, 2), ev(900, 2), ev(1000, 7), ev(1200, 7)], 'axial', 10, [{ finding_id: 'F1', slice_range: [6, 8] }]);
    expect(rows).toHaveLength(10);
    expect(rows[2]).toMatchObject({ slice: 2, ms: 1000, has_finding: false, finding_ids: [] });
    expect(rows[7]).toMatchObject({ slice: 7, ms: 200, has_finding: true, finding_ids: ['F1'] });
    const cells = dwellCells(rows, 'axial', 10);
    expect(cells[2].frac).toBe(1);
    expect(cells[7]).toMatchObject({ hasFinding: true, notVisited: true }); // 200 ms is under the 300 ms per-slice threshold
    expect(cells[6]).toMatchObject({ hasFinding: true, ms: 0, notVisited: true });
    expect(cells[8]).toMatchObject({ hasFinding: true, ms: 0, notVisited: true });
    expect(cells[0]).toMatchObject({ hasFinding: false, notVisited: false, frac: 0 });
    expect(dwellCells(null, 'axial', 3)).toHaveLength(3);
  });
  it('words the size verdict without naming the body part', () => {
    expect(sizeVerdictText({ your_mm: 32, reference_mm: 37.9, diff_pct: -15.6, ok: true }))
      .toBe('You measured 32 mm; reference 37.9 mm, 16 % smaller — within tolerance.');
    expect(sizeVerdictText({ your_mm: 50, reference_mm: 37.9, diff_pct: 31.9, ok: false }))
      .toBe('You measured 50 mm; reference 37.9 mm, 32 % larger — off by 12.1 mm.');
    expect(sizeVerdictText(null)).toBeNull();
  });
});

describe('dwell caption (backend thresholds, never contradicts finding_slices_viewed)', () => {
  const row = (slice: number, ms: number, has: boolean) => ({ plane: 'axial', slice, ms, has_finding: has, finding_ids: has ? ['F1'] : [] });
  it('counts finding slices seen ≥ 300 ms', async () => {
    const { dwellCaption, dwellCells } = await import('./dwell');
    const rows = [row(0, 900, false), row(1, 1200, true), row(2, 250, true), row(3, 0, true)];
    const cells = dwellCells(rows, 'axial', 4);
    expect(cells.map((c) => c.notVisited)).toEqual([false, false, true, true]);
    expect(dwellCaption(cells, { F1: true })).toBe('You saw 1 of the 3 slices the finding is on.');
    expect(dwellCaption(cells, { F1: false })).toBe('You saw 1 of the 3 slices the finding is on, not long enough to count.');
    expect(dwellCaption(dwellCells([row(1, 100, true), row(2, 0, true)], 'axial', 3), {})).toBe('You never paused on the 2 slices the finding is on.');
    const all = dwellCells([row(1, 400, true), row(2, 300, true)], 'axial', 3);
    expect(dwellCaption(all, { F1: true })).toBe('You saw every one of the 2 slices the finding is on.');
    expect(dwellCaption(all, { F1: false })).toBe('You saw 2 of the 2 slices the finding is on, not long enough to count.');
    expect(dwellCaption(dwellCells(null, 'axial', 3), null)).toBe('No slice times were recorded.');
  });
});
