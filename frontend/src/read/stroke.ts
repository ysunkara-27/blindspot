// Free-drawn outlines (round 5, clinician feedback A): the Draw tool traces a stroke on the film; releasing closes it.
// Pure geometry in image px, unit-tested. The viewer samples pointer positions into a stroke, then `finishStroke`
// decides: a tiny stroke becomes a point mark, anything else a closed polygon of at most MAX_POINTS vertices with the
// mark's x, y at the polygon's centroid.
export type Pt = [number, number];

export const MAX_POINTS = 120;
export const MIN_POINTS = 3;
/** A stroke whose extent is smaller than this (screen px) is a click, not an outline. */
export const TINY_PX = 8;

/** Largest extent of a stroke along x or y. */
export function strokeExtent(pts: Pt[]): number {
  if (pts.length === 0) return 0;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [x, y] of pts) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  return Math.max(x1 - x0, y1 - y0);
}

const segDist2 = (p: Pt, a: Pt, b: Pt): number => {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const l2 = dx * dx + dy * dy;
  const t = l2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2));
  const qx = a[0] + t * dx - p[0];
  const qy = a[1] + t * dy - p[1];
  return qx * qx + qy * qy;
};

/** Ramer–Douglas–Peucker on an open polyline (the first and last points are kept). */
export function rdp(pts: Pt[], tol: number): Pt[] {
  if (pts.length < 3) return pts.slice();
  const keep = new Uint8Array(pts.length);
  keep[0] = 1;
  keep[pts.length - 1] = 1;
  const stack: [number, number][] = [[0, pts.length - 1]];
  const tol2 = tol * tol;
  while (stack.length) {
    const [i0, i1] = stack.pop()!;
    let best = -1;
    let bestD = tol2;
    for (let i = i0 + 1; i < i1; i++) {
      const d = segDist2(pts[i], pts[i0], pts[i1]);
      if (d > bestD) { bestD = d; best = i; }
    }
    if (best > 0) { keep[best] = 1; stack.push([i0, best], [best, i1]); }
  }
  return pts.filter((_, i) => keep[i] === 1);
}

/** Drop consecutive duplicates (and a last point equal to the first: the shape closes itself). */
function dedupe(pts: Pt[]): Pt[] {
  const out: Pt[] = [];
  for (const p of pts) {
    const q = out[out.length - 1];
    if (!q || Math.abs(q[0] - p[0]) > 1e-6 || Math.abs(q[1] - p[1]) > 1e-6) out.push(p);
  }
  if (out.length > 1) {
    const a = out[0], b = out[out.length - 1];
    if (Math.abs(a[0] - b[0]) < 1e-6 && Math.abs(a[1] - b[1]) < 1e-6) out.pop();
  }
  return out;
}

/** Simplify a closed stroke to at most `max` vertices: RDP with a growing tolerance until it fits. */
export function simplifyStroke(pts: Pt[], max = MAX_POINTS, tol0 = 0.75): Pt[] {
  let out = dedupe(pts);
  let tol = tol0;
  for (let i = 0; i < 24 && out.length > max; i++) {
    out = dedupe(rdp(out, tol));
    tol *= 1.6;
  }
  // A pathological stroke (every point far apart): keep every n-th vertex.
  if (out.length > max) {
    const step = out.length / max;
    out = Array.from({ length: max }, (_, i) => out[Math.floor(i * step)]);
  }
  return out;
}

/** Signed area (shoelace) of a closed polygon. Positive = clockwise in image space (y down). */
export function polygonArea(poly: Pt[]): number {
  let a = 0;
  for (let i = 0, n = poly.length; i < n; i++) {
    const [x0, y0] = poly[i];
    const [x1, y1] = poly[(i + 1) % n];
    a += x0 * y1 - x1 * y0;
  }
  return a / 2;
}

/** Area centroid of a closed polygon; the mean of the vertices when the polygon is degenerate (zero area). */
export function polygonCentroid(poly: Pt[]): Pt {
  const n = poly.length;
  if (n === 0) return [0, 0];
  const a = polygonArea(poly);
  if (Math.abs(a) < 1e-9) {
    let sx = 0, sy = 0;
    for (const [x, y] of poly) { sx += x; sy += y; }
    return [sx / n, sy / n];
  }
  let cx = 0, cy = 0;
  for (let i = 0; i < n; i++) {
    const [x0, y0] = poly[i];
    const [x1, y1] = poly[(i + 1) % n];
    const cr = x0 * y1 - x1 * y0;
    cx += (x0 + x1) * cr;
    cy += (y0 + y1) * cr;
  }
  return [cx / (6 * a), cy / (6 * a)];
}

/** Translate every vertex. */
export const shiftPolygon = (poly: Pt[], dx: number, dy: number): Pt[] => poly.map(([x, y]) => [x + dx, y + dy]);

/** Clamp every vertex into [0, w] × [0, h]. */
export const clampPolygon = (poly: Pt[], w: number, h: number): Pt[] => poly.map(([x, y]) => [Math.min(w, Math.max(0, x)), Math.min(h, Math.max(0, y))]);

export type FinishedStroke =
  | { kind: 'point'; x: number; y: number }
  | { kind: 'outline'; polygon: Pt[]; x: number; y: number };

/** What a released stroke becomes. `scale` = screen px per image px (the tiny-stroke rule is in screen px). */
export function finishStroke(pts: Pt[], scale: number, max = MAX_POINTS): FinishedStroke | null {
  if (pts.length === 0) return null;
  if (strokeExtent(pts) * scale < TINY_PX) return { kind: 'point', x: pts[0][0], y: pts[0][1] };
  const polygon = simplifyStroke(pts, max);
  if (polygon.length < MIN_POINTS || Math.abs(polygonArea(polygon)) < 1e-6) return { kind: 'point', x: pts[0][0], y: pts[0][1] };
  const [x, y] = polygonCentroid(polygon);
  return { kind: 'outline', polygon, x, y };
}

/** SVG path for a closed polygon. */
export function polygonPath(poly: Pt[]): string {
  if (poly.length === 0) return '';
  return `M ${poly.map(([x, y]) => `${x} ${y}`).join(' L ')} Z`;
}
