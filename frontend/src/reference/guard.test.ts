import { describe, expect, it } from 'vitest';
import { guardReference, guardReferenceLabel, pickExamples, safeExternalUrl, uiTerms } from './guard';

describe('guardReference', () => {
  it('returns empty lists for anything that is not the payload', () => {
    for (const v of [null, undefined, 3, 'x', [], { labels: 'no' }]) expect(guardReference(v)).toEqual({ labels: [], normal_examples: [] });
  });
  it('keeps a complete label and its examples', () => {
    const r = guardReference({
      labels: [{
        label: 'nodule', display: 'Nodule', kind: 'focal', one_liner: 'A small round spot.', key_signs: ['Round'], mimics: ['Nipple shadow'],
        commonly_confused_with: ['mass'], search_tip: 'Use the loupe.', radiopaedia_url: 'https://radiopaedia.org/articles/pulmonary-nodule', review_status: 'ai_draft',
        examples: [{ case_id: 'cxd_1', image_url: '/api/cases/cxd_1/image', width: 1024, height: 1024, finding: { finding_id: 'cxd_1#F1', polygon: [[1, 2], [3, 4], [5, 6]], bbox: [1, 2, 5, 6], relative_location: 'right upper zone', side: 'right' } }],
      }],
      normal_examples: [{ case_id: 'cxd_2', image_url: '/api/cases/cxd_2/image', width: 1024, height: 1024 }],
    });
    expect(r.labels).toHaveLength(1);
    expect(r.labels[0].examples[0].finding?.polygon).toHaveLength(3);
    expect(r.labels[0].examples[0].finding?.relative_location).toBe('right upper zone');
    expect(r.normal_examples).toHaveLength(1);
  });
  it('fills missing fields with empty values instead of throwing', () => {
    const r = guardReference({ labels: [{ label: 'pleural_thickening' }, { nope: 1 }, null], normal_examples: [{ case_id: 'x' }] });
    expect(r.labels).toHaveLength(1);
    expect(r.labels[0]).toMatchObject({ display: 'pleural thickening', kind: 'focal', one_liner: '', key_signs: [], mimics: [], examples: [], radiopaedia_url: null });
    expect(r.normal_examples).toEqual([]); // no image, no size: nothing to draw
  });
  it('drops examples without an image and tolerates a missing outline', () => {
    const r = guardReference({ labels: [{ label: 'mass', examples: [{ case_id: 'a' }, { case_id: 'b', image_url: '/i.png', width: 10, height: 10, finding: { polygon: [[1, 1]], bbox: [0, 0, 1] } }] }] });
    expect(r.labels[0].examples).toHaveLength(1);
    expect(r.labels[0].examples[0].finding).toMatchObject({ polygon: null, bbox: null, relative_location: '' });
  });
  it('reads the nested review status of a raw teaching card', () => {
    expect(guardReference({ labels: [{ label: 'mass', review: { status: 'student_reviewed' } }] }).labels[0].review_status).toBe('student_reviewed');
  });
});

describe('safeExternalUrl', () => {
  it('accepts https only', () => {
    expect(safeExternalUrl('https://radiopaedia.org/articles/pulmonary-nodule')).toBe('https://radiopaedia.org/articles/pulmonary-nodule');
    for (const bad of ['javascript:alert(1)', 'http://radiopaedia.org/x', 'radiopaedia.org', '', null, 4]) expect(safeExternalUrl(bad)).toBeNull();
  });
});

describe('uiTerms', () => {
  it('calls the lens the magnifier', () => {
    expect(uiTerms('Use the loupe on the apices. Loupe off.')).toBe('Use the magnifier on the apices. Magnifier off.');
  });
});

