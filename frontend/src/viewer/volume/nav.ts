// Where the learner is in a volume: the 2×2 grid (default on open) or one plane, and the current slice of each plane.
// Pure state + reducer helpers, unit-tested.
import { clampSlice, planeGeom, PLANES, type Plane, type VolumeMeta } from './planes';

export type VolumeNav = { grid: boolean; plane: Plane; slice: Record<Plane, number> };

export function initialNav(meta: VolumeMeta, plane: Plane = 'axial', grid = true): VolumeNav {
  const slice = { axial: 0, coronal: 0, sagittal: 0 };
  for (const p of PLANES) slice[p] = Math.floor(planeGeom(meta, p).n / 2);
  return { grid, plane, slice };
}

export function setSlice(nav: VolumeNav, meta: VolumeMeta, plane: Plane, s: number): VolumeNav {
  const next = clampSlice(planeGeom(meta, plane), s);
  return next === nav.slice[plane] ? nav : { ...nav, slice: { ...nav.slice, [plane]: next } };
}
export const stepSlice = (nav: VolumeNav, meta: VolumeMeta, plane: Plane, delta: number) => setSlice(nav, meta, plane, nav.slice[plane] + delta);

/** Single-plane view of `plane` (optionally at a slice). */
export function showPlane(nav: VolumeNav, meta: VolumeMeta, plane: Plane, slice?: number): VolumeNav {
  const n = slice === undefined ? nav : setSlice(nav, meta, plane, slice);
  return n.grid === false && n.plane === plane && n === nav ? nav : { ...n, grid: false, plane };
}
export const showGrid = (nav: VolumeNav): VolumeNav => (nav.grid ? nav : { ...nav, grid: true });

/** One wheel notch (a mouse: ≥ 50 px per event) is one slice; a trackpad's small deltas accumulate to a notch. */
export const WHEEL_NOTCH_PX = 30;
export const WHEEL_DISCRETE_PX = 50;
export function wheelNotches(acc: number, deltaY: number, deltaMode: number): { acc: number; steps: number } {
  const px = deltaMode === 1 ? deltaY * WHEEL_NOTCH_PX : deltaMode === 2 ? deltaY * WHEEL_NOTCH_PX * 10 : deltaY;
  if (Math.abs(px) >= WHEEL_DISCRETE_PX) return { acc: 0, steps: Math.sign(px) };
  let a = acc + px;
  let steps = 0;
  while (a >= WHEEL_NOTCH_PX) { a -= WHEEL_NOTCH_PX; steps++; }
  while (a <= -WHEEL_NOTCH_PX) { a += WHEEL_NOTCH_PX; steps--; }
  return { acc: a, steps };
}

export const PLANE_DISPLAY: Record<Plane, string> = { axial: 'Axial', coronal: 'Coronal', sagittal: 'Sagittal' };

/** "axial 12" — where a mark sits, for the rail's "M1 · axial 12" (1-based slice). */
export const markPlace = (m: { plane?: Plane | null; slice?: number | null }): string | null =>
  m.plane && m.slice != null ? `${PLANE_DISPLAY[m.plane].toLowerCase()} ${m.slice + 1}` : null;
