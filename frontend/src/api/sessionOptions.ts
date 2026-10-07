// Round 3, pages side: the start screen → SessionCreate mapping, the learner remembered on this device, and the
// stored result of one read for the review page. Pure functions first (unit-tested in sessionOptions.test.ts);
// storage and fetch at the bottom. The finding library has its own module (api/reference.ts).
import { enoughReads, MIN_READS } from '../dashboard/helpers';
import type { Health, Modality, Mode, SessionCreate, SubmitResult } from '../types/contracts';
import { request } from './client';
import { isModality, MODALITIES, MODALITY_DISPLAY } from './labels';

/** The backend serves the curated six-film set to this display name. Never shown to a learner. */
export const SAMPLE_NAME = 'Demo';
export const SAMPLE_LABEL = 'Sample set';
export const ANONYMOUS_NAME = 'Anonymous';
export const COUNTS = [5, 10, 20] as const;
export type Count = (typeof COUNTS)[number];
export const TEST_FILMS = 20;

/** What the learner picks under "What do you want to practice?". */
export type Practice = 'mixed' | 'weak' | 'finding' | 'test';
/** `modality` is the scan type chosen first on the page; absent = Chest X-ray (the contract's default). */
export type StartForm = { name: string; practice: Practice; finding: string; count: Count; modality?: Modality };
export type TestSet = 'A' | 'B';
/** Kept in localStorage so a returning learner resumes the same reading log on this device. */
export type Remembered = { learnerId: string; name: string; tests: TestSet[] };
export type StartContext = { remembered: Remembered | null; reads: number | null; projector?: boolean };

/** A personal code such as "MK-2041": the server finds the same learner by it from any computer. */
export const looksLikeCode = (v: string) => /^[A-Za-z]{0,4}[-_]?\d{2,6}$/.test(v.trim());

const fold = (v: string) => v.trim().toLowerCase();

/** The same person as last time: the name field still holds the remembered name (blank = the anonymous learner). */
export function sameLearner(r: Remembered | null, name: string): r is Remembered {
  return !!r && fold(r.name) === fold(name);
}

/** "My weak spots" needs a history to draw on. */
export const weakSpotsReady = (reads: number | null | undefined) => enoughReads(reads);

/** What one case is called: an X-ray is a film; a CT or MR is a study. */
export const caseNoun = (modality: Modality | string | null | undefined, n = 1): string => {
  const w = modality == null || modality === 'cxr' ? 'film' : 'study';
  return n === 1 ? w : w === 'film' ? 'films' : 'studies';
};

export function weakSpotsNote(reads: number | null | undefined, modality: Modality = 'cxr'): string {
  const noun = caseNoun(modality, 2);
  if (weakSpotsReady(reads)) return `${noun.charAt(0).toUpperCase() + noun.slice(1)} like the ones you have missed most.`;
  const n = Math.max(0, Math.floor(reads ?? 0));
  const left = MIN_READS - n;
  const scope = modality === 'cxr' ? '' : ' of this scan type';
  return `Opens after ${MIN_READS} ${noun}${scope}, so there is something to go on. You have read ${n}; ${left} to go.`;
}

/** "Test myself" exists for chest films only: the fixed test sets are X-ray sets. */
export const testAvailable = (modality: Modality | undefined) => modality == null || modality === 'cxr';
export const TEST_UNAVAILABLE = 'Not yet available for this scan type.';

/** The test sets come in order: A first, then B. With both taken, A comes round again. */
export function nextTest(done: readonly TestSet[]): { mode: Extract<Mode, 'assess_A' | 'assess_B'>; set: TestSet; repeat: boolean } {
  if (done.includes('A') && !done.includes('B')) return { mode: 'assess_B', set: 'B', repeat: false };
  return { mode: 'assess_A', set: 'A', repeat: done.includes('A') };
}

