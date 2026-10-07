import { describe, expect, it } from 'vitest';
import { dwellText, plainText, scoreSentence, searchLines, whyLine } from './copy';

describe('dwellText', () => {
  it('never says "0 ms"', () => {
    for (const v of [0, 40, 99, null, undefined, NaN]) expect(dwellText(v)).toBe('no time spent there');
  });
  it('says seconds in words above 100 ms', () => {
    expect(dwellText(100)).toBe('about 0.1 s there');
    expect(dwellText(350)).toBe('about 0.4 s there');
    expect(dwellText(1240)).toBe('about 1.2 s there');
    expect(dwellText(12_400)).toBe('about 12 s there');
  });
});

describe('plainText', () => {
  it('rewrites raw dwell numbers and the old lens name in server text', () => {
    expect(plainText('F1 Nodule — right upper zone: Never looked there; dwell 0 ms.')).toBe('F1 Nodule — right upper zone: Never looked there; no time spent there.');
    expect(plainText('Missed (dwell 450 ms). Use the loupe.')).toBe('Missed (about 0.5 s there). Use the magnifier.');
    expect(plainText('dwell 2.0 s')).toBe('about 2.0 s there');
    expect(plainText('Nothing to change here.')).toBe('Nothing to change here.');
  });
});

describe('whyLine', () => {
  it('gives one line per outcome and never a raw dwell number', () => {
    expect(whyLine('missed_search', { dwell_ms: 0 })).toBe('No time spent there.');
    expect(whyLine('missed_recognition', { dwell_ms: 420 })).toBe('Your cursor passed through: about 0.4 s there.');
    expect(whyLine('missed_decision', { dwell_ms: 2300 })).toBe('You stayed about 2.3 s there and left it unmarked.');
    expect(whyLine('mislabeled', { learner_label: 'mass' })).toBe('Right place; you called it mass.');
    expect(whyLine('mislabeled', { learner_label: 'not_sure' })).toBe('Right place; you were not sure what it was.');
    expect(whyLine('false_positive', { learner_label: 'nodule' })).toBe('Radiologists marked nothing here; you called it nodule.');
    expect(whyLine('false_positive', null)).toBe('Radiologists marked nothing here.');
    expect(whyLine('duplicate', { matched: 'F1' })).toBe('A second mark on F1.');
    for (const r of ['found', 'pattern_found', 'pattern_missed', 'pattern_false', 'true_negative', 'true_positive'] as const) {
      expect(whyLine(r)).not.toMatch(/\bms\b|dwell/);
    }
  });
});

describe('score and search copy', () => {
  it('explains the score in one sentence, without a hint cost', () => {
    expect(scoreSentence(false)).toContain('70 for marking each finding in the right place, 20 for naming it, 10 for whole-film findings');
    expect(scoreSentence(false)).not.toMatch(/hint/i);
    expect(scoreSentence(true)).toContain('normal film starts at 100');
  });
  it('summarises the search from computed facts', () => {
    expect(searchLines({ lung_coverage_pct: 53.6, unvisited_review_areas: ['left_apex', 'right_hilum'] })).toEqual({
      coverage: 'Your cursor covered about 54% of the lungs.',
      areas: 'Review areas you did not visit: left apex, right hilum.',
    });
    expect(searchLines({ lung_coverage_pct: 80, unvisited_review_areas: [] }).areas).toBe('You visited every review area.');
  });
});

describe('volumes: miss lines come from the outcome, not the search flag', () => {
  it('words the three miss types from result + dwell_ms', () => {
    expect(whyLine('missed_search', { dwell_ms: 0 }, true)).toBe('Its slices were never on screen long enough to see.');
    expect(whyLine('missed_recognition', { dwell_ms: 1200 }, true)).toBe('On screen for about 1.2 s; your cursor passed over it without stopping.');
    expect(whyLine('missed_decision', { dwell_ms: 2100 }, true)).toBe('You paused on it for about 2.1 s and left it unmarked.');
    expect(whyLine('found', null, true)).toBe('You marked it and named it.');
    expect(whyLine('missed_recognition', { dwell_ms: 1200 })).toBe('Your cursor passed through: about 1.2 s there.'); // X-ray unchanged
  });
  it('the volume search lines never read finding_slices_viewed', () => {
    const l = searchLines({ lung_coverage_pct: 31, unvisited_review_areas: [], slices_viewed_pct: 31, finding_slices_viewed: { F1: false } }, true);
    expect(l.areas).toBe('You scrolled through about 31% of the slices; the bar under the scan shows which.');
    expect(l.coverage).toBe('Your cursor covered about 31% of the scan.');
  });
});
