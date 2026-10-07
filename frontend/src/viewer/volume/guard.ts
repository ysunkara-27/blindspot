// Loose guards for the volumetric parts of the API payloads (NextCase.case.volume, the anatomy names after submit).
import type { NextCase } from '../../types/contracts';
import type { Window } from './window';

export type VolumeCase = NextCase['case'];
export type VolumeMetaFull = {
  shape: number[]; spacing: number[]; window: Window; data_url: string;
  presets?: { name: string; wc: number; ww: number }[] | null; sequence?: string | null;
};

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === 'object' && v !== null && !Array.isArray(v);
const num3 = (v: unknown): v is number[] => Array.isArray(v) && v.length === 3 && v.every((n) => typeof n === 'number' && Number.isFinite(n) && n > 0);

/** A CT / MR case with a usable volume block. */
export function isVolumetric(c: Pick<VolumeCase, 'modality' | 'volume'> | null | undefined): boolean {
  return !!c && (c.modality === 'ct' || c.modality === 'mr') && volumeMeta(c) !== null;
}

export function volumeMeta(c: Pick<VolumeCase, 'volume'> | null | undefined): VolumeMetaFull | null {
  const v = c?.volume;
  if (!isObj(v) || !num3(v.shape) || !num3(v.spacing) || typeof v.data_url !== 'string' || !v.data_url) return null;
  const w = isObj(v.window) ? v.window : null;
  const wc = typeof w?.wc === 'number' ? w.wc : 0;
  const ww = typeof w?.ww === 'number' && w.ww > 0 ? w.ww : 1;
  const presets = Array.isArray(v.presets)
    ? v.presets.filter((q): q is { name: string; wc: number; ww: number } => isObj(q) && typeof q.name === 'string' && typeof q.wc === 'number' && typeof q.ww === 'number')
    : null;
  return { shape: v.shape, spacing: v.spacing, window: { wc, ww }, data_url: v.data_url, presets, sequence: typeof v.sequence === 'string' ? v.sequence : null };
}

/** Names of the mask's anatomy values from GET /attempts/{aid}/anatomy for a volume: accepts `{labels: {"1": "pancreas"}}`,
 *  `{values: …}`, `{zones: [{value, name}]}`, or nothing (then zones are "Structure n"). */
export function guardMaskNames(raw: unknown): Record<string, string> {
  const out: Record<string, string> = {};
  if (!isObj(raw)) return out;
  const map = raw.labels ?? raw.values ?? raw.names;
  if (isObj(map)) {
    for (const [k, v] of Object.entries(map)) if (typeof v === 'string' && /^\d+$/.test(k)) out[k] = pretty(v);
  }
  const zones = raw.zones;
  if (Array.isArray(zones)) {
    for (const z of zones) {
      if (!isObj(z)) continue;
      const value = typeof z.value === 'number' ? z.value : typeof z.label_value === 'number' ? z.label_value : null;
      const name = typeof z.name === 'string' ? z.name : typeof z.zone_id === 'string' ? z.zone_id : typeof z.id === 'string' ? z.id : null;
      if (value != null && name) out[String(value)] = pretty(name);
    }
  }
  return out;
}
const pretty = (s: string) => { const t = s.replace(/_/g, ' '); return t.charAt(0).toUpperCase() + t.slice(1); };
