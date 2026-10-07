import { describe, expect, it } from 'vitest';
import { initialNav, setSlice, showGrid, showPlane, stepSlice, wheelNotches } from './nav';

const meta = { shape: [16, 64, 64], spacing: [3, 1.5, 1.5] };

describe('volume navigation', () => {
  it('opens as a grid in the middle of each plane', () => {
    const n = initialNav(meta);
    expect(n.grid).toBe(true);
    expect(n.slice).toEqual({ axial: 8, coronal: 32, sagittal: 32 });
  });
  it('steps and clamps slices per plane', () => {
    let n = initialNav(meta);
    n = stepSlice(n, meta, 'axial', 20);
    expect(n.slice.axial).toBe(15);
    n = stepSlice(n, meta, 'coronal', -40);
    expect(n.slice.coronal).toBe(0);
    expect(setSlice(n, meta, 'coronal', 0)).toBe(n); // unchanged → same object
  });
  it('switches between the grid and a single plane', () => {
    let n = showPlane(initialNav(meta), meta, 'coronal', 10);
    expect(n).toMatchObject({ grid: false, plane: 'coronal' });
    expect(n.slice.coronal).toBe(10);
    n = showGrid(n);
    expect(n.grid).toBe(true);
    expect(n.plane).toBe('coronal');
  });
  it('one mouse notch is one slice; trackpad deltas accumulate', () => {
    expect(wheelNotches(0, 100, 0)).toEqual({ acc: 0, steps: 1 });
    expect(wheelNotches(0, -120, 0)).toEqual({ acc: 0, steps: -1 });
    let r = wheelNotches(0, 12, 0);
    expect(r.steps).toBe(0);
    r = wheelNotches(r.acc, 12, 0);
    r = wheelNotches(r.acc, 12, 0);
    expect(r.steps).toBe(1);
    expect(wheelNotches(0, 1, 1).steps).toBe(1); // deltaMode lines
  });
});
