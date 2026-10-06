// Review queue items (GET /api/review/items). Source: backend/app/routes/review.py. Guarded at runtime.
import type { DebriefFacts, DebriefOutput, TeachingCard } from '../types/contracts';

export type LearnerAnswer = {
  marks: { mark_id: string; x: number; y: number; label: string; confidence: number }[];
  patterns: { label: string; confidence: number }[];
  declared_normal: boolean;
};

/** Expert geometry carried by the review item itself (reviewer-gated route), so /review needs no dev route. */
export type ItemFinding = {
  finding_id: string; label: string | null; kind: 'focal' | 'pattern'; polygon: [number, number][] | null;
  bbox: [number, number, number, number]; centroid: [number, number] | null;
};
export type ItemGeometry = { width: number; height: number; findings: ItemFinding[] };

export type DebriefItem = {
  item_id: string;
  origin: 'live' | 'curated' | string;
  attempt_id: string | null;
  case_id: string;
  image_url: string | null;
  learner: LearnerAnswer;
  facts: DebriefFacts | null;
  debrief: DebriefOutput | null;
  source: string | null;
  provenance: string | null;
  validator_ok: boolean | null;
  flags: number;
  flag_comments: string | null;
  behaviour: string | null;
  geometry: ItemGeometry | null;
};

export type CardItem = { item_id: string; card: TeachingCard };

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === 'string' ? v : null);
const items = (v: unknown): unknown[] => (isObj(v) && Array.isArray(v.items) ? v.items : []);

function learner(v: unknown): LearnerAnswer {
  const o = isObj(v) ? v : {};
  const marks = (Array.isArray(o.marks) ? o.marks : []).flatMap((m) =>
    isObj(m) && typeof m.x === 'number' && typeof m.y === 'number'
      ? [{ mark_id: str(m.mark_id) ?? '?', x: m.x, y: m.y, label: str(m.label) ?? 'not_sure', confidence: typeof m.confidence === 'number' ? m.confidence : 3 }]
      : [],
  );
  const patterns = (Array.isArray(o.patterns) ? o.patterns : []).flatMap((p) =>
    isObj(p) && typeof p.label === 'string' ? [{ label: p.label, confidence: typeof p.confidence === 'number' ? p.confidence : 3 }] : [],
  );
  return { marks, patterns, declared_normal: o.declared_normal === true };
}

const num4 = (v: unknown): v is [number, number, number, number] => Array.isArray(v) && v.length === 4 && v.every((x) => typeof x === 'number');
const pt = (v: unknown): v is [number, number] => Array.isArray(v) && v.length >= 2 && typeof v[0] === 'number' && typeof v[1] === 'number';

function geometry(it: Obj): ItemGeometry | null {
  const src = Array.isArray(it.findings) ? it.findings : isObj(it.geometry) && Array.isArray(it.geometry.findings) ? it.geometry.findings : null;
  if (!src) return null;
  const g = isObj(it.geometry) ? it.geometry : it;
  const findings = src.flatMap((f): ItemFinding[] => {
    if (!isObj(f) || typeof f.finding_id !== 'string') return [];
    const geo = isObj(f.geometry) ? f.geometry : f;
    if (!num4(geo.bbox)) return [];
    const poly = Array.isArray(geo.polygon) ? geo.polygon.filter(pt).map((p) => [p[0], p[1]] as [number, number]) : null;
    return [{
      finding_id: f.finding_id,
      label: str(f.label),
      kind: f.kind === 'pattern' ? 'pattern' : 'focal',
      polygon: poly && poly.length >= 3 ? poly : null,
      bbox: geo.bbox,
      centroid: pt(f.centroid) ? [f.centroid[0], f.centroid[1]] : null,
    }];
  });
  const width = typeof g.width === 'number' ? g.width : typeof it.width === 'number' ? it.width : 1024;
  const height = typeof g.height === 'number' ? g.height : typeof it.height === 'number' ? it.height : 1024;
  return { width, height, findings };
}

