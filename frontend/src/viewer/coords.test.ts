import { describe, expect, it } from 'vitest';
import { clampView, clientToImage, clientToPlane, displayToPlane, fitView, imageToScreen, planeToScreen, screenToImage, visibleRect, zoomAt } from './coords';
import { planeGeom } from './volume/planes';

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

describe('volumes: a click on a slice becomes a 3-D mark through the same transform', () => {
  const meta = { shape: [16, 64, 64], spacing: [3, 1.5, 1.5] };
  const stage = { left: 24, top: 56 };
  it('axial: in-plane coords are x, y and the voxel carries the slice', () => {
    const g = planeGeom(meta, 'axial');
    const view = fitView(870, 776, g.W, g.H, 16);
    const target = imageToScreen(24.5, 36.25, view);
    const p = clientToPlane(target.x + stage.left, target.y + stage.top, stage, view, g, 8);
    expect(p.x).toBeCloseTo(24.5, 6);
    expect(p.y).toBeCloseTo(36.25, 6);
    expect(p.voxel[0]).toBeCloseTo(24.5, 6);
    expect(p.voxel[1]).toBeCloseTo(36.25, 6);
    expect(p.voxel[2]).toBe(8);
    expect(p.plane).toBe('axial');
    const back = planeToScreen(p.x, p.y, g, view);
    expect(back.x).toBeCloseTo(target.x, 6);
    expect(back.y).toBeCloseTo(target.y, 6);
  });
  it('coronal: display px down are stretched by the slice spacing, in-plane y is z', () => {
    const g = planeGeom(meta, 'coronal'); // 64 × 32 display px for 64 × 16 voxels
    const view = fitView(870, 776, g.W, g.H, 16);
    const target = imageToScreen(10, 20, view); // 20 display px down = z 10
    const p = clientToPlane(target.x + stage.left, target.y + stage.top, stage, view, g, 33);
    expect(p.x).toBeCloseTo(10, 6);
    expect(p.y).toBeCloseTo(10, 6);
    expect(p.voxel.map((n) => Math.round(n * 1e6) / 1e6)).toEqual([10, 33, 10]);
    expect(displayToPlane(10, 20, g, 33).voxel).toEqual([10, 33, 10]);
  });
  it('sagittal: across is y, down is z, the slice is x', () => {
    const g = planeGeom(meta, 'sagittal');
    expect(displayToPlane(40, 6, g, 12).voxel).toEqual([12, 40, 3]);
  });
});
