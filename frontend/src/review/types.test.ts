import { describe, expect, it } from 'vitest';
import { approvalStatus, cardDraft, cardEdits, guardCardItems, guardDebriefItems } from './types';
import type { TeachingCard } from '../types/contracts';

const card: TeachingCard = {
  label: 'nodule', display_name: 'Nodule', kind: 'focal', one_liner: 'A round spot.', key_signs: ['Round', 'Sharp edge'],
  where_it_hides: ['right_apex'], mimics: ['Nipple'], commonly_confused_with: [], search_tip: 'Check apices.', radiopaedia_url: null,
  review: { status: 'ai_draft', reviewer: null, date: null, notes: null },
};

describe('review types', () => {
  it('approval never downgrades a card', () => {
    expect(approvalStatus('Radiologist', 'ai_draft')).toBe('radiologist_reviewed');
    expect(approvalStatus('Medical student', 'ai_draft')).toBe('student_reviewed');
    expect(approvalStatus('Medical student', 'radiologist_reviewed')).toBe('radiologist_reviewed');
  });
  it('cardEdits returns only changed fields', () => {
    const d = cardDraft(card);
    expect(cardEdits(card, d)).toEqual({});
    d.key_signs = 'Round\n  Sharp edge  \n\nCalcified';
    d.one_liner = 'A round spot. ';
    d.radiopaedia_url = '';
    expect(cardEdits(card, d)).toEqual({ key_signs: ['Round', 'Sharp edge', 'Calcified'] });
    d.radiopaedia_url = 'https://radiopaedia.org/articles/nodule';
    expect(cardEdits(card, d).radiopaedia_url).toBe('https://radiopaedia.org/articles/nodule');
  });
  it('guards drop malformed items', () => {
    expect(guardDebriefItems({ items: [{ nope: 1 }, { item_id: 'x', case_id: 'cxd_1', learner: { marks: [{ x: 1, y: 2, mark_id: 'M1' }] } }] })).toHaveLength(1);
    expect(guardDebriefItems(null)).toEqual([]);
    expect(guardCardItems({ items: [{ item_id: 'nodule', card }] })).toHaveLength(1);
  });
});
