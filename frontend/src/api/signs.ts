// GET /api/signs (round 5): the generic sign schematics — small line drawings (SVG) of the signs the teaching cards
// and the debrief name ("visceral pleural line", "meniscus", "bat-wing"…), each with a one-paragraph description,
// the finding labels it belongs to (empty = not graded in Blindspot yet) and a Radiopaedia link (link only).
// Nothing here is about the case being read, so it may load before submit. Rendered inline, so the markup is
// guarded here: only an <svg> from our own API, with no scripts, event handlers, foreign objects or external links.
import { request } from './client';
import { safeExternalUrl } from '../reference/guard';
import type { SignSchematic } from '../types/contracts';

export type { SignSchematic };

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const str = (v: unknown): string => (typeof v === 'string' ? v.trim() : '');

/** The schematic's markup is rendered with dangerouslySetInnerHTML, so it must be a plain drawing: one <svg> root,
 *  no script, handler, foreign object, embedded page or external reference. Anything else is dropped (null). */
export function safeSvg(v: unknown): string | null {
  const s = str(v);
  if (!/^<svg[\s>]/i.test(s) || !/<\/svg>\s*$/i.test(s)) return null;
  if (s.length > 20_000) return null;
  if (/<\s*(script|foreignobject|iframe|object|embed|image|a|use|style|animate\w*|set)\b/i.test(s)) return null;
  if (/\son[a-z]+\s*=/i.test(s)) return null;
  if (/(xlink:)?href\s*=/i.test(s)) return null;
  if (/javascript:|data:|url\(/i.test(s)) return null;
  if (/<!--|<!\[CDATA\[|<\?/.test(s)) return null;
  return s;
}

export function guardSignSchematic(v: unknown): SignSchematic | null {
  if (!isObj(v)) return null;
  const id = str(v.id);
  const name = str(v.name);
  const svg = safeSvg(v.svg);
  if (!id || !name || !svg) return null;
  const labels = Array.isArray(v.labels) ? v.labels.map(str).filter(Boolean) : [];
  const modality = str(v.modality) || null;
  return {
    id, name, svg, labels, modality,
    description: str(v.description),
    radiopaedia_url: safeExternalUrl(v.radiopaedia_url),
    review_status: str(v.review_status) || 'ai_draft',
  };
}

export function guardSigns(v: unknown): SignSchematic[] {
  const list = Array.isArray(v) ? v : isObj(v) && Array.isArray(v.signs) ? v.signs : [];
  const seen = new Set<string>();
  const out: SignSchematic[] = [];
  for (const x of list) {
    const s = guardSignSchematic(x);
    if (s && !seen.has(s.id)) { seen.add(s.id); out.push(s); }
  }
  return out;
}

export const fetchSigns = async (): Promise<SignSchematic[]> => guardSigns(await request<unknown>('/signs'));

/** The schematics for one finding type, the on-film ones (`first`, schematic ids) listed first. */
export function signsForLabel(all: SignSchematic[], label: string, first: string[] = []): SignSchematic[] {
  const mine = all.filter((s) => s.labels.includes(label) || first.includes(s.id));
  const rank = (s: SignSchematic) => { const i = first.indexOf(s.id); return i < 0 ? first.length : i; };
  return [...mine].sort((a, b) => rank(a) - rank(b));
}
