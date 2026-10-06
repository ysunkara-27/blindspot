// Runtime guards for GET /api/reference (round 3). The backend lands in parallel, so every field is optional here:
// whatever is missing renders as an empty state instead of breaking the drawer.
export type Pt = [number, number];
export type ReferenceFilm = { case_id: string; image_url: string; width: number; height: number };
export type ReferenceExample = ReferenceFilm & {
  finding: { finding_id: string; polygon: Pt[] | null; bbox: [number, number, number, number] | null; relative_location: string; side: string | null } | null;
};
export type ReferenceLabel = {
  label: string;
  display: string;
  kind: 'focal' | 'pattern';
  one_liner: string;
  key_signs: string[];
  mimics: string[];
  commonly_confused_with: string[];
  search_tip: string;
  radiopaedia_url: string | null;
  review_status: string;
  examples: ReferenceExample[];
};
export type Reference = { labels: ReferenceLabel[]; normal_examples: ReferenceFilm[] };

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const str = (v: unknown): string => (typeof v === 'string' ? v.trim() : '');
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.map(str).filter(Boolean) : []);
const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
const isPt = (v: unknown): v is Pt => Array.isArray(v) && v.length >= 2 && typeof v[0] === 'number' && typeof v[1] === 'number';

function film(v: unknown): ReferenceFilm | null {
  if (!isObj(v)) return null;
  const image_url = str(v.image_url);
  const width = num(v.width);
  const height = num(v.height);
  if (!image_url || width <= 0 || height <= 0) return null;
  return { case_id: str(v.case_id), image_url, width, height };
}

function example(v: unknown): ReferenceExample | null {
  const f = film(v);
  if (!f || !isObj(v)) return null;
  const g = isObj(v.finding) ? v.finding : null;
  if (!g) return { ...f, finding: null };
  const polygon = Array.isArray(g.polygon) ? g.polygon.filter(isPt).map((p) => [p[0], p[1]] as Pt) : [];
  const b = Array.isArray(g.bbox) && g.bbox.length >= 4 && g.bbox.every((n) => typeof n === 'number') ? (g.bbox.slice(0, 4) as [number, number, number, number]) : null;
  return {
    ...f,
    finding: {
      finding_id: str(g.finding_id),
      polygon: polygon.length >= 3 ? polygon : null,
      bbox: b,
      relative_location: str(g.relative_location),
      side: str(g.side) || null,
    },
  };
}

/** Only a plain https link is rendered as "Read more on Radiopaedia" (link-only; nothing is fetched from it). */
export function safeExternalUrl(v: unknown): string | null {
  const u = str(v);
  if (!u) return null;
  try {
    const p = new URL(u);
    return p.protocol === 'https:' ? p.toString() : null;
  } catch {
    return null;
  }
}

function label(v: unknown): ReferenceLabel | null {
  if (!isObj(v)) return null;
  const id = str(v.label ?? v.id);
  if (!id) return null;
  return {
    label: id,
    display: str(v.display ?? v.display_name) || id.replace(/_/g, ' '),
    kind: v.kind === 'pattern' ? 'pattern' : 'focal',
    one_liner: str(v.one_liner),
    key_signs: strs(v.key_signs),
    mimics: strs(v.mimics),
    commonly_confused_with: strs(v.commonly_confused_with),
    search_tip: str(v.search_tip),
    radiopaedia_url: safeExternalUrl(v.radiopaedia_url),
    review_status: str(v.review_status ?? (isObj(v.review) ? v.review.status : '')),
    examples: Array.isArray(v.examples) ? v.examples.map(example).filter((e): e is ReferenceExample => !!e) : [],
  };
}

export function guardReference(v: unknown): Reference {
  if (!isObj(v)) return { labels: [], normal_examples: [] };
  return {
    labels: Array.isArray(v.labels) ? v.labels.map(label).filter((l): l is ReferenceLabel => !!l) : [],
    normal_examples: Array.isArray(v.normal_examples) ? v.normal_examples.map(film).filter((f): f is ReferenceFilm => !!f) : [],
  };
}

/** UI wording: the lens is called the magnifier everywhere (teaching cards written earlier still say "loupe"). */
export function uiTerms(text: string): string {
  return text.replace(/\bloupe\b/g, 'magnifier').replace(/\bLoupe\b/g, 'Magnifier');
}