export function guardDebriefItems(v: unknown): DebriefItem[] {
  return items(v).flatMap((it) => {
    if (!isObj(it) || typeof it.item_id !== 'string') return [];
    const facts = isObj(it.facts) && isObj(it.facts.case) ? (it.facts as unknown as DebriefFacts) : null;
    const debrief = isObj(it.debrief) && typeof it.debrief.headline === 'string' ? (it.debrief as unknown as DebriefOutput) : null;
    const caseId = str(it.case_id) ?? facts?.case.case_id ?? '';
    const val = isObj(it.validator) ? it.validator : null;
    return [{
      item_id: it.item_id,
      origin: str(it.origin) ?? 'live',
      attempt_id: str(it.attempt_id),
      case_id: caseId,
      image_url: str(it.image_url),
      learner: learner(it.learner),
      facts,
      debrief,
      source: str(it.source),
      provenance: str(it.provenance),
      validator_ok: val && typeof val.ok === 'boolean' ? val.ok : null,
      flags: typeof it.flags === 'number' ? it.flags : 0,
      flag_comments: str(it.flag_comments),
      behaviour: str(it.behaviour),
      geometry: geometry(it),
    }];
  });
}

export function guardCardItems(v: unknown): CardItem[] {
  return items(v).flatMap((it) =>
    isObj(it) && typeof it.item_id === 'string' && isObj(it.card) && typeof it.card.label === 'string'
      ? [{ item_id: it.item_id, card: it.card as unknown as TeachingCard }]
      : [],
  );
}

export const STATUS_RANK = { ai_draft: 0, student_reviewed: 1, radiologist_reviewed: 2 } as const;
export type CardStatus = keyof typeof STATUS_RANK;
export const STATUS_TEXT: Record<CardStatus, string> = {
  ai_draft: 'AI draft',
  student_reviewed: 'Student reviewed',
  radiologist_reviewed: 'Radiologist reviewed',
};

export const ROLES = ['Medical student', 'Radiologist', 'Radiology resident', 'Physician', 'Other'] as const;

/** Approval status for a reviewer's role; never downgrades a card. */
export function approvalStatus(role: string, current: CardStatus): CardStatus {
  const byRole: CardStatus = role === 'Radiologist' ? 'radiologist_reviewed' : 'student_reviewed';
  return STATUS_RANK[byRole] >= STATUS_RANK[current] ? byRole : current;
}

export const CARD_LIST_FIELDS = ['key_signs', 'where_it_hides', 'mimics', 'commonly_confused_with'] as const;
export const CARD_TEXT_FIELDS = ['display_name', 'one_liner', 'search_tip', 'radiopaedia_url'] as const;
export type CardField = (typeof CARD_LIST_FIELDS)[number] | (typeof CARD_TEXT_FIELDS)[number];

/** Fields the reviewer changed, in the shape the backend writes (lists as string[], empty URL as null). */
export function cardEdits(orig: TeachingCard, draft: Record<CardField, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of CARD_LIST_FIELDS) {
    const next = draft[f].split('\n').map((x) => x.trim()).filter(Boolean);
    const prev = orig[f] as string[];
    if (next.length !== prev.length || next.some((x, i) => x !== prev[i])) out[f] = next;
  }
  for (const f of CARD_TEXT_FIELDS) {
    const next = draft[f].trim();
    const prev = (orig[f] ?? '') as string;
    if (next !== prev) out[f] = f === 'radiopaedia_url' && !next ? null : next;
  }
  return out;
}

export function cardDraft(c: TeachingCard): Record<CardField, string> {
  return {
    display_name: c.display_name,
    one_liner: c.one_liner,
    search_tip: c.search_tip,
    radiopaedia_url: c.radiopaedia_url ?? '',
    key_signs: c.key_signs.join('\n'),
    where_it_hides: c.where_it_hides.join('\n'),
    mimics: c.mimics.join('\n'),
    commonly_confused_with: c.commonly_confused_with.join('\n'),
  };
}
