import { afterEach, describe, expect, it, vi } from 'vitest';
import { enoughReads, MIN_READS, readsToGo } from '../dashboard/helpers';
import {
  forgetLearner, guardAttemptResult, learnerLabel, loadRemembered, looksLikeCode, markTestDone, needsTutorial, nextTest, parseRemembered, readPath,
  remember, sameLearner, sampleSessionCreate, toSessionCreate, weakSpotsNote, weakSpotsReady, type Remembered, type StartForm,
} from './sessionOptions';

const form = (over: Partial<StartForm> = {}): StartForm => ({ name: '', practice: 'mixed', finding: 'nodule', count: 10, ...over });
const fresh = { remembered: null, reads: null };
const maya: Remembered = { learnerId: 'lrn_1', name: 'Maya', tests: [] };

describe('start form → SessionCreate', () => {
  it('a mixed set is adaptive practice with the chosen length, and level is always "other"', () => {
    expect(toSessionCreate(form({ name: ' Maya ', count: 5 }), fresh)).toEqual({
      display_name: 'Maya', participant_code: null, level: 'other', mode: 'practice', settings: { case_count: 5, selection: 'adaptive' },
    });
  });

  it('a blank name stays anonymous', () => {
    const b = toSessionCreate(form(), fresh);
    expect(b.display_name).toBe('Anonymous');
    expect(b.participant_code).toBeNull();
    expect(b.settings).toEqual({ case_count: 10, selection: 'adaptive' });
  });

  it('a personal code is sent as the participant code', () => {
    expect(toSessionCreate(form({ name: 'MK-2041' }), fresh)).toMatchObject({ display_name: 'MK-2041', participant_code: 'MK-2041' });
    expect(looksLikeCode('Maya')).toBe(false);
  });

  it('one finding type is a drill on that label', () => {
    expect(toSessionCreate(form({ practice: 'finding', finding: 'pneumothorax', count: 20 }), fresh)).toMatchObject({
      mode: 'drill', settings: { case_count: 20, selection: 'adaptive', label: 'pneumothorax' },
    });
  });

  it('weak spots needs 5 reads; before that it falls back to a mixed set', () => {
    expect(toSessionCreate(form({ practice: 'weak' }), { remembered: maya, reads: 4 }).settings).toMatchObject({ selection: 'adaptive' });
    const b = toSessionCreate(form({ name: 'Maya', practice: 'weak' }), { remembered: maya, reads: 5 });
    expect(b.mode).toBe('practice');
    expect(b.settings).toEqual({ learner_id: 'lrn_1', case_count: 10, selection: 'weak_areas' });
  });

  it('the test set has no length or selection: A first, B once A is done, then A again', () => {
    const a = toSessionCreate(form({ practice: 'test', count: 5 }), fresh);
    expect(a.mode).toBe('assess_A');
    expect(a.settings).toEqual({});
    expect(toSessionCreate(form({ name: 'Maya', practice: 'test' }), { remembered: { ...maya, tests: ['A'] }, reads: 0 }).mode).toBe('assess_B');
    expect(toSessionCreate(form({ name: 'Maya', practice: 'test' }), { remembered: { ...maya, tests: ['A', 'B'] }, reads: 0 }).mode).toBe('assess_A');
    expect(nextTest(['A', 'B'])).toEqual({ mode: 'assess_A', set: 'A', repeat: true });
    // Someone else's finished test does not move a new name on to B.
    expect(toSessionCreate(form({ name: 'Sam', practice: 'test' }), { remembered: { ...maya, tests: ['A'] }, reads: 0 }).mode).toBe('assess_A');
  });

  it('the remembered learner is resumed only while the name still matches', () => {
    expect(toSessionCreate(form({ name: 'maya' }), { remembered: maya, reads: 9 }).settings).toMatchObject({ learner_id: 'lrn_1' });
    expect(toSessionCreate(form({ name: 'Sam' }), { remembered: maya, reads: 9 }).settings).not.toHaveProperty('learner_id');
    const anon: Remembered = { learnerId: 'lrn_2', name: '', tests: [] };
    expect(sameLearner(anon, '  ')).toBe(true);
    expect(toSessionCreate(form(), { remembered: anon, reads: 0 }).settings).toMatchObject({ learner_id: 'lrn_2' });
  });

  it('projector mode rides along in settings', () => {
    expect(toSessionCreate(form(), { ...fresh, projector: true }).settings).toMatchObject({ projector: true });
  });

  it('the sample set uses the reserved name and nothing else; a learner typing that name does not', () => {
    expect(sampleSessionCreate()).toEqual({ display_name: 'Demo', level: 'other', participant_code: null, mode: 'practice', settings: {} });
    expect(toSessionCreate(form({ name: 'demo' }), fresh).display_name).toBe('demo (reader)');
    expect(learnerLabel('Demo')).toBe('Sample set');
    expect(learnerLabel('Anonymous')).toBe('Anonymous reader');
    expect(learnerLabel('Maya')).toBe('Maya');
  });
});