function identity(name: string, ctx: StartContext): Pick<SessionCreate, 'display_name' | 'participant_code'> & { learner_id?: string } {
  const typed = name.trim();
  // A learner who really is called "Demo" must not land on the shared sample learner.
  const display = !typed ? ANONYMOUS_NAME : fold(typed) === fold(SAMPLE_NAME) ? `${typed} (reader)` : typed;
  return {
    display_name: display,
    participant_code: looksLikeCode(typed) ? typed : null,
    ...(sameLearner(ctx.remembered, typed) ? { learner_id: ctx.remembered.learnerId } : {}),
  };
}

/** Start screen → POST /sessions body. `level` stays in the contract but is no longer asked: always "other". */
export function toSessionCreate(form: StartForm, ctx: StartContext): SessionCreate {
  const { learner_id, ...who } = identity(form.name, ctx);
  const base: Record<string, unknown> = { ...(ctx.projector ? { projector: true } : {}), ...(learner_id ? { learner_id } : {}) };
  // Chest X-ray is the contract's default and the X-ray body stays byte-identical; CT / MR say so and name the region.
  if (form.modality && form.modality !== 'cxr') Object.assign(base, { modality: form.modality, body_region: MODALITY_DISPLAY[form.modality].region });
  if (form.practice === 'test') {
    const done = sameLearner(ctx.remembered, form.name) ? ctx.remembered.tests : [];
    return { ...who, level: 'other', mode: nextTest(done).mode, settings: base };
  }
  if (form.practice === 'finding') {
    return { ...who, level: 'other', mode: 'drill', settings: { ...base, case_count: form.count, selection: 'adaptive', label: form.finding } };
  }
  // "My weak spots" without enough history quietly becomes a mixed set (the option is disabled in the form anyway).
  const selection = form.practice === 'weak' && weakSpotsReady(ctx.reads) ? 'weak_areas' : 'adaptive';
  return { ...who, level: 'other', mode: 'practice', settings: { ...base, case_count: form.count, selection } };
}

/** "Try a sample set": the curated six films, read as the shared sample learner. Never tied to the remembered learner. */
export function sampleSessionCreate(ctx: Pick<StartContext, 'projector'> = {}): SessionCreate {
  return { display_name: SAMPLE_NAME, level: 'other', participant_code: null, mode: 'practice', settings: ctx.projector ? { projector: true } : {} };
}

export const isSampleName = (name: string | null | undefined) => !!name && fold(name) === fold(SAMPLE_NAME);

/** How a learner is named on a page: the sample learner is "Sample set", never "Demo". */
export function learnerLabel(name: string | null | undefined): string {
  if (isSampleName(name)) return SAMPLE_LABEL;
  if (!name || fold(name) === fold(ANONYMOUS_NAME)) return 'Anonymous reader';
  return name;
}

// ---------- the learner remembered on this device ----------
const LEARNER_KEY = 'bs_learner';
/** Set by the reading-room tutorial when it is finished or skipped (not by this file). */
export const TUTORIAL_KEY = 'bs_tutorial_done';

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === 'string' ? v : null);
const num = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);

export function parseRemembered(raw: string | null): Remembered | null {
  if (!raw) return null;
  try {
    const o: unknown = JSON.parse(raw);
    if (!isObj(o) || typeof o.learnerId !== 'string' || !o.learnerId) return null;
    return { learnerId: o.learnerId, name: str(o.name) ?? '', tests: arr(o.tests).filter((t): t is TestSet => t === 'A' || t === 'B') };
  } catch {
    return null;
  }
}

export function loadRemembered(): Remembered | null {
  try { return parseRemembered(localStorage.getItem(LEARNER_KEY)); } catch { return null; }
}

/** Keeps the tests already taken when the same learner starts again; a different learner starts clean. */
export function remember(learnerId: string, name: string): Remembered {
  const prev = loadRemembered();
  const next: Remembered = { learnerId, name: name.trim(), tests: prev?.learnerId === learnerId ? prev.tests : [] };
  try { localStorage.setItem(LEARNER_KEY, JSON.stringify(next)); } catch { /* storage blocked: this visit still works */ }
  return next;
}

export function forgetLearner() {
  try { localStorage.removeItem(LEARNER_KEY); } catch { /* nothing stored */ }
}

