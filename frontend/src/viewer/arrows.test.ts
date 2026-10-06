import { describe, expect, it } from 'vitest';
import { arrowGeometry, placeLabels, quadPoint, shortArrowText } from './arrows';

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
