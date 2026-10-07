import { describe, expect, it } from 'vitest';
import { commonMiss, guardSetSummary, headline, NO_MISSES, rowLine, type SummaryRow } from './summaryModel';

const mix = (o: Partial<Record<'search' | 'recognition' | 'decision' | 'interpretation' | 'overcall', number>>) => ({ search: 0, recognition: 0, decision: 0, interpretation: 0, overcall: 0, ...o });
const name = (b: string) => ({ search: 'Never looked there', recognition: 'Looked past it', decision: 'Looked, judged it normal', interpretation: 'Found it, named it wrong', overcall: "Called something that isn't there" })[b]!;

describe('end-of-set summary', () => {
  it('reads round-3 rows', () => {
    const s = guardSetSummary({
      session_id: 's1', mode: 'practice', n_cases: 2, total: 5, complete: false, miss_type_mix: { search: 1 }, score_mean: 50,
      cases: [
        { attempt_id: 'a1', case_id: 'cxd_1', index: 1, score: 39.6, success: false, is_normal: false, labels: ['nodule', 'effusion'], label_displays: ['Nodule', 'Pleural effusion'], miss_types: ['overcall', 'search'], n_findings: 2, n_found: 1, n_false_positives: 1 },
        { attempt_id: 'a2', case_id: 'cxd_2', index: 2, score: 100, success: true, is_normal: true, labels: [], label_displays: [], miss_types: [], n_findings: 0, n_found: 0, n_false_positives: 0 },
      ],
    });
    expect(s.complete).toBe(false);
    expect(s.total).toBe(5);
    expect(s.rows[0]).toMatchObject({ attemptId: 'a1', score: 40, findings: ['Nodule', 'Pleural effusion'], missTypes: ['search', 'overcall'], nFound: 1 });
    expect(headline(s.rows)).toEqual({ films: 2, findings: 2, found: 1, normals: 1, normalsRight: 1, falseAlarms: 1 });
    expect(rowLine(s.rows[0], name)).toEqual({ what: 'Nodule, Pleural effusion', outcome: "Found 1 of 2 · never looked there · called something that isn't there" });
    expect(rowLine(s.rows[1], name)).toEqual({ what: 'Normal film', outcome: 'Correctly called normal' });
  });

  it('derives the row fields from outcomes and findings on an older server', () => {
    const s = guardSetSummary({
      n_cases: 1,
      cases: [{ case_id: 'cxd_3', score: 20, is_normal: false,
        outcomes: [{ target: 'F1', result: 'found' }, { target: 'F2', result: 'missed_decision' }, { target: 'M2', result: 'false_positive' }],
        findings: [{ finding_id: 'F1', kind: 'focal', display: 'Nodule' }, { finding_id: 'F2', kind: 'focal', display: 'Mass' }] }],
    });
    expect(s.complete).toBe(true);
    expect(s.rows[0]).toMatchObject({ attemptId: null, index: 1, findings: ['Nodule', 'Mass'], nFindings: 2, nFound: 1, nFalse: 1, missTypes: ['decision', 'overcall'] });
  });

  it('survives junk', () => {
    const s = guardSetSummary('nope');
    expect(s.rows).toEqual([]);
    expect(s.nCases).toBe(0);
    expect(headline(s.rows).films).toBe(0);
  });

  it('names the most common miss in plain words; ties go to the earlier stage', () => {
    expect(commonMiss(mix({ search: 3, decision: 1 })).text).toBe('You most often never looked at the finding.');
    expect(commonMiss(mix({ decision: 2, overcall: 2 })).bucket).toBe('decision');
    expect(commonMiss(mix({ overcall: 4, search: 1 })).text).toBe('You most often marked something that was not a finding.');
    expect(commonMiss(mix({}))).toEqual({ bucket: null, n: 0, text: NO_MISSES });
  });

  it('says what went wrong on a normal film', () => {
    const base: Omit<SummaryRow, 'isNormal' | 'success' | 'nFalse'> = { attemptId: 'a', caseId: 'c', index: 1, score: 0, findings: [], missTypes: [], nFindings: 0, nFound: 0, modality: null, provenance: null };
    expect(rowLine({ ...base, isNormal: true, success: false, nFalse: 2, missTypes: ['overcall'] }, name).outcome).toBe('2 false alarms on a normal film');
    expect(rowLine({ ...base, isNormal: true, success: false, nFalse: 0 }, name).outcome).toBe('Called abnormal');
    // A CT / MR row is a study, and its "normal" is a lesion-free slab.
    const ct = rowLine({ ...base, modality: 'ct', isNormal: true, success: false, nFalse: 1, missTypes: ['overcall'] }, name);
    expect(ct).toEqual({ what: 'No lesion', outcome: '1 false alarm on a normal study' });
  });

  it('reads the scan type and provenance of a row, and the set\'s scan type from the rows when the server does not say', () => {
    const prov = { dataset: 'Medical Segmentation Decathlon, Task07 Pancreas', segmented_by: 'an abdominal radiologist (single reader)' };
    const sm = guardSetSummary({ session_id: 's', mode: 'practice', cases: [
      { attempt_id: 'a1', case_id: 'vol_001', index: 1, score: 80, success: true, is_normal: false, modality: 'ct', provenance: prov, findings: [], outcomes: [] },
      { attempt_id: 'a2', case_id: 'vol_002', index: 2, score: 100, success: true, is_normal: true, modality: 'ct', findings: [], outcomes: [] },
    ] });
    expect(sm.rows.map((r) => r.modality)).toEqual(['ct', 'ct']);
    expect(sm.rows[0].provenance).toEqual(prov);
    expect(sm.modality).toBe('ct');
    expect(guardSetSummary({ cases: [{ attempt_id: 'a', case_id: 'c', modality: 'cxr' }, { attempt_id: 'b', case_id: 'd', modality: 'mr' }] }).modality).toBeNull();
    expect(guardSetSummary({ settings: { modality: 'mr' }, cases: [] }).modality).toBe('mr');
    expect(guardSetSummary({ cases: [{ attempt_id: 'a', case_id: 'c', modality: 'xray' }] }).rows[0].modality).toBeNull();
  });
});
