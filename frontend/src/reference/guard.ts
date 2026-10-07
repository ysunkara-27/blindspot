// Runtime guards for GET /api/reference (round 3; volumetric fields round 4). The backend lands in parallel, so
// every field is optional here: whatever is missing renders as an empty state instead of breaking the drawer.
import { FOCAL_LABELS_BY_MODALITY, isModality } from '../api/labels';
import type { Modality } from '../types/contracts';

export type Pt = [number, number];
/** A CT / MR example: the voxels and the label mask (both gzipped), decoded in the browser; `slice` is the axial
 *  slice through the finding's longest diameter (`measure.slice`), the one the card shows first. */
export type ReferenceVolume = {
  volume_url: string;
  mask_url: string;
  shape: [number, number, number];
  spacing: [number, number, number];
  window: { wc: number; ww: number };
  slice: number;
  /** Mask values of the finding (organs are other values); empty = outline every non-zero voxel. */
  label_values: number[];
};
export type ReferenceFilm = { case_id: string; image_url: string; width: number; height: number; modality: Modality; volume: ReferenceVolume | null; provenance: unknown };
export type ReferenceExample = ReferenceFilm & {
  finding: { finding_id: string; polygon: Pt[] | null; bbox: [number, number, number, number] | null; relative_location: string; side: string | null; slice_range: [number, number] | null } | null;
};
export type ReferenceLabel = {
  label: string;
  display: string;
  kind: 'focal' | 'pattern';
  /** The scan type this finding is read on (from the payload, else the taxonomy's per-modality lists). */
  modality: Modality;
  one_liner: string;
  key_signs: string[];
  mimics: string[];
  commonly_confused_with: string[];
  search_tip: string;
  radiopaedia_url: string | null;
  review_status: string;
  examples: ReferenceExample[];
  /** Round 5: ids of the sign schematics (GET /api/signs) that belong to this finding type. */
  signs: string[];
};
export type Reference = { labels: ReferenceLabel[]; normal_examples: ReferenceFilm[] };

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const str = (v: unknown): string => (typeof v === 'string' ? v.trim() : '');
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.map(str).filter(Boolean) : []);
const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0);
const isPt = (v: unknown): v is Pt => Array.isArray(v) && v.length >= 2 && typeof v[0] === 'number' && typeof v[1] === 'number';

const triple = (v: unknown): [number, number, number] | null =>
  Array.isArray(v) && v.length >= 3 && v.slice(0, 3).every((n) => typeof n === 'number' && Number.isFinite(n) && n > 0) ? [v[0], v[1], v[2]] : null;

/** The volume block of a CT / MR example, when it is complete enough to render a slice. */
export function volumeOf(v: Obj, measureSlice: number | null): ReferenceVolume | null {
  const volume_url = str(v.volume_url);
  const mask_url = str(v.mask_url);
  const shape = triple(v.shape);
  if (!volume_url || !mask_url || !shape) return null;
  const spacing = triple(v.spacing) ?? [1, 1, 1];
  const w = isObj(v.window) ? v.window : {};
  const window = { wc: typeof w.wc === 'number' ? w.wc : 0, ww: typeof w.ww === 'number' && w.ww > 0 ? w.ww : 1000 };
  const mid = Math.floor(shape[0] / 2);
  const slice = measureSlice != null ? Math.min(shape[0] - 1, Math.max(0, Math.round(measureSlice))) : mid;
  const label_values = Array.isArray(v.label_values) ? v.label_values.filter((x): x is number => typeof x === 'number') : [];
  return { volume_url, mask_url, shape, spacing, window, slice, label_values };
}

function film(v: unknown): ReferenceFilm | null {
  if (!isObj(v)) return null;
  const image_url = str(v.image_url);
  const width = num(v.width);
  const height = num(v.height);
  const g = isObj(v.finding) ? v.finding : null;
  const m = isObj(g?.measure) ? g.measure : null;
  const volume = volumeOf(v, typeof m?.slice === 'number' ? m.slice : null);
  const modality: Modality = isModality(v.modality) ? v.modality : volume ? 'ct' : 'cxr';
  // An X-ray needs its image; a volume example can stand without a preview image.
  if ((!image_url || width <= 0 || height <= 0) && !volume) return null;
  return { case_id: str(v.case_id), image_url, width, height, modality, volume, provenance: isObj(v.provenance) ? v.provenance : null };
}

function example(v: unknown): ReferenceExample | null {
  const f = film(v);
  if (!f || !isObj(v)) return null;
  const g = isObj(v.finding) ? v.finding : null;
  if (!g) return { ...f, finding: null };
  const polygon = Array.isArray(g.polygon) ? g.polygon.filter(isPt).map((p) => [p[0], p[1]] as Pt) : [];
  const b = Array.isArray(g.bbox) && g.bbox.length >= 4 && g.bbox.every((n) => typeof n === 'number') ? (g.bbox.slice(0, 4) as [number, number, number, number]) : null;
  const sr = Array.isArray(g.slice_range) && g.slice_range.length >= 2 && typeof g.slice_range[0] === 'number' && typeof g.slice_range[1] === 'number' ? ([g.slice_range[0], g.slice_range[1]] as [number, number]) : null;
  if (f.volume && !f.volume.label_values.length && Array.isArray(g.label_values)) f.volume.label_values = g.label_values.filter((x): x is number => typeof x === 'number');
  return {
    ...f,
    finding: {
      finding_id: str(g.finding_id),
      polygon: polygon.length >= 3 ? polygon : null,
      bbox: b,
      relative_location: str(g.relative_location),
      side: str(g.side) || null,
      slice_range: sr,
    },
  };
}

/** Which scan type a finding is read on, from the taxonomy's per-modality lists (X-ray when unknown). */
export function modalityOfLabel(id: string): Modality {
  for (const m of ['ct', 'mr'] as const) if (FOCAL_LABELS_BY_MODALITY[m].some((l) => l.id === id)) return m;
  return 'cxr';
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
    modality: isModality(v.modality) ? v.modality : modalityOfLabel(id),
    one_liner: str(v.one_liner),
    key_signs: strs(v.key_signs),
    mimics: strs(v.mimics),
    commonly_confused_with: strs(v.commonly_confused_with),
    search_tip: str(v.search_tip),
    radiopaedia_url: safeExternalUrl(v.radiopaedia_url),
    review_status: str(v.review_status ?? (isObj(v.review) ? v.review.status : '')),
    examples: Array.isArray(v.examples) ? v.examples.map(example).filter((e): e is ReferenceExample => !!e) : [],
    signs: strs(v.signs),
  };
}

/** GET /api/reference/{label}: one entry of `labels[]` (round 5: with its `signs`). */
export const guardReferenceLabel = (v: unknown): ReferenceLabel | null => label(v);

/** The example films a debrief row shows (round 5): ones with an outline to draw (polygon, bbox or a volume),
 *  distinct cases, never the case being read, up to `n`. Falls back to any example when none has an outline. */
export function pickExamples(examples: ReferenceExample[], n = 2, excludeCaseId: string | null = null): ReferenceExample[] {
  const out: ReferenceExample[] = [];
  const seen = new Set<string>();
  const take = (list: ReferenceExample[]) => {
    for (const e of list) {
      if (out.length >= n) return;
      const key = e.case_id || e.image_url || e.volume?.volume_url || '';
      if (excludeCaseId && e.case_id === excludeCaseId) continue;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(e);
    }
  };
  take(examples.filter((e) => e.volume || e.finding?.polygon || e.finding?.bbox));
  take(examples);
  return out;
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
