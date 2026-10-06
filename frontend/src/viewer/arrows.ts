// Grease-pencil arrow geometry (SPEC §14.3 step 3), in image px. k = image px per screen px.
export type Pt = [number, number];

export function arrowGeometry(from: Pt, to: Pt, targetRadius: number, k: number) {
  let [fx, fy] = from;
  const [tx, ty] = to;
  let len = Math.hypot(tx - fx, ty - fy);
  // Too close to sweep: start from a point up and to the side, 90 screen px away.
  if (len < targetRadius + 40 * k) {
    fx = tx - 64 * k * Math.sign(tx - fx || 1);
    fy = ty - 64 * k;
    len = Math.hypot(tx - fx, ty - fy);
  }
  const ux = (tx - fx) / len;
  const uy = (ty - fy) / len;
  // Stop just short of the outline.
  const stop = Math.min(len * 0.8, targetRadius + 6 * k);
  const ex = tx - ux * stop;
  const ey = ty - uy * stop;
  // Hand-drawn bow: control point offset perpendicular by 12% of the length.
  const bow = 0.12 * Math.hypot(ex - fx, ey - fy);
  const cx = (fx + ex) / 2 - uy * bow;
  const cy = (fy + ey) / 2 + ux * bow;
  const d = `M ${fx} ${fy} Q ${cx} ${cy} ${ex} ${ey}`;
  // Arrowhead: tangent at the end of a quadratic is (end − control).
  const tl = Math.hypot(ex - cx, ey - cy) || 1;
  const dx = (ex - cx) / tl;
  const dy = (ey - cy) / tl;
  const h = 14 * k;
  const a = (28 * Math.PI) / 180;
  const rot = (x: number, y: number, ang: number): Pt => [x * Math.cos(ang) - y * Math.sin(ang), x * Math.sin(ang) + y * Math.cos(ang)];
  const [l1x, l1y] = rot(-dx, -dy, a);
  const [l2x, l2y] = rot(-dx, -dy, -a);
  const head = `M ${ex + l1x * h} ${ey + l1y * h} L ${ex} ${ey} L ${ex + l2x * h} ${ey + l2y * h}`;
  return { d, head, start: [fx, fy] as Pt, ctrl: [cx, cy] as Pt, end: [ex, ey] as Pt };
}

/** Distance from `to` (inside the box) to the edge of `bbox` along the ray towards `from`: where the arrow should stop
 *  so it touches the outline's extent instead of halting in mid-air on long, thin outlines. */
export function rayToBoxEdge(from: Pt, to: Pt, bbox: readonly [number, number, number, number]): number {
  const dx = from[0] - to[0];
  const dy = from[1] - to[1];
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  const tx = ux > 1e-9 ? (bbox[2] - to[0]) / ux : ux < -1e-9 ? (bbox[0] - to[0]) / ux : Infinity;
  const ty = uy > 1e-9 ? (bbox[3] - to[1]) / uy : uy < -1e-9 ? (bbox[1] - to[1]) / uy : Infinity;
  const t = Math.min(tx, ty);
  return Number.isFinite(t) && t > 0 ? t : 0;
}

/** Point on the quadratic curve at t (used to anchor arrow text at the middle of the sweep). */
export function quadPoint(s: Pt, c: Pt, e: Pt, t: number): Pt {
  const u = 1 - t;
  return [u * u * s[0] + 2 * u * t * c[0] + t * t * e[0], u * u * s[1] + 2 * u * t * c[1] + t * t * e[1]];
}

export type Box = { x: number; y: number; w: number; h: number };

const overlaps = (a: Box, b: Box) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/** Greedy label placement: nudge each box vertically (then sideways) until it overlaps nothing placed before it.
 *  Boxes are kept inside [0, W] × [0, H]. `avoid[i]` lists soft obstacles for box i (e.g. expert outlines it must not
 *  cover): they are honoured when a free spot exists within a few lines, and dropped otherwise (a far label detaches).
 *  Returns the placed boxes in input order. */
export function placeLabels(boxes: Box[], W: number, H: number, obstacles: Box[] = [], avoid: Box[][] = []): Box[] {
  const placed: Box[] = [...obstacles];
  const clampBox = (b: Box): Box => ({ ...b, x: Math.min(Math.max(0, b.x), Math.max(0, W - b.w)), y: Math.min(Math.max(0, b.y), Math.max(0, H - b.h)) });
  const search = (b0: Box, blockers: Box[], rings: number): Box | null => {
    const step = b0.h * 1.05;
    for (let ring = 0; ring < rings; ring++) {
      for (const [dx, dy] of ring === 0 ? [[0, 0]] : [[0, -ring * step], [0, ring * step], [b0.w * 0.5 * Math.ceil(ring / 2), ring * step * 0.5], [-b0.w * 0.5 * Math.ceil(ring / 2), -ring * step * 0.5]]) {
        const cand = clampBox({ ...b0, x: b0.x + dx, y: b0.y + dy });
        if (!blockers.some((p) => overlaps(p, cand))) return cand;
      }
    }
    return null;
  };
  boxes.forEach((b0, i) => {
    const soft = avoid[i] ?? [];
    // Soft obstacles may push a label only a few lines away; further than that it would detach from its mark.
    placed.push((soft.length ? search(b0, [...placed, ...soft], 5) : null) ?? search(b0, placed, 18) ?? clampBox(b0));
  });
  return placed.slice(obstacles.length);
}

/** Film label for an arrow: the backend sentence can be long; on the film keep the last clause, ≤ max chars. */
export function shortArrowText(text: string, max = 46): string {
  let t = text.trim();
  if (t.length > max && t.includes(';')) t = t.slice(t.lastIndexOf(';') + 1).trim();
  if (t.length > max) t = `${t.slice(0, max - 1).trimEnd()}…`;
  return t.charAt(0).toUpperCase() + t.slice(1);
}
