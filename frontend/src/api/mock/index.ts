// In-browser mock of the §13 API, serving SYNTHETIC cases (drawn shapes). Loaded lazily, only in mock mode,
// so ground truth for these fixtures never ships in the real bundle's code path.
import type {
  AssessmentSummary, AttemptSubmit, DebriefResponse, HintRequest, NextCase, SessionCreate, SubmitResult,
} from '../../types/contracts';
import { zoneDisplay } from '../labels';
import { MOCK_CASES } from './cases';
import { dwellMs, scoreAttempt, templateDebrief } from './scoring';
import type { MockCase } from './types';

type Session = { id: string; learner: string; mode: SessionCreate['mode']; order: string[]; pos: number; attempts: string[] };
type Attempt = {
  id: string; sid: string; caseId: string; hints: number; asks: number; polls: number;
  result?: SubmitResult; recorded?: boolean; submit?: AttemptSubmit;
};

const sessions = new Map<string, Session>();
const attempts = new Map<string, Attempt>();
let seq = 0;
const uid = (p: string) => `${p}_mock_${++seq}`;
const byId = (id: string): MockCase => MOCK_CASES.find((c) => c.case_id === id)!;

const PRACTICE_ORDER = ['syn_005', 'syn_002', 'syn_008', 'syn_003', 'syn_006', 'syn_001', 'syn_009', 'syn_004', 'syn_007', 'syn_010'];
const ASSESS_ORDER = ['syn_001', 'syn_008', 'syn_004', 'syn_009'];

