import { describe, expect, it } from 'vitest';
import { cohortQuery, niceTicks, calibrationRows, calibrationSplit, curveLabels, curveRows, densityGrid, frocRows, missRows, rollingAccuracy } from './helpers';
import { guardCalibration, guardLearnerDashboard, guardLearningCurve } from './types';

describe('rollingAccuracy', () => {
  it('averages the last `window` outcomes, with a growing window at the start', () => {
    const r = rollingAccuracy([1, 0, 1, 1], 3);
    expect(r.map((x) => x.window_n)).toEqual([1, 2, 3, 3]);
    expect(r.map((x) => +x.success_rate.toFixed(4))).toEqual([1, 0.5, 0.6667, 0.6667]);
  });
  it('matches the backend definition for window 10 over a long run', () => {
    const seq = Array.from({ length: 25 }, (_, i) => (i % 3 === 0 ? 1 : 0) as number);
    const r = rollingAccuracy(seq, 10);
    for (let i = 0; i < seq.length; i++) {
      const w = seq.slice(Math.max(0, i - 9), i + 1);
      expect(r[i].success_rate).toBeCloseTo(w.reduce((a, b) => a + b, 0) / w.length, 10);
    }
  });
  it('handles empty input and booleans', () => {
    expect(rollingAccuracy([])).toEqual([]);
    expect(rollingAccuracy([true, false], 10)[1].success_rate).toBe(0.5);
  });
});

describe('curveRows', () => {
  const lc = guardLearningCurve({
    window: 10, n: 3,
    overall: [{ attempt: 1, success_rate: 0, window_n: 1 }, { attempt: 2, success_rate: 0.5, window_n: 2 }],
    per_label: { effusion: [{ attempt: 1, success_rate: 1 }], normal: [{ attempt: 1, success_rate: 0 }, { attempt: 2, success_rate: 0.5 }] },
  });
  it('maps overall rows to percent', () => {
    expect(curveRows(lc, 'overall')).toEqual([{ attempt: 1, pct: 0, window_n: 1 }, { attempt: 2, pct: 50, window_n: 2 }]);
  });
  it('derives window_n for per-label rows', () => {
    expect(curveRows(lc, 'normal').map((r) => r.window_n)).toEqual([1, 2]);
  });
  it('orders label choices by count', () => {
    expect(curveLabels(lc).map((x) => x.id)).toEqual(['normal', 'effusion']);
  });
  it('returns [] for a missing series', () => {
    expect(curveRows(lc, 'mass')).toEqual([]);
    expect(curveRows(null, 'overall')).toEqual([]);
  });
});

describe('calibration helpers', () => {
  const cal = guardCalibration({
    bins: [
      { confidence: 1, n: 2, correct: 0, accuracy: 0 },
      { confidence: 3, n: 4, correct: 3, accuracy: 0.75 },
      { confidence: 4, n: 3, correct: 1, accuracy: 0.333 },
      { confidence: 5, n: 1, correct: 1, accuracy: 1 },
    ],
    n: 10, confident_misses: 2,
  });
  it('always yields five rows; empty bins are null, not 0%', () => {
    const r = calibrationRows(cal);
    expect(r.map((x) => x.confidence)).toEqual([1, 2, 3, 4, 5]);
    expect(r[1]).toMatchObject({ n: 0, pct: null });
    expect(r[2].pct).toBe(75);
  });
  it('splits sure vs unsure with n', () => {
    const s = calibrationSplit(cal);
    expect(s.sure).toEqual({ n: 4, acc: 0.5 });
    expect(s.unsure).toEqual({ n: 2, acc: 0 });
  });
  it('survives a missing block', () => {
    expect(calibrationRows(null).every((x) => x.n === 0 && x.pct === null)).toBe(true);
    expect(guardCalibration('nope')).toBeNull();
  });
});

describe('other helpers', () => {
  it('missRows totals each window', () => {
    const r = missRows({ window: 10, n: 12, windows: [{ from: 1, to: 10, n: 10, search: 1, recognition: 2, decision: 0, interpretation: 1, overcall: 3 }] });
    expect(r[0]).toMatchObject({ name: '1–10', total: 7, n: 10 });
  });
  it('frocRows sorts strict→lenient and anchors at the origin', () => {
    const r = frocRows({ n_images: 4, n_lesions: 4, n_marks: 3, points: [
      { threshold: 1, llf: 0.5, nlf: 0.25, n_ll: 2, n_nl: 1 }, { threshold: 5, llf: 0.25, nlf: 0, n_ll: 1, n_nl: 0 }, { threshold: 4, llf: null, nlf: null, n_ll: 0, n_nl: 0 },
    ] });
    expect(r.map((x) => x.threshold)).toEqual([6, 5, 1]);
    expect(r[0]).toMatchObject({ nlf: 0, llf: 0 });
  });
  it('densityGrid peaks at 1 near the point', () => {
    const g = densityGrid([{ x: 0.25, y: 0.75 }], 4, 4, 0.1);
    expect(Math.max(...g.flat())).toBe(1);
    expect(g[3][1]).toBe(1);
    expect(densityGrid([], 3, 3).flat().every((v) => v === 0)).toBe(true);
  });
  it('guardLearnerDashboard tolerates garbage', () => {
    const d = guardLearnerDashboard({ n_attempts: 'x', summary: null });
    expect(d.n_attempts).toBe(0);
    expect(d.summary).toBeNull();
    expect(d.learning_curve).toBeNull();
    expect(d.abilities).toEqual([]);
  });
});

describe('niceTicks', () => {
  it('covers the max with clean steps', () => {
    expect(niceTicks(2.6)).toEqual([0, 1, 2, 3]);
    expect(niceTicks(0.7)).toEqual([0, 0.25, 0.5, 0.75]);
    expect(niceTicks(0)).toEqual([0, 0.25]);
    expect(niceTicks(1.2)).toEqual([0, 0.5, 1, 1.5]);
  });
});

describe('cohortQuery', () => {
  it('maps UI filters to API params with an exclusive end date', () => {
    expect(cohortQuery(new URLSearchParams('level=MS3&mode=practice&from=2026-10-01&to=2026-10-05')))
      .toBe('?level=MS3&mode=practice&date_from=2026-10-01&date_to=2026-10-06');
    expect(cohortQuery(new URLSearchParams(''))).toBe('');
    expect(cohortQuery(new URLSearchParams('to=2026-12-31'))).toBe('?date_to=2027-01-01');
  });
});
