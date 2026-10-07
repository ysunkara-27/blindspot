// Signs on the reveal (round 5, clinician feedback C): the radiologists' "look for" cues drawn on the film after submit.
// This store is the seam between the viewer (draws them, owns the "Signs" toggle and the S key) and the rail / reference
// drawer (a row can call `focusSign(id)` to pulse that sign on the film and, on a volume, scroll to its slice).
// Pure helpers below map a sign's geometry onto the current view; unit-tested.
import { create } from 'zustand';
import type { RevealFinding, Sign } from '../types/contracts';
import { inPlaneToDisplay, type PlaneGeom } from './volume/planes';

export const FOCUS_MS = 1500;

type SignsStore = {
  /** "Signs" toggle; on by default after every submit. */
  visible: boolean;
  setVisible: (v: boolean) => void;
  toggle: () => void;
  /** The sign a rail row asked for, with the time of the request (a repeat request pulses again). */
  focused: { id: string; at: number } | null;
  /** Pulse this sign for 1.5 s on the film (and scroll a volume to its slice); turns the layer on if it was off. */
  focusSign: (id: string) => void;
  clearFocus: () => void;
  reset: () => void;
};

export const useSigns = create<SignsStore>()((set) => ({
  visible: true,
  setVisible: (visible) => set({ visible }),
  toggle: () => set((s) => ({ visible: !s.visible })),
  focused: null,
  focusSign: (id) => set({ focused: { id, at: Date.now() }, visible: true }),
  clearFocus: () => set({ focused: null }),
  reset: () => set({ visible: true, focused: null }),
}));

/** `signsVisible` for the rail: a hook with the current value. */
export const useSignsVisible = () => useSigns((s) => s.visible);
/** `focusSign(id)` for the rail, usable outside React. */
export const focusSign = (id: string) => useSigns.getState().focusSign(id);

export type SignGeometry = Sign['geometry'];
export type SignKind = SignGeometry['kind'];

/** A sign with its finding, as drawn on the current view (points in image / display px). */
export type ViewSign = {
  id: string;
  finding_id: string;
  name: string;
  text: string;
  kind: SignKind;
  points: [number, number][];
  radius: number | null;
  schematic: string | null;
};

const isPt = (p: unknown): p is [number, number] =>
  Array.isArray(p) && p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]);

/** The minimum number of points each kind needs to be drawn. */
export const MIN_POINTS: Record<SignKind, number> = { polyline: 2, polygon: 3, circle: 1, arrow: 2, segment: 2, band: 3 };

/** Signs of these findings that can be drawn here. X-ray: every sign (geometry in image px). Volume (`geom` and
 *  `slice` given): only the signs on this plane and slice, their points (in-plane coords) mapped to display px.
 *  A sign without a usable geometry (e.g. schematic-only) is left out: the rail shows its schematic instead. */
export function signsOnView(findings: RevealFinding[], geom: PlaneGeom | null = null, slice: number | null = null): ViewSign[] {
  const out: ViewSign[] = [];
  for (const f of findings) {
    for (const s of f.signs ?? []) {
      const g = s.geometry;
      if (!g || !Array.isArray(g.points)) continue;
      const kind = g.kind;
      if (!(kind in MIN_POINTS)) continue;
      let pts = g.points.filter(isPt).map(([x, y]) => [x, y] as [number, number]);
      let radius = typeof g.radius === 'number' && Number.isFinite(g.radius) ? g.radius : null;
      if (geom) {
        if (g.plane !== geom.plane || g.slice == null || Math.round(g.slice) !== slice) continue;
        pts = pts.map(([u, v]) => { const d = inPlaneToDisplay(geom, u, v); return [d.x, d.y]; });
        if (radius != null) radius *= Math.min(geom.ax, geom.ay);
      } else if (g.plane) continue; // a volume sign never draws on an X-ray
      if (pts.length < MIN_POINTS[kind]) continue;
      if (kind === 'circle' && (radius == null || radius <= 0)) continue;
      out.push({ id: s.id, finding_id: f.finding_id, name: s.name, text: s.text, kind, points: pts, radius, schematic: s.schematic ?? null });
    }
  }
  return out;
}

/** The slice a sign sits on (volumes), or null. */
export function signSlice(findings: RevealFinding[], id: string): { plane: string; slice: number } | null {
  for (const f of findings) {
    for (const s of f.signs ?? []) {
      if (s.id === id && s.geometry?.plane && s.geometry.slice != null) return { plane: s.geometry.plane, slice: Math.round(s.geometry.slice) };
    }
  }
  return null;
}

/** Bounding box of a sign's drawn shape [x0, y0, x1, y1]. */
export function signBounds(s: ViewSign): [number, number, number, number] {
  if (s.kind === 'circle') {
    const [cx, cy] = s.points[0];
    const r = s.radius ?? 0;
    return [cx - r, cy - r, cx + r, cy + r];
  }
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [x, y] of s.points) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  return [x0, y0, x1, y1];
}
