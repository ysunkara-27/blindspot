// Plane geometry for CT / MR volumes (docs/VOLUMETRIC_PLAN.md). Pure, unit-tested.
//
// Voxel space: index [x, y, z] into a volume of shape [nz, ny, nx] stored z,y,x contiguous (index = (z*ny + y)*nx + x);
// slice 0 is the most superior, patient RIGHT is at low x (so, as on the X-ray, patient right is displayed on the left).
//
// Each plane is viewed as a 2-D image:
//   axial    across x, down y, one image per z     coronal  across x, down z, one image per y
//   sagittal across y, down z, one image per x
// "In-plane coords" (u, v) are voxel indices along the across / down axes of the plane; that is what marks and
// telemetry carry as x, y (plus `plane`, `slice` and the full `voxel`). The viewer itself works in DISPLAY px: the
// in-plane image resampled to square pixels of `unit` mm (the smaller of the two in-plane spacings), so the film
// keeps its physical aspect and the existing isotropic screen transform (coords.ts) needs no change.
export type Plane = 'axial' | 'coronal' | 'sagittal';
export const PLANES: Plane[] = ['axial', 'coronal', 'sagittal'];
export const isPlane = (v: unknown): v is Plane => v === 'axial' || v === 'coronal' || v === 'sagittal';

export type Voxel = [number, number, number];
/** [nz, ny, nx] and [sz, sy, sx] mm, as the contract sends them. */
export type VolumeMeta = { shape: number[]; spacing: number[] };

export type PlaneGeom = {
  plane: Plane;
  /** In-plane voxel columns / rows and the number of slices. */
  w: number; h: number; n: number;
  /** mm per voxel across / down. */
  su: number; sv: number;
  /** mm per display px (square). */
  unit: number;
  /** Display size in px. */
  W: number; H: number;
  /** Display px per voxel across / down. */
  ax: number; ay: number;
};

const pos = (v: number | undefined, fallback: number) => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : fallback);

export function planeGeom(meta: VolumeMeta, plane: Plane): PlaneGeom {
  const nz = Math.max(1, Math.round(meta.shape[0] ?? 1));
  const ny = Math.max(1, Math.round(meta.shape[1] ?? 1));
  const nx = Math.max(1, Math.round(meta.shape[2] ?? 1));
  const sz = pos(meta.spacing[0], 1);
  const sy = pos(meta.spacing[1], 1);
  const sx = pos(meta.spacing[2], 1);
  let w: number, h: number, n: number, su: number, sv: number;
  if (plane === 'axial') { w = nx; h = ny; n = nz; su = sx; sv = sy; }
  else if (plane === 'coronal') { w = nx; h = nz; n = ny; su = sx; sv = sz; }
  else { w = ny; h = nz; n = nx; su = sy; sv = sz; }
  const unit = Math.min(su, sv);
  const ax = su / unit;
  const ay = sv / unit;
  return { plane, w, h, n, su, sv, unit, W: w * ax, H: h * ay, ax, ay };
}

/** In-plane (u, v) on `slice` of `plane` → voxel [x, y, z]. */
export function toVoxel(plane: Plane, u: number, v: number, slice: number): Voxel {
  if (plane === 'axial') return [u, v, slice];
  if (plane === 'coronal') return [u, slice, v];
  return [slice, u, v];
}
/** Voxel [x, y, z] → in-plane (u, v) and the (float) slice of `plane` it sits on. */
export function fromVoxel(plane: Plane, vox: Voxel): { u: number; v: number; slice: number } {
  const [x, y, z] = vox;
  if (plane === 'axial') return { u: x, v: y, slice: z };
  if (plane === 'coronal') return { u: x, v: z, slice: y };
  return { u: y, v: z, slice: x };
}

/** Display px on a slice → voxel (float). THE function a click goes through to become a 3-D mark. */
export function displayToVoxel(g: PlaneGeom, slice: number, xd: number, yd: number): Voxel {
  return toVoxel(g.plane, xd / g.ax, yd / g.ay, slice);
}
/** Voxel → display px in this plane, and the slice (float) it is on. */
export function voxelToDisplay(g: PlaneGeom, vox: Voxel): { x: number; y: number; slice: number } {
  const { u, v, slice } = fromVoxel(g.plane, vox);
  return { x: u * g.ax, y: v * g.ay, slice };
}
/** In-plane voxel coords → display px (the mark's x, y → where to draw it). */
export const inPlaneToDisplay = (g: PlaneGeom, u: number, v: number) => ({ x: u * g.ax, y: v * g.ay });
export const displayToInPlane = (g: PlaneGeom, xd: number, yd: number) => ({ u: xd / g.ax, v: yd / g.ay });

export const clampSlice = (g: Pick<PlaneGeom, 'n'>, s: number) => Math.min(g.n - 1, Math.max(0, Math.round(s)));

/** Length of a caliper drawn in display px, in mm (display px are square `unit` mm). */
export function displayLengthMm(g: PlaneGeom, p0: [number, number], p1: [number, number]): number {
  return Math.hypot(p1[0] - p0[0], p1[1] - p0[1]) * g.unit;
}
/** Physical distance between two voxels, in mm. */
export function voxelDistanceMm(meta: VolumeMeta, a: Voxel, b: Voxel): number {
  const sz = pos(meta.spacing[0], 1), sy = pos(meta.spacing[1], 1), sx = pos(meta.spacing[2], 1);
  return Math.hypot((a[0] - b[0]) * sx, (a[1] - b[1]) * sy, (a[2] - b[2]) * sz);
}

/** How a mark placed on `from` shows on `to`: its display position there and how many slices away it is. */
export function projectMark(meta: VolumeMeta, vox: Voxel, to: Plane): { x: number; y: number; slice: number } {
  return voxelToDisplay(planeGeom(meta, to), vox);
}

/** Marks and the caliper show on their own slice (full), one slice either side (ghosted), and not beyond. */
export type SliceVisibility = 'full' | 'ghost' | 'hidden';
export function sliceVisibility(markSlice: number, current: number, ghostWithin = 1): SliceVisibility {
  const d = Math.abs(Math.round(markSlice) - current);
  return d < 0.5 ? 'full' : d <= ghostWithin ? 'ghost' : 'hidden';
}

/** Where the reveal opens: the first finding's measured slice, else the middle of its slice range, else its centroid,
 *  else the middle of the volume. Always a valid axial index. */
export function revealSlice(
  findings: { measure?: { slice: number } | null; slice_range?: number[] | null; centroid3?: number[] | null }[],
  nz: number,
): number {
  const f = findings[0];
  let s = Math.floor(nz / 2);
  if (f?.measure && Number.isFinite(f.measure.slice)) s = f.measure.slice;
  else if (f?.slice_range && f.slice_range.length >= 2) s = (f.slice_range[0] + f.slice_range[1]) / 2;
  else if (f?.centroid3 && f.centroid3.length >= 3) s = f.centroid3[2];
  return clampSlice({ n: nz }, s);
}
