import { describe, expect, it } from 'vitest';
import {
  canSubmit, confidenceTarget, initialRead, NOTHING_YET, readReducer, submitBlockers, toHintMarks, toSubmitMarks, toSubmitPatterns,
  type ReadAction, type ReadState,
} from './readState';

const run = (actions: ReadAction[], s: ReadState = initialRead) => actions.reduce(readReducer, s);

describe('readReducer: marks', () => {
  it('numbers marks M1, M2… in creation order and never reuses ids', () => {
    const s = run([{ type: 'place', x: 1, y: 2 }, { type: 'place', x: 3, y: 4 }, { type: 'delete', id: 'M1' }, { type: 'place', x: 5, y: 6 }]);
    expect(s.marks.map((m) => m.mark_id)).toEqual(['M2', 'M3']);
  });
  it('an unarmed click opens the full popover on the new mark; nothing is preselected', () => {
    const s = run([{ type: 'place', x: 1, y: 2 }]);
    expect(s.selectedId).toBe('M1');
    expect(s.popoverId).toBe('M1');
    expect(s.popoverMode).toBe('full');
    expect(s.marks[0]).toEqual({ mark_id: 'M1', x: 1, y: 2, label: null, confidence: null });
  });
  it('sets label, confidence and position', () => {
    const s = run([
      { type: 'place', x: 1, y: 2 }, { type: 'label', id: 'M1', label: 'nodule' }, { type: 'confidence', id: 'M1', confidence: 5 },
      { type: 'move', id: 'M1', x: 9, y: 8 },
    ]);
    expect(s.marks[0]).toEqual({ mark_id: 'M1', x: 9, y: 8, label: 'nodule', confidence: 5 });
    expect(s.popoverId).toBe('M1'); // the full popover stays until Done
  });
  it('delete clears selection and popover', () => {
    const s = run([{ type: 'place', x: 1, y: 2 }, { type: 'delete', id: 'M1' }]);
    expect(s.selectedId).toBeNull();
    expect(s.popoverId).toBeNull();
  });
});

describe('readReducer: pathology-first arming', () => {
  it('arms a finding type; the next click places a mark with that label and asks only how sure', () => {
    let s = run([{ type: 'arm', label: 'effusion' }]);
    expect(s.armed).toBe('effusion');
    s = readReducer(s, { type: 'place', x: 10, y: 20 });
    expect(s.marks[0]).toEqual({ mark_id: 'M1', x: 10, y: 20, label: 'effusion', confidence: null });
    expect(s.popoverId).toBe('M1');
    expect(s.popoverMode).toBe('confidence');
    expect(s.armed).toBeNull(); // one pick, one mark
  });
  it('choosing the confidence closes the short popover', () => {
    const s = run([{ type: 'arm', label: 'nodule' }, { type: 'place', x: 1, y: 1 }, { type: 'confidence', id: 'M1', confidence: 4 }]);
    expect(s.marks[0].confidence).toBe(4);
    expect(s.popoverId).toBeNull();
    expect(s.selectedId).toBe('M1');
  });
  it('picking the armed finding again, or disarm, puts it down', () => {
    expect(run([{ type: 'arm', label: 'mass' }, { type: 'arm', label: 'mass' }]).armed).toBeNull();
    expect(run([{ type: 'arm', label: 'mass' }, { type: 'arm', label: 'nodule' }]).armed).toBe('nodule');
    expect(run([{ type: 'arm', label: 'mass' }, { type: 'disarm' }]).armed).toBeNull();
  });
  it('"not sure what it is" can be armed like any label', () => {
    const s = run([{ type: 'arm', label: 'not_sure' }, { type: 'place', x: 1, y: 1 }]);
    expect(s.marks[0].label).toBe('not_sure');
  });
  it('arming is ignored after a normal call, and a normal call disarms', () => {
    expect(run([{ type: 'callNormal' }, { type: 'arm', label: 'mass' }]).armed).toBeNull();
    expect(run([{ type: 'arm', label: 'mass' }, { type: 'callNormal' }]).armed).toBeNull();
  });
  it('reopening a mark from the rail shows the full popover', () => {
    const s = run([{ type: 'arm', label: 'nodule' }, { type: 'place', x: 1, y: 1 }, { type: 'confidence', id: 'M1', confidence: 2 }, { type: 'select', id: 'M1', popover: true }]);
    expect(s.popoverMode).toBe('full');
    expect(s.popoverId).toBe('M1');
  });
});

