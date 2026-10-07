// Pure helpers behind the dashboard charts (unit-tested in helpers.test.ts). No React, no fetch.
import type { BlindspotPoint, Calibration, CurvePoint, Froc, LearningCurve, MissTypeMix } from './types';
import { MISS_BUCKETS } from './types';

/** Below this many reads a percentage says more about chance than about the reader, so none is shown. */
export const MIN_READS = 5;
export const enoughReads = (n: number | null | undefined): boolean => typeof n === 'number' && Number.isFinite(n) && n >= MIN_READS;
/** How many more films until the first numbers appear (0 once there are enough). */
export const readsToGo = (n: number | null | undefined): number => Math.max(0, MIN_READS - Math.max(0, Math.floor(typeof n === 'number' && Number.isFinite(n) ? n : 0)));

export const pct = (v: number | null | undefined, digits = 0): string =>
  v == null || !Number.isFinite(v) ? '—' : `${(v * 100).toFixed(digits)}%`;

/**
 * Rolling accuracy (SPEC §10.1): at attempt i the mean of the last `window` outcomes (fewer at the start).
 * Mirrors backend/app/analytics/learner.py::learning_curve so per-label rows can be checked or rebuilt client side.
 */
export function rollingAccuracy(outcomes: ReadonlyArray<boolean | number>, window = 10): Required<Pick<CurvePoint, 'attempt' | 'success_rate' | 'window_n'>>[] {
  const w = Math.max(1, Math.floor(window));
  const out: { attempt: number; success_rate: number; window_n: number }[] = [];
  let sum = 0;
  for (let i = 0; i < outcomes.length; i++) {
    sum += Number(outcomes[i]);
    if (i >= w) sum -= Number(outcomes[i - w]);
    const n = Math.min(i + 1, w);
    out.push({ attempt: i + 1, success_rate: sum / n, window_n: n });
  }
  return out;
}

export type CurveRow = { attempt: number; pct: number; window_n: number };

/** Chart rows for one learning-curve series. `key` is 'overall' or a label id. Per-label rows lack window_n; derive it. */
export function curveRows(lc: LearningCurve | null, key: string): CurveRow[] {
  if (!lc) return [];
  const pts = key === 'overall' ? lc.overall : (lc.per_label[key] ?? []);
  return pts.map((p) => ({
    attempt: p.attempt,
    pct: Math.round(p.success_rate * 1000) / 10,
    window_n: p.window_n ?? Math.min(p.attempt, lc.window),
  }));
}

/** Label choices for the per-label toggle, most-seen first. */
export function curveLabels(lc: LearningCurve | null): { id: string; n: number }[] {
  if (!lc) return [];
  return Object.entries(lc.per_label)
    .map(([id, pts]) => ({ id, n: pts.length }))
    .filter((x) => x.n > 0)
    .sort((a, b) => b.n - a.n || a.id.localeCompare(b.id));
}

export const CONFIDENCE_WORDS: Record<number, string> = { 1: 'Guess', 2: 'Unsure', 3: 'Fair', 4: 'Fairly sure', 5: 'Certain' };

export type CalibrationRow = { confidence: number; word: string; n: number; correct: number; pct: number | null };

/** Calibration rows for confidence 1–5 (always five rows, so the axis never shifts). */
export function calibrationRows(cal: Calibration | null): CalibrationRow[] {
  return [1, 2, 3, 4, 5].map((c) => {
    const b = cal?.bins.find((x) => x.confidence === c);
    const n = b?.n ?? 0;
    const correct = b?.correct ?? 0;
    return { confidence: c, word: CONFIDENCE_WORDS[c], n, correct, pct: n > 0 ? Math.round((correct / n) * 1000) / 10 : null };
  });
}

/** Accuracy when sure (confidence ≥ 4) vs unsure (≤ 2), with n — the one-line calibration read-out. */
export function calibrationSplit(cal: Calibration | null): { sure: { n: number; acc: number | null }; unsure: { n: number; acc: number | null } } {
  const rows = calibrationRows(cal);
  const agg = (pred: (c: number) => boolean) => {
    const r = rows.filter((x) => pred(x.confidence));
    const n = r.reduce((s, x) => s + x.n, 0);
    const k = r.reduce((s, x) => s + x.correct, 0);
    return { n, acc: n ? k / n : null };
  };
  return { sure: agg((c) => c >= 4), unsure: agg((c) => c <= 2) };
}

