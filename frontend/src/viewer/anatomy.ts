// "Show anatomy" (key A, after submit only): zone outlines from GET /api/attempts/{aid}/anatomy, drawn in graticule
// grey at 40%. The payload is guarded loosely so small server-side shape changes degrade to "nothing to show".
import { zoneDisplay } from '../api/labels';

export type Pt = [number, number];
export type AnatomyZone = { id: string; name: string; rings: Pt[][]; reviewArea: boolean; area: number };
export type Anatomy = { zones: AnatomyZone[]; approximate: boolean };

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const isPt = (v: unknown): v is Pt => Array.isArray(v) && v.length >= 2 && typeof v[0] === 'number' && typeof v[1] === 'number';

/** Accepts a ring ([[x,y],…]), a list of rings, or {points|polygon|contour: …}. */
function rings(v: unknown): Pt[][] {
  if (!Array.isArray(v) || v.length === 0) return [];
  if (isPt(v[0])) {
    const ring = (v as unknown[]).filter(isPt).map((p) => [p[0], p[1]] as Pt);
    return ring.length >= 3 ? [ring] : [];
  }
  return v.flatMap((r) => (isObj(r) ? rings(r.points ?? r.polygon ?? r.contour) : rings(r)));
}

/** Shoelace area (absolute), used to draw big zones first so smaller ones sit on top and win the hover. */
export function ringArea(r: Pt[]): number {
  let a = 0;
  for (let i = 0; i < r.length; i++) {
    const [x0, y0] = r[i];
    const [x1, y1] = r[(i + 1) % r.length];
    a += x0 * y1 - x1 * y0;
  }
  return Math.abs(a) / 2;
}

function zoneFrom(id: string, v: unknown): AnatomyZone | null {
  if (!id) return null;
  const o = isObj(v) ? v : { polygons: v };
  const rs = rings(o.polygons ?? o.contours ?? o.polygon ?? o.rings ?? o.outline ?? o.points);
  if (!rs.length) return null;
  const display = [o.human, o.display, o.name].find((x): x is string => typeof x === 'string' && !!x && x !== id) ?? '';
  const name = display || zoneDisplay(id);
  const area = rs.reduce((n, r) => n + ringArea(r), 0);
  return { id, name: name.charAt(0).toUpperCase() + name.slice(1), rings: rs, reviewArea: o.review_area === true, area };
}

export function guardAnatomy(v: unknown): Anatomy {
  if (!isObj(v)) return { zones: [], approximate: false };
  const approximate = v.approximate === true || v.zones_approximate === true;
  const src = v.zones ?? v.outlines ?? v.areas;
  let zones: (AnatomyZone | null)[] = [];
  if (Array.isArray(src)) {
    zones = src.map((z) => (isObj(z) ? zoneFrom(String(z.zone_id ?? z.id ?? z.zone ?? z.name ?? ''), z) : null));
  } else if (isObj(src)) {
    zones = Object.entries(src).map(([id, z]) => zoneFrom(id, z));
  }
  const kept = zones.filter((z): z is AnatomyZone => !!z).sort((a, b) => b.area - a.area);
  return { zones: kept, approximate };
}

export const ringPath = (r: Pt[]) => `M${r.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join('L')}Z`;

/** A review area the learner did not visit, drawn on the film as a thin dashed amber ring (round 3, search trace). */
export type UnvisitedRing = { id: string; name: string; cx: number; cy: number; rx: number; ry: number };

export function zoneBox(z: AnatomyZone): [number, number, number, number] {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const r of z.rings) for (const [x, y] of r) {
    if (x < x0) x0 = x;
    if (y < y0) y0 = y;
    if (x > x1) x1 = x;
    if (y > y1) y1 = y;
  }
  return [x0, y0, x1, y1];
}

/** Ring positions for the unvisited review areas, from the anatomy outlines: a ring at the centre of each area, no
 *  smaller than `minR` and no larger than `maxR` (image px), so nine unvisited areas read as nine markers rather than
 *  nine overlapping outlines. Areas with no outline come back in `missing` so the legend can still list them by name. */
export function unvisitedRings(anatomy: Anatomy | null | undefined, ids: string[], minR = 0, maxR = Infinity): { rings: UnvisitedRing[]; missing: string[] } {
  const rings: UnvisitedRing[] = [];
  const missing: string[] = [];
  const fit = (half: number) => Math.min(maxR, Math.max(minR, half));
  for (const id of ids) {
    const z = anatomy?.zones.find((x) => x.id === id);
    if (!z) { missing.push(id); continue; }
    const [x0, y0, x1, y1] = zoneBox(z);
    if (!Number.isFinite(x0 + y0 + x1 + y1)) { missing.push(id); continue; }
    rings.push({ id, name: z.name, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, rx: fit((x1 - x0) / 2), ry: fit((y1 - y0) / 2) });
  }
  return { rings, missing };
}
