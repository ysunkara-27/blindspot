// Marching squares on a binary slice: the 0.5 iso-contour of `inside(value)`, as closed rings in in-plane voxel
// coordinates (pixel (i, j) is centred at (i + 0.5, j + 0.5)). Binary input means every crossing sits at the midpoint
// of a cell edge, so segments join edge midpoints and chain into rings by shared edges. Saddles are split (never joined).
export type Ring = [number, number][];

/** Rings of the region where `inside(slice[v*w+u])` holds. Empty when nothing is inside. */
export function marchingSquares(slice: ArrayLike<number>, w: number, h: number, inside: (v: number) => boolean): Ring[] {
  // Pad with an outside border so every region closes.
  const W = w + 2;
  const H = h + 2;
  const g = new Uint8Array(W * H);
  for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) if (inside(slice[j * w + i])) g[(j + 1) * W + i + 1] = 1;

  // Edge ids: horizontal edge between centres (i, j)-(i+1, j): id = 2*(j*W+i); vertical (i, j)-(i, j+1): id = 2*(j*W+i)+1.
  const hEdge = (i: number, j: number) => 2 * (j * W + i);
  const vEdge = (i: number, j: number) => 2 * (j * W + i) + 1;
  // Adjacency: edge id → up to two neighbouring edge ids (each boundary edge is crossed by exactly two segments).
  const adj = new Map<number, number[]>();
  const link = (a: number, b: number) => {
    (adj.get(a) ?? adj.set(a, []).get(a)!).push(b);
    (adj.get(b) ?? adj.set(b, []).get(b)!).push(a);
  };
  for (let j = 0; j + 1 < H; j++) {
    for (let i = 0; i + 1 < W; i++) {
      const tl = g[j * W + i], tr = g[j * W + i + 1], br = g[(j + 1) * W + i + 1], bl = g[(j + 1) * W + i];
      const c = (tl << 3) | (tr << 2) | (br << 1) | bl;
      if (c === 0 || c === 15) continue;
      const top = hEdge(i, j), bottom = hEdge(i, j + 1), left = vEdge(i, j), right = vEdge(i + 1, j);
      switch (c) {
        case 1: case 14: link(left, bottom); break;
        case 2: case 13: link(bottom, right); break;
        case 3: case 12: link(left, right); break;
        case 4: case 11: link(top, right); break;
        case 6: case 9: link(top, bottom); break;
        case 7: case 8: link(top, left); break;
        case 5: link(top, left); link(bottom, right); break; // saddle: tl + br inside → two separate corners
        case 10: link(top, right); link(bottom, left); break;
      }
    }
  }
  // Midpoint of an edge in unpadded voxel coords.
  const point = (id: number): [number, number] => {
    const cell = id >> 1;
    const i = cell % W;
    const j = (cell - i) / W;
    // Padded centre (i, j) sits at (i - 0.5, j - 0.5) in unpadded voxel coords; the midpoint of the edge to the next
    // centre along x is (i, j - 0.5), along y it is (i - 0.5, j).
    return id & 1 ? [i - 0.5, j] : [i, j - 0.5];
  };
  const rings: Ring[] = [];
  const seen = new Set<number>();
  for (const start of adj.keys()) {
    if (seen.has(start)) continue;
    const ring: Ring = [];
    let prev = -1;
    let cur = start;
    while (!seen.has(cur)) {
      seen.add(cur);
      ring.push(point(cur));
      const nb = adj.get(cur) ?? [];
      const next = nb.find((n) => n !== prev && !seen.has(n));
      if (next === undefined) break;
      prev = cur;
      cur = next;
    }
    if (ring.length >= 3) rings.push(simplify(ring));
  }
  return rings;
}

/** Drop points that sit on a straight line between their neighbours (long runs of a flat edge). */
function simplify(r: Ring): Ring {
  if (r.length < 4) return r;
  const out: Ring = [];
  for (let i = 0; i < r.length; i++) {
    const a = r[(i + r.length - 1) % r.length], b = r[i], c = r[(i + 1) % r.length];
    const cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]);
    if (Math.abs(cross) > 1e-9) out.push(b);
  }
  return out.length >= 3 ? out : r;
}

export function ringBounds(rings: Ring[]): [number, number, number, number] | null {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const r of rings) for (const [x, y] of r) {
    if (x < x0) x0 = x;
    if (y < y0) y0 = y;
    if (x > x1) x1 = x;
    if (y > y1) y1 = y;
  }
  return Number.isFinite(x0 + y0 + x1 + y1) ? [x0, y0, x1, y1] : null;
}

/** Shoelace area (absolute) of one ring. */
export function ringArea(r: Ring): number {
  let a = 0;
  for (let i = 0; i < r.length; i++) {
    const [x0, y0] = r[i];
    const [x1, y1] = r[(i + 1) % r.length];
    a += x0 * y1 - x1 * y0;
  }
  return Math.abs(a) / 2;
}
