// The active film tool and the caliper draft. A small store so the strip under the film (Point · Draw · Caliper), the
// rail's size step (volumes: "Measure") and the viewer all see the same thing. Reset per case by the reading room.
// Round 5: 'mark' is the Point tool (a click places a mark), 'draw' traces a free outline (read/stroke.ts).
import { create } from 'zustand';
import { displayLengthMm, displayToVoxel, planeGeom, type Plane, type VolumeMeta } from '../viewer/volume/planes';
import type { DraftMeasurement } from './readState';

export type Tool = 'mark' | 'draw' | 'caliper';
/** The segmented tool buttons, in strip order, with their keys. */
export const TOOLS: { id: Tool; name: string; key: string; title: string }[] = [
  { id: 'mark', name: 'Point', key: 'P', title: 'Point: click the film to place a mark (P)' },
  { id: 'draw', name: 'Draw', key: 'D', title: 'Draw: press and drag to trace an outline around a finding (D)' },
  { id: 'caliper', name: 'Caliper', key: 'C', title: 'Caliper: drag from edge to edge to measure (C)' },
];
/** The key for a tool, or the tool for a key (case-insensitive). */
export const toolForKey = (key: string): Tool | null => TOOLS.find((t) => t.key === key.toUpperCase())?.id ?? null;
/** A caliper line in image px (X-ray) or display px of its plane (volume). */
export type CaliperDraft = { plane: Plane | null; slice: number | null; p0: [number, number]; p1: [number, number] };

type Store = {
  tool: Tool;
  caliper: CaliperDraft | null;
  /** Volumes: the mark the size step is measuring for. */
  forMark: string | null;
  setTool: (t: Tool) => void;
  /** Pressing a tool's key: that tool, or back to Point when it is already on (keys toggle). */
  toggleTool: (t: Tool) => void;
  setCaliper: (c: CaliperDraft | null) => void;
  /** Start the size step for a mark: caliper tool on, any old line cleared. */
  measure: (markId: string | null) => void;
  reset: () => void;
};

export const useTools = create<Store>()((set) => ({
  tool: 'mark',
  caliper: null,
  forMark: null,
  setTool: (tool) => set({ tool }),
  toggleTool: (t) => set((st) => ({ tool: st.tool === t ? 'mark' : t })),
  setCaliper: (caliper) => set({ caliper }),
  measure: (forMark) => set({ forMark, tool: 'caliper', caliper: null }),
  reset: () => set({ tool: 'mark', caliper: null, forMark: null }),
}));

export const caliperLengthPx = (c: CaliperDraft) => Math.hypot(c.p1[0] - c.p0[0], c.p1[1] - c.p0[1]);

/** A recorded measurement from the caliper draft on a volume: mm from the plane's spacing, endpoints as voxels. */
export function measurementFromCaliper(meta: VolumeMeta, c: CaliperDraft): DraftMeasurement | null {
  if (!c.plane || c.slice == null) return null;
  const g = planeGeom(meta, c.plane);
  const long_mm = displayLengthMm(g, c.p0, c.p1);
  if (!(long_mm > 0)) return null;
  return { long_mm, plane: c.plane, slice: c.slice, p0: displayToVoxel(g, c.slice, c.p0[0], c.p0[1]), p1: displayToVoxel(g, c.slice, c.p1[0], c.p1[1]) };
}