export type MissRow = { name: string; n: number; total: number } & Record<(typeof MISS_BUCKETS)[number], number>;

export function missRows(mix: MissTypeMix | null): MissRow[] {
  if (!mix) return [];
  return mix.windows.map((w) => ({
    name: w.from === w.to ? `${w.from}` : `${w.from}–${w.to}`,
    n: w.n,
    total: MISS_BUCKETS.reduce((s, b) => s + w[b], 0),
    ...Object.fromEntries(MISS_BUCKETS.map((b) => [b, w[b]])),
  })) as MissRow[];
}

export type FrocRow = { threshold: number; nlf: number; llf: number; n_ll: number; n_nl: number };

/** FROC operating points from strictest (≥5) to most lenient (≥1), anchored at the origin. */
export function frocRows(f: Froc | null): FrocRow[] {
  if (!f) return [];
  const pts = f.points
    .filter((p) => p.llf != null && p.nlf != null)
    .sort((a, b) => b.threshold - a.threshold)
    .map((p) => ({ threshold: p.threshold, nlf: p.nlf as number, llf: p.llf as number, n_ll: p.n_ll, n_nl: p.n_nl }));
  return pts.length ? [{ threshold: 6, nlf: 0, llf: 0, n_ll: 0, n_nl: 0 }, ...pts] : [];
}

/**
 * Gaussian kernel density of points in the unit square on an nx × ny grid, normalised so the peak is 1.
 * Used for the blind-spot map (misses only). Bandwidth in unit-square coordinates.
 */
export function densityGrid(points: ReadonlyArray<Pick<BlindspotPoint, 'x' | 'y'>>, nx = 28, ny = 28, bw = 0.08): number[][] {
  const g = Array.from({ length: ny }, () => new Array<number>(nx).fill(0));
  if (!points.length) return g;
  let peak = 0;
  for (let j = 0; j < ny; j++) {
    const cy = (j + 0.5) / ny;
    for (let i = 0; i < nx; i++) {
      const cx = (i + 0.5) / nx;
      let s = 0;
      for (const p of points) {
        const dx = cx - p.x;
        const dy = cy - p.y;
        s += Math.exp(-(dx * dx + dy * dy) / (2 * bw * bw));
      }
      g[j][i] = s;
      if (s > peak) peak = s;
    }
  }
  return peak > 0 ? g.map((row) => row.map((v) => v / peak)) : g;
}

/** Clean axis ticks (0, 0.25, 0.5 … / 0, 0.5, 1 … / 0, 1, 2 …) covering `max`. */
export function niceTicks(max: number): number[] {
  const step = max <= 1 ? 0.25 : max <= 2.5 ? 0.5 : max <= 6 ? 1 : 2;
  const top = Math.max(step, Math.ceil(max / step) * step);
  return Array.from({ length: Math.round(top / step) + 1 }, (_, i) => +(i * step).toFixed(2));
}

/** UI dates are inclusive days; the API's date_to is exclusive, so send the day after. */
export function cohortQuery(p: URLSearchParams): string {
  const q = new URLSearchParams();
  const level = p.get('level');
  const mode = p.get('mode');
  const from = p.get('from');
  const to = p.get('to');
  if (level) q.set('level', level);
  if (mode) q.set('mode', mode);
  if (from) q.set('date_from', from);
  if (to) {
    const t = new Date(`${to}T00:00:00Z`);
    if (!Number.isNaN(t.getTime())) { t.setUTCDate(t.getUTCDate() + 1); q.set('date_to', t.toISOString().slice(0, 10)); }
  }
  const qs = q.toString();
  return qs ? `?${qs}` : '';
}

/** Round 4: does the reading log need a scan-type switch? Only once the library or this log holds something besides
 *  chest films (health `cases_by_modality` / `modalities`, or the dashboard's `n_by_modality`). */
export function showScopeSwitch(
  h: { cases_by_modality?: Record<string, number> | null; modalities?: string[] | null } | null | undefined,
  d: { n_by_modality: Record<string, number> | null } | null | undefined,
): boolean {
  const by = h?.cases_by_modality;
  if (by && ((by.ct ?? 0) > 0 || (by.mr ?? 0) > 0)) return true;
  if (!by && h?.modalities?.some((m) => m === 'ct' || m === 'mr')) return true;
  const n = d?.n_by_modality;
  return !!n && ((n.ct ?? 0) > 0 || (n.mr ?? 0) > 0);
}
