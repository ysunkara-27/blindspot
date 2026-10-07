// The learner's read for one case: marks, whole-film findings, normal call. Pure reducer (SPEC §5.2).
// Round 3: pathology-first marking (arm a finding type, then click where it is) and no preselected confidence:
// every mark, whole-film finding and normal call needs a confidence the learner chose before the read can be submitted.
// Volumes (CT / MR): a mark also carries the plane and slice it was placed on and its voxel [x, y, z]; x, y are then
// the in-plane voxel coords of that plane. Mass-like marks get a size step (measure with the caliper, or skip).
import type { Confidence, Mark, Measurement, PatternSelection } from '../types/contracts';
import { labelDisplay, type PatternLabel } from '../api/labels';

export type MarkLabel = Mark['label'];
export type Plane = NonNullable<Mark['plane']>;
export type Voxel = [number, number, number];
export type Mark3 = { plane: Plane; slice: number; voxel: Voxel };
export type DraftMark = { mark_id: string; x: number; y: number; label: MarkLabel | null; confidence: Confidence | null } & Partial<Mark3>;
/** A caliper measurement waiting to be recorded, or recorded, for one mark. */
export type DraftMeasurement = { long_mm: number; plane: Plane; slice: number; p0: Voxel; p1: Voxel };
export type SizeStep = { kind: 'recorded'; m: DraftMeasurement } | { kind: 'skipped' };

/** Labels that get the "How big is it?" step (config/scoring.yaml volumetric.size_labels, mirrored for the UI). */
export const SIZE_LABELS: MarkLabel[] = ['pancreatic_tumour', 'liver_tumour', 'brain_tumour', 'lung_tumour', 'colon_tumour', 'nodule', 'mass'];
export const needsSize = (label: MarkLabel | null | undefined): boolean => !!label && SIZE_LABELS.includes(label);
/** 'full' = choose a label and a confidence; 'confidence' = the label came from the armed finding, only ask how sure. */
export type PopoverMode = 'full' | 'confidence';

export type ReadState = {
  marks: DraftMark[];
  nextId: number; // M<n> ids in creation order, never reused within a case
  selectedId: string | null;
  popoverId: string | null;
  popoverMode: PopoverMode;
  /** The finding type picked in the rail; the next click on the film places a mark with this label. */
  armed: MarkLabel | null;
  /** Ticked whole-film findings; null = ticked, confidence not chosen yet. */
  patterns: Partial<Record<PatternLabel, Confidence | null>>;
  declaredNormal: boolean;
  normalConfidence: Confidence | null;
  /** Volumes only: the size step per mass-like mark (absent = still to do). */
  sizes: Record<string, SizeStep>;
  /** Volumes only: whether the size step applies (the case is volumetric). */
  volumetric: boolean;
};

export const initialRead: ReadState = {
  marks: [], nextId: 1, selectedId: null, popoverId: null, popoverMode: 'full', armed: null,
  patterns: {}, declaredNormal: false, normalConfidence: null, sizes: {}, volumetric: false,
};
export const initialVolumetricRead: ReadState = { ...initialRead, volumetric: true };

export type ReadAction =
  | { type: 'arm'; label: MarkLabel }
  | { type: 'disarm' }
  | { type: 'place'; x: number; y: number; at?: Mark3 }
  | { type: 'move'; id: string; x: number; y: number; at?: Mark3 }
  | { type: 'label'; id: string; label: MarkLabel }
  | { type: 'confidence'; id: string; confidence: Confidence }
  | { type: 'delete'; id: string }
  | { type: 'select'; id: string | null; popover?: boolean }
  | { type: 'closePopover' }
  | { type: 'togglePattern'; label: PatternLabel }
  | { type: 'patternConfidence'; label: PatternLabel; confidence: Confidence }
  | { type: 'callNormal' }
  | { type: 'undoNormal' }
  | { type: 'normalConfidence'; confidence: Confidence }
  | { type: 'recordSize'; id: string; m: DraftMeasurement }
  | { type: 'skipSize'; id: string }
  | { type: 'reset' };

