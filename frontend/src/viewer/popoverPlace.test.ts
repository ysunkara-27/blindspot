import { describe, expect, it } from 'vitest';
import { clearsMark, placePopover } from './popoverPlace';

const size = { w: 340, h: 320 };
const stage = { w: 870, h: 660 };

describe('placePopover', () => {
  it('goes to the right of the mark when there is room, clear of the mark', () => {
    const m = { x: 200, y: 300 };
    const p = placePopover(m, size, stage, 16);
    expect(p.side).toBe('right');
    expect(p.left).toBeGreaterThanOrEqual(m.x + 16);
    expect(clearsMark(p, size, m, 16)).toBe(true);
  });
  it('flips to the left near the right edge', () => {
    const m = { x: 800, y: 300 };
    const p = placePopover(m, size, stage, 16);
    expect(p.side).toBe('left');
    expect(p.left + size.w).toBeLessThanOrEqual(m.x - 16);
  });
  it('never covers the mark, and keeps off the magnifier lens wherever a lens-clear spot exists', () => {
    const lens = 90;
    let lensCovered = 0;
    let n = 0;
    for (let x = 20; x <= 850; x += 83) for (let y = 20; y <= 640; y += 62) {
      const m = { x, y };
      const p = placePopover(m, size, stage, lens);
      n++;
      expect(clearsMark(p, size, m, 20), `mark at ${x},${y} → ${p.side}`).toBe(true);
      if (!clearsMark(p, size, m, lens)) lensCovered++;
      expect(p.left).toBeGreaterThanOrEqual(8);
      expect(p.left + size.w).toBeLessThanOrEqual(stage.w - 8);
      expect(p.top).toBeGreaterThanOrEqual(8);
      expect(p.top + size.h).toBeLessThanOrEqual(stage.h - 8);
    }
    // Only the dead centre of the stage (too little room on every side for the full popover) may touch the lens.
    expect(lensCovered).toBeLessThanOrEqual(2);
    expect(n).toBeGreaterThan(100);
  });
  it('the short "How sure are you?" popover always clears the lens', () => {
    const small = { w: 300, h: 150 };
    for (let x = 20; x <= 850; x += 41) for (let y = 20; y <= 640; y += 31) {
      const m = { x, y };
      expect(clearsMark(placePopover(m, small, stage, 90), small, m, 90), `mark at ${x},${y}`).toBe(true);
    }
  });
  it('stays on the stage vertically', () => {
    const top = placePopover({ x: 200, y: 5 }, size, stage, 16);
    expect(top.top).toBeGreaterThanOrEqual(8);
    const bottom = placePopover({ x: 200, y: 655 }, size, stage, 16);
    expect(bottom.top + size.h).toBeLessThanOrEqual(stage.h - 8);
  });
  it('the connector runs from the mark to the popover edge', () => {
    const m = { x: 200, y: 300 };
    const p = placePopover(m, size, stage, 90);
    expect(p.from.x).toBeGreaterThan(m.x);
    expect(p.to.x).toBe(p.left);
    expect(p.to.y).toBeGreaterThanOrEqual(p.top);
    expect(p.to.y).toBeLessThanOrEqual(p.top + size.h);
  });
  it('a small stage still keeps the popover inside it', () => {
    const p = placePopover({ x: 150, y: 150 }, size, { w: 360, h: 340 }, 90);
    expect(p.left).toBeGreaterThanOrEqual(8);
    expect(p.left + size.w).toBeLessThanOrEqual(360 - 8);
  });
});