class MockHttpError extends Error {
  status: number;
  constructor(status: number, msg: string) { super(`${status} ${msg}`); this.status = status; }
}

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function mockRequest(method: string, path: string, body: unknown): Promise<unknown> {
  await delay(60);
  const p = path.split('?')[0];
  let m: RegExpMatchArray | null;

  if (method === 'GET' && p === '/health') return { ok: true, offline: true, cases: MOCK_CASES.length, version: 'mock-synthetic' };

  if (method === 'POST' && p === '/sessions') {
    const b = body as SessionCreate;
    let order = PRACTICE_ORDER;
    if (b.mode === 'assess_A' || b.mode === 'assess_B') order = ASSESS_ORDER;
    if (b.mode === 'drill') {
      const label = String((b.settings as { label?: string } | undefined)?.label ?? 'effusion');
      const hits = PRACTICE_ORDER.filter((id) => byId(id).findings.some((f) => f.label === label));
      const normals = PRACTICE_ORDER.filter((id) => byId(id).is_normal);
      order = [];
      for (let i = 0; i < Math.max(hits.length, normals.length); i++) {
        if (hits[i]) order.push(hits[i]);
        if (normals[i]) order.push(normals[i]);
      }
    }
    const s: Session = { id: uid('ses'), learner: uid('lrn'), mode: b.mode, order, pos: 0, attempts: [] };
    sessions.set(s.id, s);
    return { session_id: s.id, learner_id: s.learner, mode: s.mode };
  }

  if (method === 'GET' && (m = p.match(/^\/sessions\/([^/]+)\/next$/))) {
    const s = need(sessions.get(m[1]));
    const assess = s.mode.startsWith('assess');
    if (s.pos >= s.order.length) {
      if (!assess) s.pos = 0; // practice loops over the small synthetic bank
      else return { attempt_id: '', case: { case_id: '', image_url: '', width: 0, height: 0 }, index: s.pos, total: s.order.length, done: true } satisfies NextCase;
    }
    const c = byId(s.order[s.pos++]);
    const a: Attempt = { id: uid('att'), sid: s.id, caseId: c.case_id, hints: 0, asks: 0, polls: 0 };
    attempts.set(a.id, a);
    s.attempts.push(a.id);
    return {
      attempt_id: a.id,
      case: { case_id: c.case_id, image_url: `/mock/${c.case_id}.png`, width: c.width, height: c.height },
      index: s.attempts.length, total: assess ? s.order.length : null, hints_enabled: !assess, done: false,
    } satisfies NextCase;
  }

  if (method === 'POST' && (m = p.match(/^\/attempts\/([^/]+)\/hint$/))) {
    const a = need(attempts.get(m[1]));
    const s = need(sessions.get(a.sid));
    if (s.mode.startsWith('assess')) throw new MockHttpError(403, 'hints are disabled in assessment');
    if (a.hints >= 3) throw new MockHttpError(409, 'no hints left');
    a.hints++;
    const c = byId(a.caseId);
    const req = body as HintRequest;
    let text: string;
    if (a.hints === 1) {
      const areas = ['right_apex', 'left_apex', 'retrocardiac', 'right_costophrenic_angle', 'left_costophrenic_angle'];
      const pad = 0;
      const unvisited = areas.filter((z) => dwellMs(req.telemetry, zoneBox(z, c), pad) < 300);
      text = unvisited.length ? `You haven't looked at: ${unvisited.map(zoneDisplay).join(', ')}.` : 'Compare each region with the same region on the other side.';
    } else {
      const f = c.findings.find((x) => x.kind === 'focal' && !req.marks.some((mk) => mk.x >= x.bbox[0] - 10 && mk.x <= x.bbox[2] + 10 && mk.y >= x.bbox[1] - 10 && mk.y <= x.bbox[3] + 10));
      if (a.hints === 2) text = c.is_normal || !f ? 'Asymmetry is the clue: compare left and right zone by zone.' : `Look again at the patient's ${f.side}: ${zoneDisplay(f.primary_zone)}.`;
      else text = c.is_normal || !f ? 'If every review area is clear, normal is a valid call.' : 'Look for an edge or density that is not on the other side.';
    }
    return { level: a.hints, text, remaining: 3 - a.hints };
  }

  if (method === 'POST' && (m = p.match(/^\/attempts\/([^/]+)\/submit$/))) {
    const a = need(attempts.get(m[1]));
    if (a.result || a.recorded) throw new MockHttpError(409, 'already submitted');
    const s = need(sessions.get(a.sid));
    a.submit = body as AttemptSubmit;
    if (s.mode.startsWith('assess')) {
      a.recorded = true;
      return { recorded: true, index: s.pos, total: s.order.length };
    }
    a.result = scoreAttempt(byId(a.caseId), a.submit);
    return a.result;
  }

  if (method === 'GET' && (m = p.match(/^\/attempts\/([^/]+)\/debrief$/))) {
    const a = need(attempts.get(m[1]));
    if (!a.result) throw new MockHttpError(409, 'not submitted');
    a.polls++;
    if (a.polls < 3) return { status: 'pending' } satisfies DebriefResponse;
    return { status: 'ready', debrief: templateDebrief(a.result), source: 'template', provenance: 'ai_draft', latency_ms: 4 } satisfies DebriefResponse;
  }

  if (method === 'POST' && (m = p.match(/^\/attempts\/([^/]+)\/ask$/))) {
    const a = need(attempts.get(m[1]));
    if (!a.result) throw new MockHttpError(409, 'not submitted');
    if (a.asks >= 3) throw new MockHttpError(409, 'no questions left');
    a.asks++;
    return { answer: 'The tutor is offline in this synthetic demo. Use the outlines and the facts card above to compare your read with the expert marks.', remaining: 3 - a.asks, source: 'template' };
  }

  if (method === 'POST' && (m = p.match(/^\/attempts\/([^/]+)\/flag$/))) return { ok: true };

  if (method === 'GET' && (m = p.match(/^\/sessions\/([^/]+)\/summary$/))) {
    const s = need(sessions.get(m[1]));
    const scored = s.attempts.map((id) => attempts.get(id)!).filter((a) => a.submit).map((a) => ({ a, r: scoreAttempt(byId(a.caseId), a.submit!) }));
    const abn = scored.filter((x) => !x.r.reveal.is_normal);
    const nor = scored.filter((x) => x.r.reveal.is_normal);
    const mix: Record<string, number> = {};
    for (const x of scored) for (const o of x.r.outcomes) {
      const k = o.result.startsWith('missed_') ? o.result.slice(7) : o.result === 'mislabeled' ? 'interpretation' : o.result === 'false_positive' ? 'overcall' : null;
      if (k) mix[k] = (mix[k] ?? 0) + 1;
    }
    const focalTotal = abn.reduce((n, x) => n + x.r.reveal.findings.filter((f) => f.kind === 'focal').length, 0);
    const localized = abn.reduce((n, x) => n + x.r.reveal.findings.filter((f) => f.result === 'found' || f.result === 'mislabeled').length, 0);
    return {
      session_id: s.id, mode: s.mode, n_cases: scored.length,
      sensitivity: abn.length ? abn.filter((x) => x.r.reveal.marks.some((mk) => mk.result === 'true_positive')).length / abn.length : null,
      specificity: nor.length ? nor.filter((x) => x.r.success).length / nor.length : null,
      localization_fraction: focalTotal ? localized / focalTotal : null,
      false_positives_per_image: scored.length ? scored.reduce((n, x) => n + x.r.reveal.marks.filter((mk) => mk.result === 'false_positive').length, 0) / scored.length : 0,
      miss_type_mix: mix,
      score_mean: scored.length ? scored.reduce((n, x) => n + x.r.score, 0) / scored.length : 0,
    } satisfies AssessmentSummary;
  }

  if (method === 'POST' && p === '/sus') {
    const a = (body as { answers: number[] }).answers;
    return { score: a.reduce((t, v, i) => t + (i % 2 === 0 ? v - 1 : 5 - v), 0) * 2.5 };
  }

  if (method === 'GET' && p === '/about') throw new MockHttpError(404, 'about is static in mock mode');
  throw new MockHttpError(404, `mock has no route ${method} ${p}`);
}

function zoneBox(z: string, c: MockCase): [number, number, number, number] {
  const w = c.width;
  const h = c.height;
  if (z === 'right_apex') return [0.08 * w, 0.08 * h, 0.48 * w, 0.3 * h];
  if (z === 'left_apex') return [0.52 * w, 0.08 * h, 0.92 * w, 0.3 * h];
  if (z === 'retrocardiac') return [0.5 * w, 0.55 * h, 0.7 * w, 0.85 * h];
  if (z === 'right_costophrenic_angle') return [0.08 * w, 0.75 * h, 0.3 * w, 0.95 * h];
  return [0.7 * w, 0.75 * h, 0.92 * w, 0.95 * h];
}

function need<T>(v: T | undefined): T {
  if (v === undefined) throw new MockHttpError(404, 'not found');
  return v;
}
