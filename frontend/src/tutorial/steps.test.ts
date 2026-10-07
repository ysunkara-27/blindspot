import { describe, expect, it } from 'vitest';
import { availableSteps, hasTutorialFlag, placeCard, shouldOpenTutorial, STEPS, tourStep, type Rect } from './steps';

describe('tutorial steps', () => {
  it('has the seven X-ray steps in order, each pointing at a real control; the two volume steps sit between them', () => {
    expect(STEPS.filter((s) => !s.volumetric).map((s) => s.id)).toEqual(['film', 'magnifier', 'pick', 'confidence', 'whole', 'hints', 'submit']);
    expect(STEPS.map((s) => s.id)).toEqual(['film', 'slices', 'magnifier', 'pick', 'confidence', 'measure', 'whole', 'hints', 'submit']);
    for (const s of STEPS) expect(s.target).toMatch(/^\[data-tour="[a-z-]+"\]$/);
  });
  it('a chest film never sees the volume steps, even when their controls are on the page; a CT sees them only when they are', () => {
    expect(availableSteps(() => true).map((s) => s.id)).toEqual(['film', 'magnifier', 'pick', 'confidence', 'whole', 'hints', 'submit']);
    expect(availableSteps(() => true, STEPS, true).map((s) => s.id)).toEqual(['film', 'slices', 'magnifier', 'pick', 'confidence', 'measure', 'whole', 'hints', 'submit']);
    expect(availableSteps((sel) => sel !== '[data-tour="measure"]', STEPS, true).map((s) => s.id)).not.toContain('measure');
  });
  it('never mentions a points cost for hints', () => {
    for (const s of STEPS) expect(`${s.title} ${s.body}`).not.toMatch(/points?|cost/i);
  });
  it('keeps the reference tip when hints are off (test set), and drops steps whose control is missing', () => {
    const noHints = availableSteps((sel) => sel !== '[data-tour="hints"]');
    expect(noHints).toHaveLength(7);
    expect(noHints[5]).toMatchObject({ id: 'hints', target: '[data-tour="pick"]', title: 'Not sure what a finding looks like?' });
    expect(availableSteps((sel) => sel !== '[data-tour="magnifier"]').map((s) => s.id)).not.toContain('magnifier');
    expect(availableSteps(() => false)).toEqual([]);
  });
});

describe('shouldOpenTutorial', () => {
  const base = { webdriver: false, bootFlag: false, urlFlag: false, done: false, firstCase: false };
  it('opens on a first session in a real browser', () => {
    expect(shouldOpenTutorial({ ...base, urlFlag: true })).toBe(true);
    expect(shouldOpenTutorial({ ...base, firstCase: true })).toBe(true);
    expect(shouldOpenTutorial(base)).toBe(false);
  });
  it('stays closed once finished or skipped', () => {
    expect(shouldOpenTutorial({ ...base, urlFlag: true, firstCase: true, done: true })).toBe(false);
  });
  it('under automation opens only when the page was loaded with ?tutorial=1', () => {
    expect(shouldOpenTutorial({ ...base, webdriver: true, urlFlag: true, firstCase: true })).toBe(false);
    expect(shouldOpenTutorial({ ...base, webdriver: true, bootFlag: true })).toBe(true);
    expect(shouldOpenTutorial({ ...base, webdriver: true, bootFlag: true, done: true })).toBe(true);
  });
  it('reads the flag from a query string', () => {
    expect(hasTutorialFlag('?mock=1&tutorial=1')).toBe(true);
    expect(hasTutorialFlag('?tutorial=0')).toBe(false);
    expect(hasTutorialFlag('')).toBe(false);
  });
});

describe('tourStep', () => {
  it('walks forward and back and ends after the last step', () => {
    expect(tourStep({ i: 0, n: 7 }, 'next')).toEqual({ i: 1, n: 7 });
    expect(tourStep({ i: 0, n: 7 }, 'back')).toEqual({ i: 0, n: 7 });
    expect(tourStep({ i: 3, n: 7 }, 'back')).toEqual({ i: 2, n: 7 });
    expect(tourStep({ i: 6, n: 7 }, 'next')).toBeNull();
  });
});

describe('placeCard', () => {
  const vp = { w: 1280, h: 800 };
  const film: Rect = { left: 0, top: 90, width: 870, height: 664 };
  const card = { w: 320, h: 190 };
  const hit = (a: Rect, b: Rect) => a.left < b.left + b.width && b.left < a.left + a.width && a.top < b.top + b.height && b.top < a.top + a.height;
  const rectOf = (p: { left: number; top: number }): Rect => ({ left: p.left, top: p.top, width: card.w, height: card.h });

  it('puts the film step beside the film, not on it', () => {
    const p = placeCard(film, card, vp, film);
    expect(p.side).toBe('right');
    expect(hit(rectOf(p), film)).toBe(false);
  });
  it('keeps every rail and toolbar step off the film', () => {
    const targets: Rect[] = [
      { left: 730, top: 760, width: 130, height: 30 }, // magnifier button, right end of the bar under the film
      { left: 892, top: 150, width: 366, height: 200 }, // pick list
      { left: 892, top: 360, width: 366, height: 70 }, // marks
      { left: 892, top: 440, width: 366, height: 300 }, // whole film + normal
      { left: 892, top: 600, width: 366, height: 60 }, // hints
      { left: 892, top: 700, width: 366, height: 90 }, // submit bar
    ];
    for (const t of targets) {
      const p = placeCard(t, card, vp, film);
      expect(hit(rectOf(p), film), `card for target at ${t.left},${t.top} (${p.side})`).toBe(false);
      expect(hit(rectOf(p), t)).toBe(false);
      expect(p.left).toBeGreaterThanOrEqual(8);
      expect(p.left + card.w).toBeLessThanOrEqual(vp.w - 8);
      expect(p.top).toBeGreaterThanOrEqual(8);
      expect(p.top + card.h).toBeLessThanOrEqual(vp.h - 8);
    }
  });
  it('falls back to sitting inside a target that fills the viewport', () => {
    const p = placeCard({ left: 0, top: 0, width: 1280, height: 800 }, card, vp, null);
    expect(p.side).toBe('inside');
    expect(p.top + card.h).toBeLessThanOrEqual(vp.h - 8);
  });
});
