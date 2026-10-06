// The learner's read for one case: marks, global findings, normal call. Pure reducer (SPEC §5.2).
import type { Confidence, Mark, PatternSelection } from '../types/contracts';
import type { PatternLabel } from '../api/labels';

export type DraftMark = { mark_id: string; x: number; y: number; label: Mark['label'] | null; confidence: Confidence };

export type ReadState = {
  marks: DraftMark[];
  nextId: number; // M<n> ids in creation order, never reused within a case
  selectedId: string | null;
  popoverId: string | null;
  patterns: Partial<Record<PatternLabel, Confidence>>;
  declaredNormal: boolean;
  normalConfidence: Confidence;
};

export const DEFAULT_CONFIDENCE: Confidence = 3;

export const initialRead: ReadState = {
  marks: [], nextId: 1, selectedId: null, popoverId: null, patterns: {}, declaredNormal: false, normalConfidence: DEFAULT_CONFIDENCE,
};

export type ReadAction =
  | { type: 'place'; x: number; y: number }
  | { type: 'move'; id: string; x: number; y: number }
  | { type: 'label'; id: string; label: Mark['label'] }
  | { type: 'confidence'; id: string; confidence: Confidence }
  | { type: 'delete'; id: string }
  | { type: 'select'; id: string | null; popover?: boolean }
  | { type: 'closePopover' }
  | { type: 'togglePattern'; label: PatternLabel }
  | { type: 'patternConfidence'; label: PatternLabel; confidence: Confidence }
  | { type: 'callNormal' }
  | { type: 'undoNormal' }
  | { type: 'normalConfidence'; confidence: Confidence }
  | { type: 'reset' };

export function readReducer(s: ReadState, a: ReadAction): ReadState {
  switch (a.type) {
    case 'place': {
      if (s.declaredNormal) return s;
      const id = `M${s.nextId}`;
      return {
        ...s,
        marks: [...s.marks, { mark_id: id, x: a.x, y: a.y, label: null, confidence: DEFAULT_CONFIDENCE }],
        nextId: s.nextId + 1, selectedId: id, popoverId: id,
      };
    }
    case 'move':
      return { ...s, marks: s.marks.map((m) => (m.mark_id === a.id ? { ...m, x: a.x, y: a.y } : m)) };
    case 'label':
      return { ...s, marks: s.marks.map((m) => (m.mark_id === a.id ? { ...m, label: a.label } : m)) };
    case 'confidence':
      return { ...s, marks: s.marks.map((m) => (m.mark_id === a.id ? { ...m, confidence: a.confidence } : m)) };
    case 'delete':
      return {
        ...s,
        marks: s.marks.filter((m) => m.mark_id !== a.id),
        selectedId: s.selectedId === a.id ? null : s.selectedId,
        popoverId: s.popoverId === a.id ? null : s.popoverId,
      };
    case 'select':
      return { ...s, selectedId: a.id, popoverId: a.popover ? a.id : null };
    case 'closePopover':
      return { ...s, popoverId: null };
    case 'togglePattern': {
      if (s.declaredNormal) return s;
      const patterns = { ...s.patterns };
      if (patterns[a.label] !== undefined) delete patterns[a.label];
      else patterns[a.label] = DEFAULT_CONFIDENCE;
      return { ...s, patterns };
    }
    case 'patternConfidence':
      return s.patterns[a.label] === undefined ? s : { ...s, patterns: { ...s.patterns, [a.label]: a.confidence } };
    case 'callNormal':
      // Calling normal clears marks and global findings (the UI confirms first if any exist).
      return { ...s, marks: [], patterns: {}, selectedId: null, popoverId: null, declaredNormal: true };
    case 'undoNormal':
      return { ...s, declaredNormal: false };
    case 'normalConfidence':
      return { ...s, normalConfidence: a.confidence };
    case 'reset':
      return initialRead;
  }
}

export function canSubmit(s: ReadState): boolean {
  return s.marks.length > 0 || Object.keys(s.patterns).length > 0 || s.declaredNormal;
}

/** Contract-shaped marks/patterns for submit and hint. Unlabeled marks go as "not_sure". */
export function toSubmitMarks(s: ReadState): Mark[] {
  return s.marks.map((m) => ({ mark_id: m.mark_id, x: m.x, y: m.y, label: m.label ?? 'not_sure', confidence: m.confidence }));
}
export function toSubmitPatterns(s: ReadState): PatternSelection[] {
  return (Object.entries(s.patterns) as [PatternLabel, Confidence][]).map(([label, confidence]) => ({ label, confidence }));
}
