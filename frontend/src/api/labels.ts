// Display names mirror config/taxonomy.yaml (learner_focal_options / learner_focal_options_by_modality /
// learner_pattern_options). Copy rules: SPEC §14.4.
import type { Mark, Modality, OutcomeResult, PatternSelection } from '../types/contracts';

export type FocalLabel = Exclude<Mark['label'], 'not_sure'>;
export type PatternLabel = PatternSelection['label'];
export type LabelOption<T extends string = string> = { id: T; display: string };

/** The X-ray focal findings (taxonomy `learner_focal_options`). */
export const FOCAL_LABELS: LabelOption<FocalLabel>[] = [
  { id: 'pneumothorax', display: 'Pneumothorax' },
  { id: 'effusion', display: 'Pleural effusion' },
  { id: 'consolidation', display: 'Consolidation' },
  { id: 'atelectasis', display: 'Atelectasis' },
  { id: 'nodule', display: 'Nodule' },
  { id: 'mass', display: 'Mass' },
  { id: 'calcification', display: 'Calcification' },
  { id: 'fracture', display: 'Fracture' },
  { id: 'pleural_thickening', display: 'Pleural thickening' },
];

/** Volumetric (CT / MR) focal findings; organs are zones, not findings. */
export const VOLUMETRIC_LABELS: LabelOption<FocalLabel>[] = [
  { id: 'pancreatic_tumour', display: 'Pancreatic tumour' },
  { id: 'liver_tumour', display: 'Liver tumour' },
  { id: 'brain_tumour', display: 'Brain tumour' },
  { id: 'lung_tumour', display: 'Lung tumour' },
  { id: 'colon_tumour', display: 'Colon tumour' },
];

const byId = (ids: FocalLabel[]) => ids.map((id) => [...FOCAL_LABELS, ...VOLUMETRIC_LABELS].find((l) => l.id === id)!);

/** Mirrors taxonomy `learner_focal_options_by_modality`: what a learner may mark on each scan type. */
export const FOCAL_LABELS_BY_MODALITY: Record<Modality, LabelOption<FocalLabel>[]> = {
  cxr: FOCAL_LABELS,
  ct: byId(['pancreatic_tumour', 'liver_tumour', 'lung_tumour', 'colon_tumour']),
  mr: byId(['brain_tumour']),
};

export const MODALITIES: Modality[] = ['cxr', 'ct', 'mr'];
export const isModality = (v: unknown): v is Modality => typeof v === 'string' && (MODALITIES as string[]).includes(v);

/** The findings a learner can choose or mark on this scan type: focal labels of the modality, plus the whole-film
 *  patterns on an X-ray (CT / MR have no pattern findings). An unknown modality falls back to the X-ray list. */
export function labelsFor(modality: Modality | string | null | undefined): LabelOption[] {
  const m: Modality = isModality(modality) ? modality : 'cxr';
  return m === 'cxr' ? [...FOCAL_LABELS, ...PATTERN_LABELS] : FOCAL_LABELS_BY_MODALITY[m];
}

/** Scan-type names as the learner sees them. */
export const MODALITY_DISPLAY: Record<Modality, { short: string; long: string; region: 'chest' | 'abdomen' | 'brain' }> = {
  cxr: { short: 'Chest X-ray', long: 'Chest X-ray', region: 'chest' },
  ct: { short: 'CT', long: 'Abdominal CT', region: 'abdomen' },
  mr: { short: 'MRI', long: 'Brain MRI', region: 'brain' },
};
export const modalityDisplay = (m: string | null | undefined, form: 'short' | 'long' = 'long') => (isModality(m) ? MODALITY_DISPLAY[m][form] : MODALITY_DISPLAY.cxr[form]);

export const PATTERN_LABELS: { id: PatternLabel; display: string }[] = [
  { id: 'cardiomegaly', display: 'Cardiomegaly' },
  { id: 'emphysema', display: 'Emphysema' },
  { id: 'fibrosis', display: 'Fibrosis' },
  { id: 'diffuse_nodule', display: 'Diffuse nodules' },
];

const ALL: Record<string, string> = Object.fromEntries(
  [...FOCAL_LABELS, ...VOLUMETRIC_LABELS, ...PATTERN_LABELS].map((l) => [l.id, l.display]),
);
ALL.not_sure = 'Not sure';

export function labelDisplay(id: string | null | undefined): string {
  if (!id) return 'Unlabeled';
  return ALL[id] ?? id.replace(/_/g, ' ');
}

/** Zone ids name the PATIENT's side (CLAUDE.md rule 3). "right_upper_zone" → "right upper zone". */
export function zoneDisplay(zone: string | null | undefined): string {
  return zone ? zone.replace(/_/g, ' ') : '';
}

export type OutcomeTone = 'found' | 'missed' | 'overcall' | 'neutral';

/** Outcome copy (SPEC §14.3 step 4) and tone. Cyan = truth, amber = learner. Never red/green. */
export const OUTCOME_COPY: Record<OutcomeResult, { text: string; tone: OutcomeTone; missType?: string }> = {
  found: { text: 'Found it', tone: 'found' },
  pattern_found: { text: 'Found it', tone: 'found' },
  true_positive: { text: 'Found it', tone: 'found' },
  true_negative: { text: 'Correctly called normal', tone: 'found' },
  mislabeled: { text: 'Found it, named it wrong', tone: 'missed', missType: 'interpretation' },
  missed_search: { text: 'Never looked there', tone: 'missed', missType: 'search' },
  missed_recognition: { text: 'Looked past it', tone: 'missed', missType: 'recognition' },
  missed_decision: { text: 'Looked, judged it normal', tone: 'missed', missType: 'decision' },
  pattern_missed: { text: 'Not called', tone: 'missed' },
  false_positive: { text: "Called something that isn't there", tone: 'overcall', missType: 'overcall' },
  pattern_false: { text: "Called something that isn't there", tone: 'overcall', missType: 'overcall' },
  duplicate: { text: 'Second mark on the same finding', tone: 'neutral' },
  // CT / MR: public reference sets are not exhaustive, so a mark the reference does not label is reported, never penalised.
  unmatched: { text: 'Not in the reference', tone: 'neutral' },
};

export const PROXY_TOOLTIP = 'Based on your cursor, magnifier and zoom — a proxy for where you looked.';

export const LEVELS = ['MS1', 'MS2', 'MS3', 'MS4', 'intern', 'resident', 'PA/NP student', 'other'] as const;
export const MODES = [
  { id: 'practice', display: 'Practice', note: 'Films chosen for you. Feedback after every film.' },
  { id: 'drill', display: 'One finding type', note: 'One finding at a time, mixed with normal films.' },
  { id: 'assess_A', display: 'Test set A', note: 'A fixed set of 20 films. Feedback at the end.' },
  { id: 'assess_B', display: 'Test set B', note: 'A fixed set of 20 films. Feedback at the end.' },
  { id: 'review', display: 'Review missed', note: 'Films like the ones you missed before.' },
] as const;

export function modeDisplay(mode: string): string {
  return MODES.find((m) => m.id === mode)?.display ?? mode;
}
