import { beforeEach, describe, expect, it } from 'vitest';
import type { RevealFinding, Sign } from '../types/contracts';
import { planeGeom } from './volume/planes';
import { focusSign, signBounds, signSlice, signsOnView, useSigns } from './signs';

const finding = (id: string, signs: Sign[]): RevealFinding => ({ finding_id: id, label: 'effusion', display: 'Effusion', kind: 'focal', bbox: [0, 0, 10, 10], zones: [], signs });
const sign = (id: string, geometry: Sign['geometry']): Sign => ({ id, name: 'Meniscus', text: 'The top of the fluid curves up the chest wall.', geometry });

describe('signsOnView', () => {
  it('maps every X-ray sign in image px and drops the undrawable ones', () => {
    const f = finding('F1', [
      sign('F1:a', { kind: 'polyline', points: [[10, 20], [30, 40]] }),
      sign('F1:b', { kind: 'circle', points: [[50, 50]], radius: 12 }),
      sign('F1:c', { kind: 'circle', points: [[50, 50]] }), // no radius
      sign('F1:d', { kind: 'polygon', points: [[0, 0], [1, 1]] }), // too few points
      sign('F1:e', { kind: 'segment', points: [[0, 0], [9, 9]], plane: 'axial', slice: 3 }), // a volume sign
    ]);
    const out = signsOnView([f]);
    expect(out.map((s) => s.id)).toEqual(['F1:a', 'F1:b']);
    expect(out[0]).toMatchObject({ finding_id: 'F1', kind: 'polyline', points: [[10, 20], [30, 40]], radius: null, name: 'Meniscus' });
    expect(signBounds(out[1])).toEqual([38, 38, 62, 62]);
  });
  it('on a volume keeps only the signs of this plane and slice, in display px of the plane', () => {
    // [nz, ny, nx] = [10, 100, 200], spacing [3, 1, 0.5] mm: axial display px are 0.5 mm, so x stays and y doubles.
    const g = planeGeom({ shape: [10, 100, 200], spacing: [3, 1, 0.5] }, 'axial');
    const f = finding('F1', [
      sign('F1:a', { kind: 'segment', points: [[20, 10], [40, 10]], plane: 'axial', slice: 4 }),
      sign('F1:b', { kind: 'circle', points: [[20, 10]], radius: 5, plane: 'axial', slice: 5 }),
      sign('F1:c', { kind: 'segment', points: [[20, 10], [40, 10]], plane: 'coronal', slice: 4 }),
      sign('F1:d', { kind: 'segment', points: [[20, 10], [40, 10]] }), // no plane: an X-ray sign
    ]);
    expect(signsOnView([f], g, 4).map((s) => [s.id, s.points])).toEqual([['F1:a', [[20, 20], [40, 20]]]]);
    const b = signsOnView([f], g, 5);
    expect(b).toHaveLength(1);
    expect(b[0].radius).toBe(5); // scaled by the smaller display factor
    expect(signSlice([f], 'F1:b')).toEqual({ plane: 'axial', slice: 5 });
    expect(signSlice([f], 'F1:d')).toBeNull();
  });
});

describe('useSigns', () => {
  beforeEach(() => useSigns.getState().reset());
  it('is visible by default; toggle flips it; focusSign pulses and turns the layer on', () => {
    expect(useSigns.getState().visible).toBe(true);
    useSigns.getState().toggle();
    expect(useSigns.getState().visible).toBe(false);
    focusSign('F1:a');
    expect(useSigns.getState().visible).toBe(true);
    expect(useSigns.getState().focused?.id).toBe('F1:a');
    useSigns.getState().clearFocus();
    expect(useSigns.getState().focused).toBeNull();
  });
});

describe('wrapText (sign tips)', () => {
  it('breaks a sentence at spaces into lines of at most the limit', async () => {
    const { wrapText } = await import('./signLabels');
    const lines = wrapText('The heart or diaphragm border is lost where the opacity touches it, which tells you where it sits.', 40);
    expect(lines.length).toBeGreaterThan(1);
    for (const l of lines) expect(l.length).toBeLessThanOrEqual(40);
    expect(lines.join(' ')).toBe('The heart or diaphragm border is lost where the opacity touches it, which tells you where it sits.');
    expect(wrapText('Short.')).toEqual(['Short.']);
  });
});
