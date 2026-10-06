// Display names mirror config/taxonomy.yaml (learner_focal_options / learner_pattern_options). Copy rules: SPEC §14.4.
import type { Mark, OutcomeResult, PatternSelection } from '../types/contracts';

export type FocalLabel = Exclude<Mark['label'], 'not_sure'>;
export type PatternLabel = PatternSelection['label'];

export const FOCAL_LABELS: { id: FocalLabel; display: string }[] = [
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

export const PATTERN_LABELS: { id: PatternLabel; display: string }[] = [
  { id: 'cardiomegaly', display: 'Cardiomegaly' },
  { id: 'emphysema', display: 'Emphysema' },
  { id: 'fibrosis', display: 'Fibrosis' },
  { id: 'diffuse_nodule', display: 'Diffuse nodules' },
];

const ALL: Record<string, string> = Object.fromEntries(
  [...FOCAL_LABELS, ...PATTERN_LABELS].map((l) => [l.id, l.display]),
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
};

export const PROXY_TOOLTIP = 'Based on your cursor, loupe and zoom — a proxy for where you looked.';

export const LEVELS = ['MS1', 'MS2', 'MS3', 'MS4', 'intern', 'resident', 'PA/NP student', 'other'] as const;
export const MODES = [
  { id: 'practice', display: 'Practice', note: 'Cases chosen for you. Feedback after every case.' },
  { id: 'drill', display: 'Drill', note: 'One finding at a time, mixed with normals.' },
  { id: 'assess_A', display: 'Assessment A', note: 'Fixed 20-case set. Feedback at the end.' },
  { id: 'assess_B', display: 'Assessment B', note: 'Fixed 20-case set. Feedback at the end.' },
  { id: 'review', display: 'Review missed', note: 'Cases like the ones you missed before.' },
] as const;

export function modeDisplay(mode: string): string {
  return MODES.find((m) => m.id === mode)?.display ?? mode;
}