describe('readReducer: whole-film findings and the normal call', () => {
  it('ticks a whole-film finding with no confidence preselected', () => {
    let s = run([{ type: 'togglePattern', label: 'fibrosis' }]);
    expect(s.patterns).toEqual({ fibrosis: null });
    expect(toSubmitPatterns(s)).toEqual([]);
    s = readReducer(s, { type: 'patternConfidence', label: 'fibrosis', confidence: 2 });
    expect(toSubmitPatterns(s)).toEqual([{ label: 'fibrosis', confidence: 2 }]);
    s = readReducer(s, { type: 'togglePattern', label: 'fibrosis' });
    expect(s.patterns).toEqual({});
  });
  it('call it normal clears marks and whole-film findings and blocks new ones', () => {
    const s = run([
      { type: 'place', x: 1, y: 2 }, { type: 'togglePattern', label: 'cardiomegaly' }, { type: 'callNormal' }, { type: 'place', x: 1, y: 1 },
      { type: 'togglePattern', label: 'emphysema' },
    ]);
    expect(s.marks).toEqual([]);
    expect(s.patterns).toEqual({});
    expect(s.declaredNormal).toBe(true);
    expect(s.normalConfidence).toBeNull();
  });
  it('undoing the normal call forgets its confidence', () => {
    const s = run([{ type: 'callNormal' }, { type: 'normalConfidence', confidence: 5 }, { type: 'undoNormal' }, { type: 'callNormal' }]);
    expect(s.normalConfidence).toBeNull();
  });
  it('normal confidence is ignored unless normal is called', () => {
    expect(run([{ type: 'normalConfidence', confidence: 4 }]).normalConfidence).toBeNull();
  });
});

describe('submitBlockers: what exactly is missing', () => {
  it('nothing yet', () => {
    expect(submitBlockers(initialRead)).toEqual([NOTHING_YET]);
    expect(canSubmit(initialRead)).toBe(false);
  });
  it('a mark needs a label AND a confidence', () => {
    let s = run([{ type: 'place', x: 1, y: 1 }]);
    expect(submitBlockers(s)).toEqual(['M1 needs a label and a confidence']);
    s = readReducer(s, { type: 'label', id: 'M1', label: 'nodule' });
    expect(submitBlockers(s)).toEqual(['M1 needs a confidence']);
    s = readReducer(s, { type: 'confidence', id: 'M1', confidence: 3 });
    expect(submitBlockers(s)).toEqual([]);
    expect(canSubmit(s)).toBe(true);
  });
  it('names each unfinished mark', () => {
    const s = run([
      { type: 'arm', label: 'mass' }, { type: 'place', x: 1, y: 1 }, { type: 'confidence', id: 'M1', confidence: 4 },
      { type: 'arm', label: 'nodule' }, { type: 'place', x: 2, y: 2 }, { type: 'closePopover' },
      { type: 'place', x: 3, y: 3 }, { type: 'confidence', id: 'M3', confidence: 1 },
    ]);
    expect(submitBlockers(s)).toEqual(['M2 needs a confidence', 'M3 needs a label']);
    expect(canSubmit(s)).toBe(false);
  });
  it('a ticked whole-film finding needs a confidence', () => {
    let s = run([{ type: 'togglePattern', label: 'cardiomegaly' }]);
    expect(submitBlockers(s)).toEqual(['Cardiomegaly needs a confidence']);
    s = readReducer(s, { type: 'patternConfidence', label: 'cardiomegaly', confidence: 5 });
    expect(canSubmit(s)).toBe(true);
  });
  it('the normal call needs a confidence', () => {
    let s = run([{ type: 'callNormal' }]);
    expect(submitBlockers(s)).toEqual(['The normal call needs a confidence']);
    s = readReducer(s, { type: 'normalConfidence', confidence: 4 });
    expect(canSubmit(s)).toBe(true);
  });
});

describe('digit keys and payloads', () => {
  it('digits target the selected mark, or the normal call when it is active', () => {
    expect(confidenceTarget(initialRead)).toBeNull();
    expect(confidenceTarget(run([{ type: 'place', x: 1, y: 1 }]))).toEqual({ kind: 'mark', id: 'M1' });
    expect(confidenceTarget(run([{ type: 'place', x: 1, y: 1 }, { type: 'select', id: null }]))).toBeNull();
    expect(confidenceTarget(run([{ type: 'callNormal' }]))).toEqual({ kind: 'normal' });
  });
  it('submits only complete marks; hint requests carry unfinished ones as not_sure', () => {
    const s = run([{ type: 'place', x: 1, y: 1 }]);
    expect(toSubmitMarks(s)).toEqual([]);
    expect(toHintMarks(s)[0]).toMatchObject({ mark_id: 'M1', label: 'not_sure' });
    const done = run([{ type: 'label', id: 'M1', label: 'mass' }, { type: 'confidence', id: 'M1', confidence: 2 }], s);
    expect(toSubmitMarks(done)).toEqual([{ mark_id: 'M1', x: 1, y: 1, label: 'mass', confidence: 2 }]);
  });
});
