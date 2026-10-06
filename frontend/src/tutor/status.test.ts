import { describe, expect, it } from 'vitest';
import { bannerText, debriefErrorText, resumeText, spendText, tutorStatus } from './status';

const now = new Date('2026-10-06T15:00:00');

describe('tutorStatus', () => {
  it('uses tutor when present, else falls back to offline', () => {
    expect(tutorStatus({ ok: true, offline: false, cases: 1, tutor: { mode: 'paused_rate' } })?.mode).toBe('paused_rate');
    expect(tutorStatus({ ok: true, offline: true, cases: 1 })?.mode).toBe('offline');
    expect(tutorStatus({ ok: true, offline: false, cases: 1 })?.mode).toBe('live');
    expect(tutorStatus(null)).toBeNull();
  });
});

describe('bannerText', () => {
  it('is quiet when live', () => {
    expect(bannerText({ mode: 'live' })).toBeNull();
  });
  it.each([
    ['offline', 'The AI tutor is off. You still get the built-in explanation after every film.'],
    ['paused_credits', 'The AI tutor is paused (account credits ran out). Built-in explanations continue.'],
    ['paused_rate', 'The AI tutor is busy; trying again shortly.'],
    ['paused_error', 'The AI tutor is unavailable right now. Built-in explanations continue.'],
    ['paused_budget', 'The AI tutor has reached its spending limit for now. Built-in explanations continue.'],
  ] as const)('%s', (mode, text) => {
    expect(bannerText({ mode })).toBe(text);
  });
  it('adds the local resume time for a budget pause', () => {
    const t = new Date('2026-10-06T16:30:00').toISOString();
    const text = bannerText({ mode: 'paused_budget', resume_at: t }, now)!;
    expect(text.startsWith('The AI tutor has reached its spending limit for now. Built-in explanations continue. Back around ')).toBe(true);
    expect(text).toContain(resumeText(t, now)!);
    expect(text).toMatch(/\d:30/);
  });
  it('never shows a raw code', () => {
    expect(bannerText({ mode: 'something_new' as never })).toBe('The AI tutor is unavailable right now. Built-in explanations continue.');
  });
});

describe('resumeText', () => {
  it('names the weekday when the time is on another day, and copes with junk', () => {
    expect(resumeText(new Date('2026-10-08T09:05:00').toISOString(), now)).toMatch(/^\w{3} .*9:05/);
    expect(resumeText('not a date', now)).toBeNull();
    expect(resumeText(null, now)).toBeNull();
  });
});

describe('spendText', () => {
  it('reads spend_usd.day', () => {
    expect(spendText({ mode: 'live', spend_usd: { day: 1.2345, hour: 0.1 } })).toBe('Spend today $1.23');
    expect(spendText({ mode: 'live', spend_usd: { hour: 0.1 } })).toBeNull();
    expect(spendText({ mode: 'live' })).toBeNull();
    expect(spendText(null)).toBeNull();
  });
});

describe('debriefErrorText', () => {
  const d = { status: 'ready' as const, debrief: { headline: 'x' } as never };
  it.each([
    ['offline', 'The AI tutor is off. Showing the built-in explanation instead.'],
    ['credits_depleted', 'The AI tutor is paused (account credits ran out). Showing the built-in explanation instead.'],
    ['rate_limited', 'The AI tutor is busy. Showing the built-in explanation instead.'],
    ['budget_exceeded', 'The AI tutor has reached its spending limit for now. Showing the built-in explanation instead.'],
    ['unavailable', 'The AI tutor is unavailable right now. Showing the built-in explanation instead.'],
    ['auth', 'The AI tutor could not sign in to its service. Showing the built-in explanation instead.'],
    ['validator_failed', "The AI tutor's draft did not pass our checks. Showing the built-in explanation instead."],
    ['timeout', 'The AI tutor took too long. Showing the built-in explanation instead.'],
    ['internal_error', 'Something went wrong while writing the AI debrief. Showing the built-in explanation instead.'],
  ])('%s', (code, text) => {
    expect(debriefErrorText({ ...d, error: code }, false)).toBe(text);
  });
  it('is silent for a clean debrief and never leaks an unknown code', () => {
    expect(debriefErrorText({ ...d, error: null }, false)).toBeNull();
    expect(debriefErrorText({ ...d, error: 'LiveCallError' }, false)).toBe('The AI tutor is unavailable right now. Showing the built-in explanation instead.');
    expect(debriefErrorText({ status: 'failed', error: 'LiveCallError' }, true)).toBe('The AI tutor is unavailable right now. The facts above are complete.');
    expect(debriefErrorText({ status: 'failed', error: 'LiveCallError' }, true)).not.toContain('LiveCallError');
    expect(debriefErrorText(undefined, true)).toBe('The AI tutor is unavailable right now. The facts above are complete.');
  });
  it('says the facts are complete when a known code comes with no explanation', () => {
    expect(debriefErrorText({ status: 'failed', error: 'timeout' }, true)).toBe('The AI tutor took too long. The facts above are complete.');
  });
});
