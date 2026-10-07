import { describe, expect, it } from 'vitest';
import { finishStroke, MAX_POINTS, polygonArea, polygonCentroid, rdp, shiftPolygon, simplifyStroke, strokeExtent, type Pt } from './stroke';

const circle = (cx: number, cy: number, r: number, n: number): Pt[] =>
  Array.from({ length: n }, (_, i) => [cx + r * Math.cos((2 * Math.PI * i) / n), cy + r * Math.sin((2 * Math.PI * i) / n)]);

describe('stroke simplification', () => {
  it('keeps a straight line as its two ends', () => {
    const pts: Pt[] = Array.from({ length: 50 }, (_, i) => [i * 2, i * 2 + (i % 2) * 0.1]);
    expect(rdp(pts, 0.5)).toEqual([pts[0], pts[49]]);
  });
  it('simplifies a dense trace to at most 120 points and keeps its shape', () => {
    const dense = circle(300, 300, 120, 2000);
    const out = simplifyStroke(dense);
    expect(out.length).toBeLessThanOrEqual(MAX_POINTS);
    expect(out.length).toBeGreaterThanOrEqual(12);
    // Area within 3 % of the true circle, centroid within a pixel.
    expect(Math.abs(Math.abs(polygonArea(out)) - Math.PI * 120 * 120) / (Math.PI * 120 * 120)).toBeLessThan(0.03);
    const [cx, cy] = polygonCentroid(out);
    expect(Math.abs(cx - 300)).toBeLessThan(1);
    expect(Math.abs(cy - 300)).toBeLessThan(1);
  });
  it('drops duplicate points and a closing point equal to the first', () => {
    expect(simplifyStroke([[0, 0], [0, 0], [10, 0], [10, 10], [10, 10], [0, 10], [0, 0]])).toEqual([[0, 0], [10, 0], [10, 10], [0, 10]]);
  });
});

describe('polygon geometry', () => {
  it('computes the area centroid of a square and a triangle', () => {
    expect(polygonCentroid([[0, 0], [10, 0], [10, 10], [0, 10]])).toEqual([5, 5]);
    const [tx, ty] = polygonCentroid([[0, 0], [30, 0], [0, 30]]);
    expect(tx).toBeCloseTo(10);
    expect(ty).toBeCloseTo(10);
  });
  it('falls back to the vertex mean for a degenerate polygon', () => {
    expect(polygonCentroid([[0, 0], [10, 0], [20, 0]])).toEqual([10, 0]);
  });
  it('shifts every vertex', () => {
    expect(shiftPolygon([[1, 1], [2, 2]], 3, -1)).toEqual([[4, 0], [5, 1]]);
  });
  it('measures the extent of a stroke', () => {
    expect(strokeExtent([[2, 3], [5, 9]])).toBe(6);
    expect(strokeExtent([])).toBe(0);
  });
});

describe('finishStroke', () => {
  it('turns a tiny stroke (< 8 screen px) into a point mark at its start', () => {
    const r = finishStroke([[100, 100], [102, 101], [103, 103]], 1);
    expect(r).toEqual({ kind: 'point', x: 100, y: 100 });
    // The rule is in screen px: the same stroke zoomed 4× is an outline-sized gesture, but with no area it is still a point.
    expect(finishStroke([[100, 100], [103, 100], [106, 100]], 4)?.kind).toBe('point');
  });
  it('closes a traced shape into a polygon with x, y at its centroid', () => {
    const r = finishStroke(circle(200, 150, 40, 300), 1);
    expect(r?.kind).toBe('outline');
    if (r?.kind !== 'outline') return;
    expect(r.polygon.length).toBeGreaterThanOrEqual(3);
    expect(r.polygon.length).toBeLessThanOrEqual(MAX_POINTS);
    expect(r.x).toBeCloseTo(200, 0);
    expect(r.y).toBeCloseTo(150, 0);
  });
  it('returns null for no points', () => {
    expect(finishStroke([], 1)).toBeNull();
  });
});
