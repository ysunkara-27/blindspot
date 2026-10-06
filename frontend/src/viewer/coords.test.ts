import { describe, expect, it } from 'vitest';
import { clampView, clientToImage, fitView, imageToScreen, screenToImage, visibleRect, zoomAt } from './coords';

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

describe('click mapping within 2 px (SPEC §5.4)', () => {
  // 1024×1024 film in an 870×776 stage at (24, 56) on the page, like the 1280×800 layout.
  const stage = { left: 24, top: 56 };
  for (const [imgW, imgH] of [[1024, 1024], [256, 256], [2048, 1536]]) {
    const fit = fitView(870, 776, imgW, imgH, 16);
    for (const zoom of [1, 3]) {
      it(`${imgW}×${imgH} at ${zoom}×`, () => {
        const view = zoom === 1 ? fit : zoomAt(fit, zoom, 435, 388, fit.scale, fit.scale * 6);
        expect(view.scale / fit.scale).toBeCloseTo(zoom, 9);
        // Known image targets; compute where they land on screen, click there, map back.
        const targets = [[imgW * 0.5, imgH * 0.5], [imgW * 0.45, imgH * 0.52], [imgW * 0.55, imgH * 0.48]];
        for (const [tx, ty] of targets) {
          const s = imageToScreen(tx, ty, view);
          // A real click lands on an integer client pixel.
          const cx = Math.round(s.x + stage.left);
          const cy = Math.round(s.y + stage.top);
          const p = clientToImage(cx, cy, stage, view);
          expect(Math.abs(p.x - tx)).toBeLessThanOrEqual(2);
          expect(Math.abs(p.y - ty)).toBeLessThanOrEqual(2);
        }
      });
    }
  }
});

describe('fit and clamp', () => {
  it('fits to height and centres', () => {
    const f = fitView(1000, 500, 1024, 1024);
    expect(f.scale).toBeCloseTo(500 / 1024);
    expect(f.originY).toBeCloseTo(0);
    expect(f.originX).toBeCloseTo(250);
  });
  it('never fits wider than the stage', () => {
    const f = fitView(300, 800, 1024, 1024);
    expect(f.scale * 1024).toBeCloseTo(300);
  });
  it('keeps part of the image visible when panning far away', () => {
    const c = clampView({ originX: -5000, originY: 5000, scale: 1 }, 800, 600, 1024, 1024, 80);
    expect(c.originX).toBe(80 - 1024);
    expect(c.originY).toBe(600 - 80);
  });
});
