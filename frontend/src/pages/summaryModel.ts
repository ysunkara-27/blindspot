// The end-of-set summary as data: a guard for GET /sessions/{sid}/summary (round-3 rows, with fallbacks for an older
// server) and the plain-language read-outs built from it. Pure; unit-tested in summaryModel.test.ts.
import { isModality } from '../api/labels';
import { guardStats, MISS_BUCKETS, type CaseStats, type MissBucket, type MissMix } from '../dashboard/types';
import type { Modality } from '../types/contracts';

export type SummaryRow = {
  attemptId: string | null;
  caseId: string;
  index: number;
  score: number;
  success: boolean;
  isNormal: boolean | null;
  /** Display names of what was on the film ([] on a normal film). */
  findings: string[];
  missTypes: MissBucket[];
  nFindings: number;
  nFound: number;
  nFalse: number;
  /** cxr | ct | mr; null from an older server (every case was a chest film). */
  modality: Modality | null;
  /** The '___ by ___' block or sentence, when the row carries one. */
  provenance: unknown;
};

export type SetSummary = {
  sessionId: string;
  mode: string;
  /** The set's scan type: the server's, else the rows' when they agree, else null (mixed or unknown). */
  modality: Modality | null;
  nCases: number;
  /** Films in the set, when it has a fixed length. */
  total: number | null;
  complete: boolean;
  stats: CaseStats | null;
  mix: MissMix;
  rows: SummaryRow[];
};

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const num = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const strs = (v: unknown) => arr(v).filter((x): x is string => typeof x === 'string');

const FOUND = new Set(['found', 'pattern_found']);
const MISS_OF: Record<string, MissBucket> = {
  missed_search: 'search', missed_recognition: 'recognition', missed_decision: 'decision', mislabeled: 'interpretation',
  false_positive: 'overcall', pattern_false: 'overcall',
};

function row(v: unknown, i: number): SummaryRow[] {
  if (!isObj(v)) return [];
  const outcomes = arr(v.outcomes).flatMap((o) => (isObj(o) && typeof o.result === 'string' ? [{ target: String(o.target ?? ''), result: o.result }] : []));
  const findings = arr(v.findings).flatMap((f) => (isObj(f) ? [{ id: String(f.finding_id ?? ''), display: typeof f.display === 'string' ? f.display : String(f.label ?? '').replace(/_/g, ' ') }] : []));
  const byTarget = new Map(outcomes.map((o) => [o.target, o.result]));
  const displays = strs(v.label_displays);
  const derivedMiss = [...new Set(outcomes.flatMap((o) => (MISS_OF[o.result] ? [MISS_OF[o.result]] : [])))];
  const given = strs(v.miss_types).filter((m): m is MissBucket => (MISS_BUCKETS as readonly string[]).includes(m));
  const isNormal = typeof v.is_normal === 'boolean' ? v.is_normal : null;
  return [{
    attemptId: typeof v.attempt_id === 'string' && v.attempt_id ? v.attempt_id : null,
    caseId: typeof v.case_id === 'string' ? v.case_id : '',
    index: num(v.index) ? v.index : i + 1,
    score: num(v.score) ? Math.round(v.score) : 0,
    success: v.success === true,
    isNormal,
    findings: displays.length ? displays : [...new Set(findings.map((f) => f.display).filter(Boolean))],
    // Kundel order, whatever order the server sent.
    missTypes: MISS_BUCKETS.filter((b) => (Array.isArray(v.miss_types) ? given : derivedMiss).includes(b)),
    nFindings: num(v.n_findings) ? v.n_findings : findings.length,
    nFound: num(v.n_found) ? v.n_found : findings.filter((f) => FOUND.has(byTarget.get(f.id) ?? '')).length,
    nFalse: num(v.n_false_positives) ? v.n_false_positives : outcomes.filter((o) => o.result === 'false_positive').length,
    modality: isModality(v.modality) ? v.modality : null,
    provenance: v.provenance ?? null,
  }];
}