export function markTestDone(learnerId: string, mode: string) {
  const set: TestSet | null = mode === 'assess_A' ? 'A' : mode === 'assess_B' ? 'B' : null;
  const r = loadRemembered();
  if (!set || !r || r.learnerId !== learnerId || r.tests.includes(set)) return;
  try { localStorage.setItem(LEARNER_KEY, JSON.stringify({ ...r, tests: [...r.tests, set] })); } catch { /* storage blocked */ }
}

/** First session in this browser: the reading room opens its tutorial when asked with ?tutorial=1. */
export function needsTutorial(): boolean {
  try { return localStorage.getItem(TUTORIAL_KEY) == null; } catch { return false; }
}

export const readPath = () => (needsTutorial() ? '/read?tutorial=1' : '/read');

/** Scan types the library holds right now (health `cases_by_modality`); an older server has chest films only. */
export function availableModalities(h: { cases_by_modality?: Record<string, number> | null; modalities?: Modality[] | null } | null | undefined): Modality[] {
  const by = h?.cases_by_modality;
  if (by) return MODALITIES.filter((m) => (by[m] ?? 0) > 0);
  if (h?.modalities?.length) return MODALITIES.filter((m) => h.modalities!.includes(m));
  return ['cxr'];
}

/** "Library: 520 chest films with radiologist outlines." or, with volumes, "…, 12 abdominal CT and 6 brain MRI studies, with expert outlines." */
export function libraryLine(h: Health): string {
  const by = h.cases_by_modality;
  const ct = by?.ct ?? 0;
  const mr = by?.mr ?? 0;
  if (!by || (!ct && !mr)) return `Library: ${h.cases.toLocaleString()} chest films with radiologist outlines.`;
  const cxr = by.cxr ?? Math.max(0, h.cases - ct - mr);
  const vols = [ct ? `${ct.toLocaleString()} abdominal CT` : '', mr ? `${mr.toLocaleString()} brain MRI` : ''].filter(Boolean).join(' and ');
  return `Library: ${cxr.toLocaleString()} chest films, ${vols} ${ct + mr === 1 ? 'study' : 'studies'}, with expert outlines.`;
}

// ---------- the scan type remembered on this device ----------
const MODALITY_KEY = 'bs_modality';
export function loadModality(): Modality {
  try { const v = localStorage.getItem(MODALITY_KEY); return isModality(v) ? v : 'cxr'; } catch { return 'cxr'; }
}
export function saveModality(m: Modality) {
  try { localStorage.setItem(MODALITY_KEY, m); } catch { /* storage blocked */ }
}

// Until the reading log counts reads per scan type (dashboard `n_by_modality`), CT / MR reads are counted on this
// device: the studies of every CT / MR set started here. An estimate, and the start screen says so.
const LOCAL_READS_KEY = 'bs_reads_by_modality';
export type LocalReads = Partial<Record<Modality, number>>;
export function parseLocalReads(raw: string | null): LocalReads {
  if (!raw) return {};
  try {
    const o: unknown = JSON.parse(raw);
    if (!isObj(o)) return {};
    return Object.fromEntries(Object.entries(o).filter(([k, v]) => isModality(k) && num(v) && v >= 0).map(([k, v]) => [k, Math.floor(v as number)]));
  } catch {
    return {};
  }
}
export function loadLocalReads(): LocalReads {
  try { return parseLocalReads(localStorage.getItem(LOCAL_READS_KEY)); } catch { return {}; }
}
export function addLocalReads(m: Modality, n: number) {
  const cur = loadLocalReads();
  try { localStorage.setItem(LOCAL_READS_KEY, JSON.stringify({ ...cur, [m]: (cur[m] ?? 0) + n })); } catch { /* storage blocked */ }
}

/** Reads of one scan type: the server's per-modality count when it sends one; an X-ray log without one is all
 *  X-ray (every case before the volumetric round was a chest film); CT / MR fall back to the local estimate. */
