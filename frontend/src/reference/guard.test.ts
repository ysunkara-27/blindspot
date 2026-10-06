import { describe, expect, it } from 'vitest';
import { guardReference, safeExternalUrl, uiTerms } from './guard';

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
