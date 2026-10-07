import { describe, expect, it } from 'vitest';
import { downsample, MAX_EVENTS, TelemetryBuffer } from './telemetry';

const S = { x: 10, y: 20, zoom: 1, vp: [0, 0, 1024, 1024] as [number, number, number, number], loupe: true };

function clock() {
  let t = 1000;
  return { now: () => t, tick: (ms: number) => { t += ms; } };
}

describe('TelemetryBuffer', () => {
  it('throttles moves to 33 ms', () => {
    const c = clock();
    const b = new TelemetryBuffer(c.now);
    b.start();
    // 1 s of mouse movement reported every 8 ms (a 120 Hz mouse)
    for (let i = 0; i < 125; i++) { b.push('move', S); c.tick(8); }
    expect(b.length).toBeGreaterThanOrEqual(29);
    expect(b.length).toBeLessThanOrEqual(35);
    const ts = b.snapshot().map((e) => e.t);
    for (let i = 1; i < ts.length; i++) expect(ts[i] - ts[i - 1]).toBeGreaterThanOrEqual(29);
  });
  it('yields ≥ 30 events per 10 s of movement', () => {
    const c = clock();
    const b = new TelemetryBuffer(c.now);
    b.start();
    for (let i = 0; i < 600; i++) { b.push('move', S); c.tick(1000 / 60); }
    expect(b.length).toBeGreaterThanOrEqual(290); // ~30 Hz from a 60 Hz pointer
  });
  it('never throttles toggles and viewport changes', () => {
    const c = clock();
    const b = new TelemetryBuffer(c.now);
    b.start();
    b.push('move', S);
    expect(b.push('wheel', S)).toBe(true);
    expect(b.push('loupe', { ...S, loupe: false })).toBe(true);
    expect(b.push('wl', S)).toBe(true);
    expect(b.push('move', S)).toBe(false);
    expect(b.length).toBe(4);
  });
  it('omits x/y when off the image and keeps t relative to start', () => {
    const c = clock();
    const b = new TelemetryBuffer(c.now);
    c.tick(500);
    b.start();
    c.tick(40);
    b.push('leave', { zoom: 1, vp: [0, 0, 1, 1], loupe: false });
    const [e] = b.snapshot();
    expect(e.t).toBe(40);
    expect('x' in e).toBe(false);
  });
  it('downsamples to the cap', () => {
    const c = clock();
    const b = new TelemetryBuffer(c.now, 100);
    b.start();
    for (let i = 0; i < 1000; i++) { b.push('wheel', S); c.tick(1); }
    const snap = b.snapshot();
    expect(snap.length).toBe(100);
    expect(snap[0].t).toBe(0);
    expect(snap[99].t).toBe(999);
  });
});

describe('downsample', () => {
  it('is uniform and keeps endpoints', () => {
    const a = Array.from({ length: 50_000 }, (_, i) => i);
    const d = downsample(a, MAX_EVENTS);
    expect(d.length).toBe(MAX_EVENTS);
    expect(d[0]).toBe(0);
    expect(d[d.length - 1]).toBe(49_999);
    const gaps = d.slice(1).map((v, i) => v - d[i]);
    expect(Math.max(...gaps) - Math.min(...gaps)).toBeLessThanOrEqual(1);
  });
  it('returns a copy when under the cap', () => {
    const a = [1, 2, 3];
    expect(downsample(a, 10)).toEqual(a);
  });
});

describe('volumes', () => {
  it('records plane and slice on every event, and throttles window drags like moves', () => {
    let t = 0;
    const b = new TelemetryBuffer(() => t, 100);
    b.start();
    const s = (slice: number) => ({ zoom: 1, vp: [0, 0, 64, 64] as [number, number, number, number], loupe: false, plane: 'axial' as const, slice, x: 1, y: 2 });
    expect(b.push('slice', s(3))).toBe(true);
    t = 5;
    expect(b.push('window', s(3))).toBe(true);
    t = 10;
    expect(b.push('window', s(3))).toBe(false); // within 33 ms of the last throttled event
    t = 50;
    expect(b.push('plane', { ...s(0), plane: 'coronal' })).toBe(true);
    const ev = b.snapshot();
    expect(ev.map((e) => e.kind)).toEqual(['slice', 'window', 'plane']);
    expect(ev[0]).toMatchObject({ plane: 'axial', slice: 3, x: 1, y: 2 });
    expect(ev[2]).toMatchObject({ plane: 'coronal', slice: 0 });
    // An X-ray sample has no plane: nothing is added.
    b.push('move', { zoom: 1, vp: [0, 0, 1, 1], loupe: false });
    expect('plane' in b.snapshot()[3]).toBe(false);
  });
});