export function readsFor(dash: unknown, modality: Modality, local: LocalReads): { n: number; estimated: boolean } {
  const d = isObj(dash) ? dash : {};
  const by = isObj(d.n_by_modality) ? d.n_by_modality : null;
  if (by && num(by[modality])) return { n: by[modality] as number, estimated: false };
  if (by) return { n: 0, estimated: false };
  if (modality === 'cxr') return { n: num(d.n_attempts) ? (d.n_attempts as number) : 0, estimated: false };
  return { n: local[modality] ?? 0, estimated: true };
}

// ---------- stored result for one read (GET /attempts/{aid}/result) ----------
export type ReviewMark = { mark_id: string; x: number; y: number; label: string; confidence: number };
export type ReviewFilm = {
  case_id: string; image_url: string | null; width: number | null; height: number | null;
  /** The NextCase-shaped `volume` block (shape, spacing, window, data_url) when the read was a CT / MR; passed through as sent. */
  volume: Record<string, unknown> | null;
};
export type AttemptReview = {
  result: SubmitResult;
  /** Which film it was, when the server says so. */
  film: ReviewFilm | null;
  /** cxr | ct | mr, from the result, the reveal or the case block; null on an older server (an X-ray). */
  modality: Modality | null;
  /** The '___ by ___' block, when the server sends one (reveal.provenance or case.provenance). */
  provenance: unknown;
  /** Where the learner marked; null when the server does not send the submitted read. */
  marks: ReviewMark[] | null;
  patterns: { label: string; confidence: number }[];
  declaredNormal: boolean | null;
};

function marksOf(v: unknown): ReviewMark[] | null {
  if (!Array.isArray(v)) return null;
  return v.flatMap((m) => (isObj(m) && num(m.x) && num(m.y)
    ? [{ mark_id: str(m.mark_id) ?? '?', x: m.x, y: m.y, label: str(m.label) ?? 'not_sure', confidence: num(m.confidence) ? m.confidence : 3 }]
    : []));
}

/** Throws on a payload that is not a SubmitResult; reads the optional `case` and `submitted` blocks when present. */
export function guardAttemptResult(v: unknown): AttemptReview {
  if (!isObj(v) || !isObj(v.reveal) || !Array.isArray(v.reveal.findings) || !Array.isArray(v.outcomes)) throw new Error('malformed result');
  const reveal = v.reveal;
  const result = {
    ...v,
    score: num(v.score) ? v.score : 0,
    success: v.success === true,
    reveal: { ...reveal, marks: arr(reveal.marks), arrows: arr(reveal.arrows), search: isObj(reveal.search) ? reveal.search : { lung_coverage_pct: 0, unvisited_review_areas: [] } },
    facts_card: isObj(v.facts_card) && typeof v.facts_card.headline === 'string' ? { headline: v.facts_card.headline, lines: arr(v.facts_card.lines).filter((l): l is string => typeof l === 'string') } : { headline: '', lines: [] },
  } as unknown as SubmitResult;
  const c = isObj(v.case) ? v.case : null;
  const sub = isObj(v.submitted) ? v.submitted : null;
  const mod = [v.modality, reveal.modality, c?.modality].find(isModality) ?? null;
  return {
    result,
    modality: mod,
    provenance: isObj(reveal.provenance) ? reveal.provenance : isObj(c?.provenance) ? c.provenance : null,
    film: c && typeof c.case_id === 'string' && c.case_id
      ? { case_id: c.case_id, image_url: str(c.image_url), width: num(c.width) ? c.width : null, height: num(c.height) ? c.height : null, volume: isObj(c.volume) ? c.volume : null }
      : null,
    marks: marksOf(sub?.marks) ?? marksOf(v.marks),
    patterns: arr(sub?.patterns ?? v.patterns).flatMap((p) => (isObj(p) && typeof p.label === 'string' ? [{ label: p.label, confidence: num(p.confidence) ? p.confidence : 3 }] : [])),
    declaredNormal: typeof (sub?.declared_normal ?? v.declared_normal) === 'boolean' ? ((sub?.declared_normal ?? v.declared_normal) as boolean) : null,
  };
}

export const fetchAttemptResult = async (aid: string) => guardAttemptResult(await request<unknown>(`/attempts/${encodeURIComponent(aid)}/result`));
