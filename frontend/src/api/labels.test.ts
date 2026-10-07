import { describe, expect, it } from 'vitest';
import { FOCAL_LABELS, FOCAL_LABELS_BY_MODALITY, isModality, labelDisplay, labelsFor, MODALITY_DISPLAY, modalityDisplay, OUTCOME_COPY, PATTERN_LABELS, VOLUMETRIC_LABELS } from './labels';
import type { OutcomeResult } from '../types/contracts';

describe('labels by scan type (round 4; mirrors config/taxonomy.yaml learner_focal_options_by_modality)', () => {
  it('X-ray keeps the nine focal and four pattern findings, in order', () => {
    expect(FOCAL_LABELS_BY_MODALITY.cxr).toBe(FOCAL_LABELS);
    expect(labelsFor('cxr').map((l) => l.id)).toEqual([...FOCAL_LABELS, ...PATTERN_LABELS].map((l) => l.id));
    expect(labelsFor('cxr')).toHaveLength(13);
  });
  it('CT and MR list only their tumours, with no whole-film patterns', () => {
    expect(labelsFor('ct').map((l) => l.id)).toEqual(['pancreatic_tumour', 'liver_tumour', 'lung_tumour', 'colon_tumour']);
    expect(labelsFor('mr').map((l) => l.id)).toEqual(['brain_tumour']);
    expect(labelsFor('ct').map((l) => l.display)).toEqual(['Pancreatic tumour', 'Liver tumour', 'Lung tumour', 'Colon tumour']);
    expect(labelsFor('mr')[0].display).toBe('Brain tumour');
  });
  it('an unknown or missing scan type is the X-ray list', () => {
    expect(labelsFor(undefined)).toEqual(labelsFor('cxr'));
    expect(labelsFor('pet')).toEqual(labelsFor('cxr'));
    expect(isModality('ct')).toBe(true);
    expect(isModality('xray')).toBe(false);
  });
  it('display names cover the new labels', () => {
    for (const l of VOLUMETRIC_LABELS) expect(labelDisplay(l.id)).toBe(l.display);
    expect(labelDisplay('liver_tumour')).toBe('Liver tumour');
    expect(modalityDisplay('ct')).toBe('Abdominal CT');
    expect(modalityDisplay('mr', 'short')).toBe('MRI');
    expect(modalityDisplay(null)).toBe('Chest X-ray');
    expect(MODALITY_DISPLAY.ct.region).toBe('abdomen');
    expect(MODALITY_DISPLAY.mr.region).toBe('brain');
  });
  it('"unmatched" (a mark the reference does not label) is neutral, never a miss or an overcall', () => {
    expect(OUTCOME_COPY.unmatched).toEqual({ text: 'Not in the reference', tone: 'neutral' });
    const all: OutcomeResult[] = ['found', 'mislabeled', 'missed_search', 'missed_recognition', 'missed_decision', 'pattern_found', 'pattern_missed', 'pattern_false', 'true_positive', 'duplicate', 'false_positive', 'true_negative', 'unmatched'];
    for (const r of all) expect(OUTCOME_COPY[r].text).toBeTruthy();
  });
});
