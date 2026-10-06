import { describe, expect, it } from 'vitest';
import { arrowGeometry, placeLabels, quadPoint, rayToBoxEdge, shortArrowText } from './arrows';

describe('arrowGeometry', () => {
  it('stops short of the target and keeps the start', () => {
    const g = arrowGeometry([0, 0], [100, 0], 10, 1);
    expect(g.start).toEqual([0, 0]);
    expect(g.end[0]).toBeLessThan(100 - 10);
    expect(g.d.startsWith('M 0 0 Q')).toBe(true);
  });
  it('moves the start away when the source sits on the target', () => {
    const g = arrowGeometry([50, 50], [52, 50], 20, 1);
    expect(Math.hypot(g.start[0] - 52, g.start[1] - 50)).toBeGreaterThan(60);
  });
  it('quadPoint hits the endpoints', () => {
    expect(quadPoint([0, 0], [5, 5], [10, 0], 0)).toEqual([0, 0]);
    expect(quadPoint([0, 0], [5, 5], [10, 0], 1)).toEqual([10, 0]);
  });
});

describe('placeLabels', () => {
  it('separates labels that start in the same place', () => {
    const b = { x: 100, y: 100, w: 200, h: 20 };
    const out = placeLabels([b, b, b], 1024, 1024);
    for (let i = 0; i < out.length; i++) for (let j = i + 1; j < out.length; j++) {
      const a = out[i], c = out[j];
      const overlap = a.x < c.x + c.w && c.x < a.x + a.w && a.y < c.y + c.h && c.y < a.y + a.h;
      expect(overlap).toBe(false);
    }
  });
  it('keeps labels inside the image', () => {
    const [p] = placeLabels([{ x: 1000, y: -10, w: 200, h: 20 }], 1024, 1024);
    expect(p.x + p.w).toBeLessThanOrEqual(1024);
    expect(p.y).toBeGreaterThanOrEqual(0);
  });
});

describe('shortArrowText', () => {
  it('keeps short text and trims long sentences to the last clause', () => {
    expect(shortArrowText('Here: left apex')).toBe('Here: left apex');
    expect(shortArrowText('Your mark was in the right mid zone; the pneumothorax is higher, in the right apex.'))
      .toBe('The pneumothorax is higher, in the right apex.');
    expect(shortArrowText('x'.repeat(80)).length).toBeLessThanOrEqual(46);
  });
  it('avoids obstacles', () => {
    const [p] = placeLabels([{ x: 0, y: 0, w: 50, h: 10 }], 100, 100, [{ x: 0, y: 0, w: 60, h: 12 }]);
    expect(p.y >= 12 || p.x >= 60).toBe(true);
  });
});

describe('placeLabels soft obstacles', () => {
  const ov = (a: { x: number; y: number; w: number; h: number }, b: typeof a) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  it('moves a label off an outline when there is room', () => {
    const outline = { x: 100, y: 100, w: 200, h: 200 };
    const [b] = placeLabels([{ x: 150, y: 150, w: 80, h: 20 }], 1024, 1024, [], [[outline]]);
    expect(ov(b, outline)).toBe(false);
  });
  it('falls back to hard obstacles only when no free spot exists', () => {
    const full = { x: 0, y: 0, w: 100, h: 100 };
    const [b] = placeLabels([{ x: 10, y: 10, w: 50, h: 20 }], 100, 100, [], [[full]]);
    expect(b).toEqual({ x: 10, y: 10, w: 50, h: 20 });
  });
});

describe('rayToBoxEdge', () => {
  it('measures to the side the ray exits through', () => {
    expect(rayToBoxEdge([0, 500], [500, 500], [400, 100, 600, 900])).toBeCloseTo(100);
    expect(rayToBoxEdge([500, 0], [500, 500], [400, 100, 600, 900])).toBeCloseTo(400);
    expect(rayToBoxEdge([0, 0], [500, 500], [400, 400, 600, 600])).toBeCloseTo(Math.SQRT2 * 100);
  });
});