export function guardSetSummary(v: unknown): SetSummary {
  const o = isObj(v) ? v : {};
  const rows = arr(o.cases).flatMap(row);
  const nCases = num(o.n_cases) ? o.n_cases : rows.length;
  const total = num(o.total) ? o.total : null;
  const stats = guardStats({
    n: nCases,
    n_abnormal: num(o.n_abnormal) ? o.n_abnormal : rows.filter((r) => r.isNormal === false).length,
    n_normal: num(o.n_normal) ? o.n_normal : rows.filter((r) => r.isNormal === true).length,
    n_focal_findings: o.n_focal_findings,
    sensitivity: o.sensitivity,
    specificity: o.specificity,
    localization_fraction: o.localization_fraction,
    false_positives_per_image: o.false_positives_per_image,
    miss_type_mix: o.miss_type_mix,
    score_mean: o.score_mean,
  });
  const mix = stats?.miss_type_mix ?? (Object.fromEntries(MISS_BUCKETS.map((b) => [b, 0])) as MissMix);
  const settings = isObj(o.settings) ? o.settings : {};
  const rowMods = new Set(rows.map((r) => r.modality).filter(Boolean));
  const modality = isModality(o.modality) ? o.modality : isModality(settings.modality) ? settings.modality : rowMods.size === 1 ? [...rowMods][0]! : null;
  return {
    sessionId: typeof o.session_id === 'string' ? o.session_id : '',
    mode: typeof o.mode === 'string' ? o.mode : 'practice',
    modality,
    nCases,
    total,
    // An older server sends no flag: a set with a known length is complete when all of it is read.
    complete: typeof o.complete === 'boolean' ? o.complete : total == null || nCases >= total,
    stats,
    mix,
    rows,
  };
}

/** The counts on the end screen. Counts, not percentages: a set is too short for a percentage to mean much. */
export function headline(rows: readonly SummaryRow[]) {
  const normals = rows.filter((r) => r.isNormal === true);
  return {
    films: rows.length,
    findings: rows.reduce((a, r) => a + r.nFindings, 0),
    found: rows.reduce((a, r) => a + r.nFound, 0),
    normals: normals.length,
    normalsRight: normals.filter((r) => r.success).length,
    falseAlarms: rows.reduce((a, r) => a + r.nFalse, 0),
  };
}

export const MOST_OFTEN: Record<MissBucket, string> = {
  search: 'You most often never looked at the finding.',
  recognition: 'You most often looked at the finding and moved on.',
  decision: 'You most often looked at the finding and judged it normal.',
  interpretation: 'You most often found the finding but gave it the wrong name.',
  overcall: 'You most often marked something that was not a finding.',
};
export const NO_MISSES = 'No misses and no false alarms in this set.';

/** The most common miss type in plain words. A tie goes to the earlier stage of the search (Kundel order). */
export function commonMiss(mix: MissMix): { bucket: MissBucket | null; n: number; text: string } {
  let best: MissBucket | null = null;
  for (const b of MISS_BUCKETS) if (mix[b] > 0 && (best == null || mix[b] > mix[best])) best = b;
  return best ? { bucket: best, n: mix[best], text: MOST_OFTEN[best] } : { bucket: null, n: 0, text: NO_MISSES };
}

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`;

/** One line for a film in the per-film list: what was on it and what happened. A CT / MR row says "study". */
export function rowLine(r: SummaryRow, missName: (b: MissBucket) => string): { what: string; outcome: string } {
  const noun = r.modality && r.modality !== 'cxr' ? 'study' : 'film';
  if (r.isNormal) {
    const outcome = r.success ? 'Correctly called normal' : r.nFalse > 0 ? `${plural(r.nFalse, 'false alarm')} on a normal ${noun}` : 'Called abnormal';
    return { what: noun === 'film' ? 'Normal film' : 'No lesion', outcome };
  }
  const what = r.findings.length ? r.findings.join(', ') : plural(r.nFindings, 'finding');
  const found = r.nFindings ? `Found ${r.nFound} of ${r.nFindings}` : '';
  const misses = r.missTypes.map((b) => missName(b).toLowerCase());
  return { what, outcome: [found, ...misses].filter(Boolean).join(' · ') };
}