export function readReducer(s: ReadState, a: ReadAction): ReadState {
  switch (a.type) {
    case 'arm':
      // Picking the armed finding again puts it down.
      if (s.declaredNormal) return s;
      return { ...s, armed: s.armed === a.label ? null : a.label, popoverId: null };
    case 'disarm':
      return s.armed ? { ...s, armed: null } : s;
    case 'place': {
      if (s.declaredNormal) return s;
      const id = `M${s.nextId}`;
      // Armed: the mark takes that label and only the confidence is asked. Not armed: the popover asks for both.
      return {
        ...s,
        marks: [...s.marks, { mark_id: id, x: a.x, y: a.y, label: s.armed, confidence: null, ...(a.at ?? {}) }],
        nextId: s.nextId + 1, selectedId: id, popoverId: id, popoverMode: s.armed ? 'confidence' : 'full', armed: null,
      };
    }
    case 'move': {
      // A moved mark's measurement no longer fits it.
      const sizes = { ...s.sizes };
      delete sizes[a.id];
      return { ...s, sizes, marks: s.marks.map((m) => (m.mark_id === a.id ? { ...m, x: a.x, y: a.y, ...(a.at ?? {}) } : m)) };
    }
    case 'label': {
      const sizes = { ...s.sizes };
      delete sizes[a.id];
      return { ...s, sizes, marks: s.marks.map((m) => (m.mark_id === a.id ? { ...m, label: a.label } : m)) };
    }
    case 'confidence': {
      const marks = s.marks.map((m) => (m.mark_id === a.id ? { ...m, confidence: a.confidence } : m));
      // The short "How sure are you?" popover has one job; it closes once that is done.
      const closes = s.popoverId === a.id && s.popoverMode === 'confidence' && !!marks.find((m) => m.mark_id === a.id)?.label;
      return { ...s, marks, popoverId: closes ? null : s.popoverId };
    }
    case 'delete': {
      const sizes = { ...s.sizes };
      delete sizes[a.id];
      return {
        ...s,
        sizes,
        marks: s.marks.filter((m) => m.mark_id !== a.id),
        selectedId: s.selectedId === a.id ? null : s.selectedId,
        popoverId: s.popoverId === a.id ? null : s.popoverId,
      };
    }
    case 'select':
      return { ...s, selectedId: a.id, popoverId: a.popover ? a.id : null, popoverMode: a.popover ? 'full' : s.popoverMode };
    case 'closePopover':
      return s.popoverId ? { ...s, popoverId: null } : s;
    case 'togglePattern': {
      if (s.declaredNormal) return s;
      const patterns = { ...s.patterns };
      if (a.label in patterns) delete patterns[a.label];
      else patterns[a.label] = null;
      return { ...s, patterns };
    }
    case 'patternConfidence':
      return a.label in s.patterns ? { ...s, patterns: { ...s.patterns, [a.label]: a.confidence } } : s;
    case 'callNormal':
      // Calling normal clears marks and whole-film findings (the UI confirms first if any exist).
      return { ...s, marks: [], patterns: {}, sizes: {}, selectedId: null, popoverId: null, armed: null, declaredNormal: true };
    case 'undoNormal':
      return { ...s, declaredNormal: false, normalConfidence: null };
    case 'normalConfidence':
      return s.declaredNormal ? { ...s, normalConfidence: a.confidence } : s;
    case 'recordSize':
      return s.marks.some((m) => m.mark_id === a.id) ? { ...s, sizes: { ...s.sizes, [a.id]: { kind: 'recorded', m: a.m } } } : s;
    case 'skipSize':
      return s.marks.some((m) => m.mark_id === a.id) ? { ...s, sizes: { ...s.sizes, [a.id]: { kind: 'skipped' } } } : s;
    case 'reset':
      return s.volumetric ? initialVolumetricRead : initialRead;
  }
}

/** Marks that still need the size step (volumes only): labelled mass-like, confidence chosen, size neither recorded
 *  nor skipped. In rail order. */