describe('fewer than 5 reads', () => {
  it('gates the headline numbers and the weak-spots option at the same threshold', () => {
    expect(MIN_READS).toBe(5);
    for (const n of [null, undefined, Number.NaN, 0, 4]) {
      expect(enoughReads(n)).toBe(false);
      expect(weakSpotsReady(n)).toBe(false);
    }
    for (const n of [5, 6, 200]) {
      expect(enoughReads(n)).toBe(true);
      expect(weakSpotsReady(n)).toBe(true);
    }
  });

  it('says how many films are left', () => {
    expect(readsToGo(0)).toBe(5);
    expect(readsToGo(3)).toBe(2);
    expect(readsToGo(5)).toBe(0);
    expect(readsToGo(null)).toBe(5);
    expect(weakSpotsNote(2)).toBe('Opens after 5 films, so there is something to go on. You have read 2; 3 to go.');
    expect(weakSpotsNote(8)).toBe('Films like the ones you have missed most.');
  });
});

describe('guards', () => {
  it('reads a remembered learner and rejects junk', () => {
    expect(parseRemembered('{"learnerId":"x","name":"Maya","tests":["A","C"]}')).toEqual({ learnerId: 'x', name: 'Maya', tests: ['A'] });
    expect(parseRemembered('{"name":"Maya"}')).toBeNull();
    expect(parseRemembered('not json')).toBeNull();
    expect(parseRemembered(null)).toBeNull();
  });

  it('takes a stored result with or without the film and the submitted marks', () => {
    const base = { score: 70, success: true, outcomes: [], reveal: { findings: [] }, facts_card: { headline: 'h', lines: ['a', 3] } };
    const bare = guardAttemptResult(base);
    expect(bare.film).toBeNull();
    expect(bare.marks).toBeNull();
    expect(bare.result.reveal.marks).toEqual([]);
    expect(bare.result.facts_card.lines).toEqual(['a']);
    const full = guardAttemptResult({
      ...base, case: { case_id: 'cxd_1', image_url: '/api/cases/cxd_1/image', width: 1024, height: 1024 },
      submitted: { marks: [{ mark_id: 'M1', x: 10, y: 20, label: 'nodule', confidence: 4 }, { x: 'bad' }], declared_normal: false },
    });
    expect(full.film).toEqual({ case_id: 'cxd_1', image_url: '/api/cases/cxd_1/image', width: 1024, height: 1024 });
    expect(full.marks).toEqual([{ mark_id: 'M1', x: 10, y: 20, label: 'nodule', confidence: 4 }]);
    expect(full.declaredNormal).toBe(false);
    expect(() => guardAttemptResult({ recorded: true })).toThrow();
  });
});

describe('this device remembers the learner', () => {
  const store = new Map<string, string>();
  const fake = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v), removeItem: (k: string) => void store.delete(k) };
  afterEach(() => { store.clear(); vi.unstubAllGlobals(); });

  it('keeps the reader and the tests they finished; a different reader starts clean', () => {
    vi.stubGlobal('localStorage', fake);
    expect(loadRemembered()).toBeNull();
    remember('lrn_1', ' Maya ');
    expect(loadRemembered()).toEqual({ learnerId: 'lrn_1', name: 'Maya', tests: [] });
    markTestDone('lrn_1', 'assess_A');
    markTestDone('lrn_1', 'assess_A');
    markTestDone('someone_else', 'assess_B');
    markTestDone('lrn_1', 'practice');
    expect(loadRemembered()?.tests).toEqual(['A']);
    expect(remember('lrn_1', 'Maya').tests).toEqual(['A']);
    expect(remember('lrn_2', 'Sam').tests).toEqual([]);
    forgetLearner();
    expect(loadRemembered()).toBeNull();
  });

  it('asks for the tutorial on the first session only, and never when storage is blocked', () => {
    expect(needsTutorial()).toBe(false); // no localStorage at all: do not nag
    vi.stubGlobal('localStorage', fake);
    expect(readPath()).toBe('/read?tutorial=1');
    store.set('bs_tutorial_done', '1');
    expect(readPath()).toBe('/read');
  });
});
