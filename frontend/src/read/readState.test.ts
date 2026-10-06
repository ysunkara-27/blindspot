import { describe, expect, it } from 'vitest';
import { canSubmit, initialRead, readReducer, toSubmitMarks, toSubmitPatterns, type ReadAction, type ReadState } from './readState';

const run = (actions: ReadAction[], s: ReadState = initialRead) => actions.reduce(readReducer, s);

describe('readReducer', () => {
  it('numbers marks M1, M2… in creation order and never reuses ids', () => {
    const s = run([{ type: 'place', x: 1, y: 2 }, { type: 'place', x: 3, y: 4 }, { type: 'delete', id: 'M1' }, { type: 'place', x: 5, y: 6 }]);
    expect(s.marks.map((m) => m.mark_id)).toEqual(['M2', 'M3']);
  });
  it('opens the popover on the new mark and selects it', () => {
    const s = run([{ type: 'place', x: 1, y: 2 }]);
    expect(s.selectedId).toBe('M1');
    expect(s.popoverId).toBe('M1');
  });
  it('sets label, confidence and position', () => {
    const s = run([
      { type: 'place', x: 1, y: 2 }, { type: 'label', id: 'M1', label: 'nodule' }, { type: 'confidence', id: 'M1', confidence: 5 },
      { type: 'move', id: 'M1', x: 9, y: 8 },
    ]);
    expect(s.marks[0]).toEqual({ mark_id: 'M1', x: 9, y: 8, label: 'nodule', confidence: 5 });
  });
  it('delete clears selection and popover', () => {
    const s = run([{ type: 'place', x: 1, y: 2 }, { type: 'delete', id: 'M1' }]);
    expect(s.selectedId).toBeNull();
    expect(s.popoverId).toBeNull();
  });
  it('call it normal clears marks and patterns and blocks new marks', () => {
    const s = run([
      { type: 'place', x: 1, y: 2 }, { type: 'togglePattern', label: 'cardiomegaly' }, { type: 'callNormal' }, { type: 'place', x: 1, y: 1 },
      { type: 'togglePattern', label: 'emphysema' },
    ]);
    expect(s.marks).toEqual([]);
    expect(s.patterns).toEqual({});
    expect(s.declaredNormal).toBe(true);
    expect(canSubmit(s)).toBe(true);
  });
  it('toggles patterns with a default confidence', () => {
    let s = run([{ type: 'togglePattern', label: 'fibrosis' }, { type: 'patternConfidence', label: 'fibrosis', confidence: 2 }]);
    expect(toSubmitPatterns(s)).toEqual([{ label: 'fibrosis', confidence: 2 }]);
    s = readReducer(s, { type: 'togglePattern', label: 'fibrosis' });
    expect(toSubmitPatterns(s)).toEqual([]);
  });
  it('submit is disabled until a mark, a global finding, or a normal call', () => {
    expect(canSubmit(initialRead)).toBe(false);
    expect(canSubmit(run([{ type: 'place', x: 1, y: 1 }]))).toBe(true);
    expect(canSubmit(run([{ type: 'togglePattern', label: 'emphysema' }]))).toBe(true);
  });
  it('sends unlabeled marks as not_sure', () => {
    expect(toSubmitMarks(run([{ type: 'place', x: 1, y: 1 }]))[0].label).toBe('not_sure');
  });
});
