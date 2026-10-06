import { describe, expect, it } from 'vitest';
import { imageToScreen, screenToImage, visibleRect, zoomAt } from './coords';

describe('coords', () => {
  const v = { originX: 100, originY: 20, scale: 0.75 };
  it('round-trips within 1e-9', () => {
    const p = imageToScreen(512, 300, v);
    const q = screenToImage(p.x, p.y, v);
    expect(q.x).toBeCloseTo(512, 9);
    expect(q.y).toBeCloseTo(300, 9);
  });
  it('keeps the cursor point fixed when zooming', () => {
    const before = screenToImage(400, 300, v);
    const z = zoomAt(v, 3, 400, 300, 0.1, 10);
    const after = screenToImage(400, 300, z);
    expect(after.x).toBeCloseTo(before.x, 9);
    expect(after.y).toBeCloseTo(before.y, 9);
    expect(z.scale).toBeCloseTo(2.25);
  });
  it('clamps the visible rect to the image', () => {
    expect(visibleRect(1000, 800, v, 1024, 1024)).toEqual([0, 0, 1024, 1024]);
  });
});