describe('guardReference — volumetric examples (round 4)', () => {
  it('reads a CT example with its volume block, the measure slice and the finding values', () => {
    const r = guardReference({ labels: [{
      label: 'pancreatic_tumour', display: 'Pancreatic tumour', kind: 'focal',
      examples: [{
        case_id: 'vol_001', image_url: '/api/cases/vol_001/image', width: 64, height: 64, modality: 'ct',
        volume_url: '/api/cases/vol_001/volume', mask_url: '/api/cases/vol_001/maskvol', shape: [16, 64, 64], spacing: [3, 1.5, 1.5], window: { wc: 50, ww: 400 },
        provenance: { dataset: 'Medical Segmentation Decathlon, Task07 Pancreas', segmented_by: 'an abdominal radiologist (single reader)' },
        finding: { finding_id: 'vol_001#F1', bbox: [20, 32, 29, 41], relative_location: 'middle slices of the volume', slice_range: [6, 10], measure: { long_mm: 13.5, slice: 8 }, label_values: [2] },
      }],
    }] });
    const l = r.labels[0];
    expect(l.modality).toBe('ct');
    const ex = l.examples[0];
    expect(ex.modality).toBe('ct');
    expect(ex.volume).toEqual({ volume_url: '/api/cases/vol_001/volume', mask_url: '/api/cases/vol_001/maskvol', shape: [16, 64, 64], spacing: [3, 1.5, 1.5], window: { wc: 50, ww: 400 }, slice: 8, label_values: [2] });
    expect(ex.finding?.slice_range).toEqual([6, 10]);
    expect(ex.provenance).toMatchObject({ dataset: 'Medical Segmentation Decathlon, Task07 Pancreas' });
  });
  it('a volume example without a preview image still renders (the slice is drawn from the voxels); a broken volume block is dropped', () => {
    const r = guardReference({ labels: [{ label: 'brain_tumour', examples: [
      { case_id: 'v', volume_url: '/v.gz', mask_url: '/m.gz', shape: [8, 32, 32] },
      { case_id: 'w', volume_url: '/v.gz', shape: [8, 32, 32] },
    ] }] });
    expect(r.labels[0].modality).toBe('mr');
    expect(r.labels[0].examples).toHaveLength(1);
    const ex = r.labels[0].examples[0];
    expect(ex.volume?.slice).toBe(4);
    expect(ex.volume?.spacing).toEqual([1, 1, 1]);
    expect(ex.volume?.window.ww).toBe(1000);
  });
  it('an X-ray example without a modality stays cxr and carries no volume', () => {
    const r = guardReference({ labels: [{ label: 'nodule', examples: [{ case_id: 'c', image_url: '/i.png', width: 10, height: 10 }] }] });
    expect(r.labels[0].modality).toBe('cxr');
    expect(r.labels[0].examples[0]).toMatchObject({ modality: 'cxr', volume: null, provenance: null });
  });
});

describe('pickExamples (round 5: the two thumbnails under a debrief row)', () => {
  const ex = (case_id: string, outline: boolean, volume = false) => ({
    case_id, image_url: `/i/${case_id}.png`, width: 10, height: 10, modality: 'cxr' as const, provenance: null,
    volume: volume ? { volume_url: '/v', mask_url: '/m', shape: [4, 4, 4] as [number, number, number], spacing: [1, 1, 1] as [number, number, number], window: { wc: 0, ww: 1 }, slice: 1, label_values: [] } : null,
    finding: outline ? { finding_id: `${case_id}#F1`, polygon: [[1, 1], [2, 2], [3, 1]] as [number, number][], bbox: null, relative_location: 'right upper zone', side: 'right', slice_range: null } : null,
  });
  it('prefers examples with an outline to draw, distinct cases, at most n', () => {
    const got = pickExamples([ex('a', false), ex('b', true), ex('b', true), ex('c', true), ex('d', true)], 2);
    expect(got.map((e) => e.case_id)).toEqual(['b', 'c']);
  });
  it('falls back to plain films when no outline exists, and never shows the case being read', () => {
    expect(pickExamples([ex('a', false), ex('b', false)], 2).map((e) => e.case_id)).toEqual(['a', 'b']);
    expect(pickExamples([ex('a', true), ex('b', true), ex('c', true)], 2, 'a').map((e) => e.case_id)).toEqual(['b', 'c']);
    expect(pickExamples([], 2)).toEqual([]);
  });
  it('counts a volume example as drawable', () => {
    expect(pickExamples([ex('a', false), ex('v', false, true)], 1).map((e) => e.case_id)).toEqual(['v']);
  });
  it('guardReferenceLabel reads one entry with its sign ids', () => {
    const l = guardReferenceLabel({ label: 'effusion', signs: ['meniscus', 3, ''], examples: [] });
    expect(l?.signs).toEqual(['meniscus']);
    expect(guardReferenceLabel(null)).toBeNull();
  });
});
