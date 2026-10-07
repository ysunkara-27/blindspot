import { describe, expect, it } from 'vitest';
import { DEFAULT_URL } from '../analytics';
import {
  EMPTY_FORM, FAILED_MESSAGE, failureMessage, feedbackEndpoint, LIMIT_MESSAGE, MAX_CONTACT, MAX_MISSING, missingAnswer, OFFLINE_MESSAGE,
  RATINGS_MESSAGE, toPayload, VERDICT_MESSAGE, type FeedbackForm,
} from './feedbackModel';

const full: FeedbackForm = {
  role: 'resident', years: '5-15', ratings: { ease: 4, teaching: 5, accuracy: 3, recommend: 4 }, verdict: 'yes',
  missing: '  More CT cases.  ', contact: ' a@example.org ',
};

describe('missingAnswer', () => {
  it('needs the four ratings, then the verdict; role, years and the texts are optional', () => {
    expect(missingAnswer(EMPTY_FORM)).toEqual({ message: RATINGS_MESSAGE, field: 'ease' });
    expect(missingAnswer({ ...EMPTY_FORM, ratings: { ease: 3, teaching: 3, accuracy: 3 } })).toEqual({ message: RATINGS_MESSAGE, field: 'recommend' });
    expect(missingAnswer({ ...EMPTY_FORM, ratings: { ease: 3, teaching: 3, accuracy: 3, recommend: 3 } })).toEqual({ message: VERDICT_MESSAGE, field: 'verdict' });
    expect(missingAnswer({ ...EMPTY_FORM, ratings: { ease: 3, teaching: 3, accuracy: 3, recommend: 3 }, verdict: 'maybe' })).toBeNull();
  });
});

describe('toPayload', () => {
  it('maps the form onto the worker contract and trims the free text', () => {
    expect(toPayload(full)).toEqual({
      role: 'resident', years: '5-15', ease: 4, teaching: 5, accuracy: 3, recommend: 4, real_product: 'yes',
      missing: 'More CT cases.', contact: 'a@example.org',
    });
  });

  it('sends "other" for no role and "" for no years', () => {
    const p = toPayload({ ...full, role: null, years: null, missing: '', contact: '' });
    expect(p).toMatchObject({ role: 'other', years: '', missing: '', contact: '' });
  });

  it('is null while a required answer is missing', () => {
    expect(toPayload({ ...full, verdict: null })).toBeNull();
    expect(toPayload({ ...full, ratings: { ...full.ratings, accuracy: undefined } })).toBeNull();
  });

  it('never exceeds the worker limits (600 / 200 characters, well under 4 KB in all)', () => {
    const p = toPayload({ ...full, missing: 'x'.repeat(2000), contact: 'y'.repeat(500) })!;
    expect(p.missing).toHaveLength(MAX_MISSING);
    expect(p.contact).toHaveLength(MAX_CONTACT);
    expect(new TextEncoder().encode(JSON.stringify(p)).length).toBeLessThan(4096);
  });

  it('only ever sends values the worker accepts', () => {
    const p = toPayload(full)!;
    expect(['radiologist', 'resident', 'medical_student', 'other_clinician', 'other']).toContain(p.role);
    expect(['<5', '5-15', '>15', '']).toContain(p.years);
    expect(['yes', 'maybe', 'no']).toContain(p.real_product);
    for (const k of ['ease', 'teaching', 'accuracy', 'recommend'] as const) {
      expect(Number.isInteger(p[k])).toBe(true);
      expect(p[k]).toBeGreaterThanOrEqual(1);
      expect(p[k]).toBeLessThanOrEqual(5);
    }
  });
});

describe('feedbackEndpoint', () => {
  it('uses the tracker base, without a trailing slash, and the default worker when the variable is empty or unset', () => {
    expect(feedbackEndpoint('https://api.example.org/')).toBe('https://api.example.org/feedback/submit');
    expect(feedbackEndpoint('https://api.example.org')).toBe('https://api.example.org/feedback/submit');
    expect(feedbackEndpoint('')).toBe(`${DEFAULT_URL}/feedback/submit`);
    expect(feedbackEndpoint('   ')).toBe(`${DEFAULT_URL}/feedback/submit`);
    expect(feedbackEndpoint(undefined)).toBe(`${DEFAULT_URL}/feedback/submit`);
  });
});

describe('failureMessage', () => {
  it('names the hourly limit on 429, repeats the worker on other errors, and says "no connection" when nothing answered', () => {
    expect(failureMessage(429, { error: 'Thanks — that is plenty for one hour.' })).toBe(LIMIT_MESSAGE);
    expect(failureMessage(400, { error: 'Choose a role.' })).toBe('Choose a role.');
    expect(failureMessage(503, {})).toBe(FAILED_MESSAGE);
    expect(failureMessage(500, 'not json')).toBe(FAILED_MESSAGE);
    expect(failureMessage(null, null)).toBe(OFFLINE_MESSAGE);
  });
});
