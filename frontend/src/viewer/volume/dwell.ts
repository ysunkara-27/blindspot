// Slice dwell: how long each slice of a plane was on screen (from telemetry), and the bar drawn next to the slider
// after the reveal (from the server's `search.slice_dwell`). Pure, unit-tested; the server's numbers are the ones shown.
import type { SearchSummary, TelemetryEvent } from '../../types/contracts';
import type { Plane } from './planes';

/** Longest gap counted between two events (an idle learner is not "looking" for minutes). */
export const DWELL_GAP_CAP_MS = 1500;
/** Below this, summed over a finding's slices, the finding counts as never seen (config/scoring.yaml volumetric;
 *  mirrored for the mock). */
export const SEEN_MS = 800;
/** Below this a single slice of the finding gets the "not visited" tag on the dwell bar (a glance is 150 ms). */
export const NOT_SEEN_MS = 150;

export type SliceDwell = NonNullable<SearchSummary['slice_dwell']>[number];

/** ms on screen per slice of `plane`, from the telemetry stream: each event's slice is on screen until the next event
 *  (gaps capped). Events without a plane/slice (an X-ray, or before the first slice event) count for nothing. */
export function sliceDwellFromTelemetry(events: TelemetryEvent[], plane: Plane, cap = DWELL_GAP_CAP_MS): Map<number, number> {
  const out = new Map<number, number>();
  for (let i = 0; i + 1 < events.length; i++) {
    const e = events[i];
    if (e.plane !== plane || e.slice == null) continue;
    const dt = Math.max(0, Math.min(events[i + 1].t - e.t, cap));
    out.set(e.slice, (out.get(e.slice) ?? 0) + dt);
  }
  return out;
}

export type DwellCell = {
  slice: number;
  ms: number;
  /** 0–1, relative to the busiest slice of the plane. */
  frac: number;
  hasFinding: boolean;
  findingIds: string[];
  /** A finding's slice the learner never saw (ms below the threshold). */
  notVisited: boolean;
};

/** One cell per slice of `plane` for the dwell bar. Slices the server did not report get 0 ms. */
export function dwellCells(dwell: SliceDwell[] | null | undefined, plane: Plane, n: number, seenMs = NOT_SEEN_MS): DwellCell[] {
  const rows = (dwell ?? []).filter((d) => d.plane === plane);
  const max = rows.reduce((m, d) => Math.max(m, d.ms), 0);
  const cells: DwellCell[] = [];
  for (let s = 0; s < n; s++) {
    const d = rows.find((r) => r.slice === s);
    const ms = d?.ms ?? 0;
    const hasFinding = !!d?.has_finding;
    cells.push({ slice: s, ms, frac: max > 0 ? ms / max : 0, hasFinding, findingIds: d?.finding_ids ?? [], notVisited: hasFinding && ms < seenMs });
  }
  return cells;
}

/** The server's slice_dwell for the mock: dwell per slice plus which slices hold which findings. */
export function buildSliceDwell(
  events: TelemetryEvent[], plane: Plane, n: number,
  findings: { finding_id: string; slice_range?: number[] | null }[],
): SliceDwell[] {
  const ms = sliceDwellFromTelemetry(events, plane);
  const out: SliceDwell[] = [];
  for (let s = 0; s < n; s++) {
    const ids = findings.filter((f) => f.slice_range && s >= f.slice_range[0] && s <= f.slice_range[1]).map((f) => f.finding_id);
    out.push({ plane, slice: s, ms: Math.round(ms.get(s) ?? 0), has_finding: ids.length > 0, finding_ids: ids });
  }
  return out;
}

/** Wording of the size verdict line under a finding. Never names the body part. */
export function sizeVerdictText(v: { your_mm: number; reference_mm: number; diff_pct: number; ok: boolean } | null | undefined): string | null {
  if (!v) return null;
  const pct = Math.round(Math.abs(v.diff_pct));
  const dir = v.your_mm < v.reference_mm ? 'smaller' : v.your_mm > v.reference_mm ? 'larger' : 'the same';
  const cmp = dir === 'the same' ? 'the same' : `${pct} % ${dir}`;
  return `You measured ${fmtMm(v.your_mm)} mm; reference ${fmtMm(v.reference_mm)} mm, ${cmp} — ${v.ok ? 'within tolerance' : `off by ${fmtMm(Math.abs(v.your_mm - v.reference_mm))} mm`}.`;
}
/** "32" or "37.9": one decimal only when there is one. */
export const fmtMm = (mm: number) => { const r = Math.round(mm * 10) / 10; return Number.isInteger(r) ? r.toString() : r.toFixed(1); };
