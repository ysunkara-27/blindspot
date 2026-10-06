// Smoke test for the read-only review block (static markup; the film layer itself needs a measured width).
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { SubmitResult } from '../types/contracts';
import { CaseReview } from './CaseReview';

const result: SubmitResult = {
  score: 62, success: false,
  outcomes: [
    { target: 'F1', result: 'missed_search', dwell_ms: 0, zone: 'left_lower_zone' },
    { target: 'M1', result: 'false_positive', zone: 'right_upper_zone', learner_label: 'nodule' },
  ],
  reveal: {
    findings: [{ finding_id: 'F1', label: 'effusion', display: 'Pleural effusion', kind: 'focal', polygon: null, bbox: [600, 800, 700, 900], zones: ['left_lower_zone'], primary_zone: 'left_lower_zone', relative_location: 'left costophrenic angle', result: 'missed_search', dwell_ms: 0 }],
    marks: [{ mark_id: 'M1', result: 'false_positive', zone: 'right_upper_zone' }],
    arrows: [],
    search: { lung_coverage_pct: 41, unvisited_review_areas: ['left_costophrenic_angle'] },
    is_normal: false,
  },
  facts_card: { headline: 'Missed: Pleural effusion', lines: ['F1 Pleural effusion — left costophrenic angle: Never looked there; dwell 0 ms.'] },
  debrief_status: 'pending',
};
const marks = [{ mark_id: 'M1', x: 300, y: 300, label: 'nodule', confidence: 4 }];

describe('CaseReview', () => {
  it('renders the film block with its key, and nothing interactive', () => {
    const html = renderToStaticMarkup(<CaseReview result={result} imageUrl="/api/cases/cxd_1/image" width={1024} height={1024} marks={marks} />);
    expect(html).toContain('data-testid="case-figure"');
    expect(html).toContain('Expert outline');
    expect(html).toContain('Patient right is on the image left');
    expect(html).not.toContain('data-testid="outcomes"');
    expect(html).not.toContain('<input');
  });
  it('with `summary`, adds the one merged list and the search summary, in words', () => {
    const html = renderToStaticMarkup(<CaseReview result={result} imageUrl="/x.png" width={1024} height={1024} marks={marks} summary />);
    expect(html).toContain('data-testid="outcomes"');
    expect(html).toContain('Score <strong>62</strong> / 100');
    expect(html).toContain('No time spent there.');
    expect(html).toContain('Radiologists marked nothing here; you called it nodule.');
    expect(html).toContain('Review areas you did not visit: left costophrenic angle.');
    expect(html).not.toMatch(/dwell|0 ms/);
  });
});