export function pendingSizes(s: ReadState): DraftMark[] {
  if (!s.volumetric || s.declaredNormal) return [];
  return s.marks.filter((m) => needsSize(m.label) && m.confidence != null && !s.sizes[m.mark_id]);
}

export const NOTHING_YET = 'Mark a finding, tick a whole-film one, or call it normal.';

/** Everything that still stands between this read and "Submit read", in the order the rail shows it.
 *  Empty = ready. Each line names exactly what is missing ("M2 needs a confidence"). */
export function submitBlockers(s: ReadState): string[] {
  if (s.declaredNormal) return s.normalConfidence == null ? ['The normal call needs a confidence'] : [];
  const out: string[] = [];
  for (const m of s.marks) {
    if (!m.label && m.confidence == null) out.push(`${m.mark_id} needs a label and a confidence`);
    else if (!m.label) out.push(`${m.mark_id} needs a label`);
    else if (m.confidence == null) out.push(`${m.mark_id} needs a confidence`);
    else if (s.volumetric && needsSize(m.label) && !s.sizes[m.mark_id]) out.push(`${m.mark_id} needs a size: measure it or skip`);
  }
  for (const [label, conf] of Object.entries(s.patterns)) {
    if (conf == null) out.push(`${labelDisplay(label)} needs a confidence`);
  }
  if (out.length === 0 && s.marks.length === 0 && Object.keys(s.patterns).length === 0) out.push(NOTHING_YET);
  return out;
}

export function canSubmit(s: ReadState): boolean {
  return submitBlockers(s).length === 0;
}

/** What a digit key (1–5) should set right now: the selected mark, else the normal call when it is active. */
export function confidenceTarget(s: ReadState): { kind: 'mark'; id: string } | { kind: 'normal' } | null {
  if (s.declaredNormal) return { kind: 'normal' };
  if (s.selectedId && s.marks.some((m) => m.mark_id === s.selectedId)) return { kind: 'mark', id: s.selectedId };
  return null;
}

/** The 3-D fields of a mark, when it has them (volumes). An X-ray mark sends none. */
const at3 = (m: DraftMark): Pick<Mark, 'plane' | 'slice' | 'voxel'> =>
  m.voxel && m.plane ? { plane: m.plane, slice: m.slice ?? null, voxel: m.voxel } : {};

/** Contract-shaped marks for submit: only complete marks (canSubmit guarantees all of them are). */
export function toSubmitMarks(s: ReadState): Mark[] {
  return s.marks.flatMap((m) => (m.label && m.confidence != null ? [{ mark_id: m.mark_id, x: m.x, y: m.y, label: m.label, confidence: m.confidence, ...at3(m) }] : []));
}
/** Marks for a hint request, which may arrive mid-read: positions matter, an unfinished label goes as "not_sure"
 *  and an unchosen confidence as the scale midpoint (the hint ladder does not read it; nothing is recorded). */
export function toHintMarks(s: ReadState): Mark[] {
  return s.marks.map((m) => ({ mark_id: m.mark_id, x: m.x, y: m.y, label: m.label ?? 'not_sure', confidence: m.confidence ?? 3, ...at3(m) }));
}
/** Recorded caliper measurements for submit (volumes; empty on an X-ray). */
export function toSubmitMeasurements(s: ReadState): Measurement[] {
  return s.marks.flatMap((m) => {
    const st = s.sizes[m.mark_id];
    return st?.kind === 'recorded' ? [{ mark_id: m.mark_id, long_mm: Math.round(st.m.long_mm * 10) / 10, plane: st.m.plane, slice: st.m.slice, p0: st.m.p0, p1: st.m.p1 }] : [];
  });
}
export function toSubmitPatterns(s: ReadState): PatternSelection[] {
  return (Object.entries(s.patterns) as [PatternLabel, Confidence | null][]).flatMap(([label, confidence]) => (confidence != null ? [{ label, confidence }] : []));
}
