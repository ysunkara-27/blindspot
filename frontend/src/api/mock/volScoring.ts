// Mock scoring for SYNTHETIC CT / MR cases, a small stand-in for backend/app/scoring `volumetric` (docs/VOLUMETRIC_PLAN.md):
// a hit is a mark voxel inside the finding's box (± tolerance, ± 2 slices); a mark the reference does not label is
// `unmatched` (reported, never penalised); miss types come from the slice dwell; the size verdict is within
// max(3 mm, 20 %). NOT the scoring of record.
import type { AttemptSubmit, NextCase, Outcome, RevealFinding, RevealMark, SubmitResult, TelemetryEvent } from '../../types/contracts';
import { labelDisplay } from '../labels';
import { buildSliceDwell, SEEN_MS } from '../../viewer/volume/dwell';
import type { MockVolCase, MockVolFinding } from './volTypes';

const PRESETS: Record<'ct' | 'mr', { name: string; wc: number; ww: number }[]> = {
  ct: [{ name: 'Soft tissue', wc: 50, ww: 400 }, { name: 'Liver', wc: 80, ww: 180 }, { name: 'Lung', wc: -600, ww: 1500 }, { name: 'Bone', wc: 400, ww: 1800 }],
  mr: [{ name: 'Brain', wc: 300, ww: 600 }, { name: 'Wide', wc: 400, ww: 1200 }],
};

/** The NextCase `case` block for a volume: voxels only, never the mask. */
export function volumeCase(c: MockVolCase): NextCase['case'] {
  return {
    case_id: c.case_id, image_url: `/mock/vol/${c.case_id}_axial.png`, width: c.width, height: c.height,
    modality: c.modality, body_region: c.body_region,
    volume: { shape: c.volume.shape, spacing: c.volume.spacing, window: c.volume.window, data_url: `/mock/vol/${c.case_id}.i16.gz`, sequence: c.volume.sequence, presets: PRESETS[c.modality] },
    provenance: c.provenance,
  };
}

/** Names of the mask's anatomy values (GET /attempts/{aid}/anatomy for a volume). */
export function volumeAnatomy(c: MockVolCase) {
  const findingValues = new Set(c.findings.flatMap((f) => f.label_values));
  const labels: Record<string, string> = {};
  for (const [k, v] of Object.entries(c.volume.labels)) if (!findingValues.has(Number(k))) labels[k] = v;
  return { labels, approximate: false };
}

const RECOG_MS = 2000;
const NEAR_MM = 15;

function inFinding(f: MockVolFinding, vox: number[], c: MockVolCase): boolean {
  const [sz, sy, sx] = c.volume.spacing;
  const fovMm = Math.max(c.volume.shape[1] * sy, c.volume.shape[2] * sx);
  const tolVox = (0.02 * fovMm) / Math.min(sx, sy);
  const [x, y, z] = vox;
  const [x0, y0, x1, y1] = f.bbox;
  void sz;
  return x >= x0 - tolVox && x <= x1 + tolVox && y >= y0 - tolVox && y <= y1 + tolVox && z >= f.slice_range[0] - 2 && z <= f.slice_range[1] + 2;
}

/** Was the cursor ever within 15 mm of the finding's centroid, on one of its slices? */
function cursorNear(f: MockVolFinding, events: TelemetryEvent[], c: MockVolCase): boolean {
  const [, sy, sx] = c.volume.spacing;
  const [cx, cy] = f.centroid3;
  return events.some((e) => e.plane === 'axial' && e.slice != null && e.slice >= f.slice_range[0] && e.slice <= f.slice_range[1]
    && e.x !== undefined && e.y !== undefined && Math.hypot((e.x - cx) * sx, (e.y - cy) * sy) <= NEAR_MM);
}

export function scoreVolumeAttempt(c: MockVolCase, body: AttemptSubmit): SubmitResult {
  const nz = c.volume.shape[0];
  const sliceDwell = buildSliceDwell(body.telemetry, 'axial', nz, c.findings);
  const dwellOf = (f: MockVolFinding) => sliceDwell.filter((d) => d.slice >= f.slice_range[0] && d.slice <= f.slice_range[1]).reduce((n, d) => n + d.ms, 0);
  const outcomes: Outcome[] = [];
  const marks: RevealMark[] = [];
  const matchedBy = new Map<string, string>();
  const markTo = new Map<string, string>();
  // Nearest-first greedy matching on the voxel.
  const pairs: { m: string; f: MockVolFinding; d: number }[] = [];
  for (const mk of body.marks) {
    const vox = mk.voxel ?? [mk.x, mk.y, mk.slice ?? 0];
    for (const f of c.findings) if (inFinding(f, vox, c)) pairs.push({ m: mk.mark_id, f, d: Math.hypot(vox[0] - f.centroid3[0], vox[1] - f.centroid3[1], (vox[2] - f.centroid3[2]) * 2) });
  }
  pairs.sort((a, b) => a.d - b.d);
  for (const p of pairs) {
    if (markTo.has(p.m) || matchedBy.has(p.f.finding_id)) continue;
    markTo.set(p.m, p.f.finding_id);
    matchedBy.set(p.f.finding_id, p.m);
  }
  let unmatched = 0;
  for (const mk of body.marks) {
    const fid = markTo.get(mk.mark_id);
    const base = { mark_id: mk.mark_id, zone: 'mid_slab', voxel: mk.voxel ?? null, plane: mk.plane ?? null, slice: mk.slice ?? null };
    if (fid) { marks.push({ ...base, result: 'true_positive', matched_finding: fid }); continue; }
    const dup = pairs.find((p) => p.m === mk.mark_id);
    if (dup) {
      marks.push({ ...base, result: 'duplicate', matched_finding: dup.f.finding_id });
      outcomes.push({ target: mk.mark_id, result: 'duplicate', zone: 'mid_slab', matched: dup.f.finding_id });
      continue;
    }
    unmatched++;
    marks.push({ ...base, result: 'unmatched' as RevealMark['result'] });
    outcomes.push({ target: mk.mark_id, result: 'unmatched', zone: 'mid_slab', learner_label: mk.label });
  }

  const findings: RevealFinding[] = [];
  const findingSlicesViewed: Record<string, boolean> = {};
  let localized = 0;
  let exact = 0;
  for (const f of c.findings) {
    const mid = matchedBy.get(f.finding_id);
    const dwell = dwellOf(f);
    findingSlicesViewed[f.finding_id] = dwell >= SEEN_MS;
    let result: Outcome['result'];
    let learnerLabel: string | null = null;
    if (mid) {
      localized++;
      const mk = body.marks.find((m) => m.mark_id === mid)!;
      learnerLabel = mk.label;
      if (mk.label === f.label) { exact++; result = 'found'; } else result = 'mislabeled';
    } else result = dwell < SEEN_MS ? 'missed_search' : dwell < RECOG_MS || !cursorNear(f, body.telemetry, c) ? 'missed_recognition' : 'missed_decision';
    // Size verdict: the learner's measurement for the matched mark against the reference's longest diameter.
    const meas = mid ? (body.measurements ?? []).find((m) => m.mark_id === mid) : undefined;
    const sizeVerdict = meas
      ? (() => {
          const ref = f.measure.long_mm;
          const diff = meas.long_mm - ref;
          const tol = Math.max(3, 0.2 * ref);
          return { your_mm: Math.round(meas.long_mm * 10) / 10, reference_mm: ref, diff_mm: Math.round(diff * 10) / 10, diff_pct: Math.round((diff / ref) * 1000) / 10, ok: Math.abs(diff) <= tol, plane: meas.plane };
        })()
      : null;
    outcomes.unshift({ target: f.finding_id, result, dwell_ms: dwell, zone: f.primary_zone, matched: mid ?? null, learner_label: learnerLabel, size_verdict: sizeVerdict, slices_viewed: dwell >= SEEN_MS });
    findings.push({
      finding_id: f.finding_id, label: f.label, display: labelDisplay(f.label), kind: f.kind, polygon: null, bbox: f.bbox, centroid: f.centroid,
      side: f.side, zones: f.zones, primary_zone: f.primary_zone, relative_location: f.relative_location, result, dwell_ms: dwell,
      slice_range: f.slice_range, centroid3: f.centroid3, label_values: f.label_values, components: f.components, measure: f.measure, size_verdict: sizeVerdict,
    });
  }

  const nf = c.findings.length;
  let score: number;
  let success: boolean;
  if (c.is_normal) {
    const tn = body.declared_normal && body.marks.length === 0;
    if (tn) outcomes.push({ target: 'case', result: 'true_negative' });
    score = 100; // unmatched marks are never penalised
    success = true;
  } else {
    score = nf ? Math.round(70 * (localized / nf) + 20 * (exact / nf) + 10 * (localized > 0 ? 1 : 0)) : 100;
    success = localized === nf;
  }
  const viewed = sliceDwell.filter((d) => d.ms >= 100).length;
  const slicesViewedPct = Math.round((100 * viewed) / nz);
  const missed = findings.filter((f) => f.result?.startsWith('missed'));
  const found = findings.filter((f) => f.result === 'found');
  const headline = c.is_normal
    ? body.declared_normal ? 'Nothing to find here, and you called it normal.' : `Nothing labelled here${unmatched ? `; ${unmatched} mark${unmatched > 1 ? 's' : ''} not in the reference` : ''}.`
    : missed.length === 0 ? `Every finding found${unmatched ? `, ${unmatched} mark${unmatched > 1 ? 's' : ''} not in the reference` : ''}.` : `${found.length} of ${findings.length} found.`;
  const lines = findings.map((f) => `${f.finding_id} ${f.display}, slices ${f.slice_range![0] + 1}–${f.slice_range![1] + 1}: ${f.result?.replace(/_/g, ' ')}.`);
  lines.push(`You scrolled through about ${slicesViewedPct}% of the slices.`);
  return {
    score, success, outcomes,
    reveal: {
      findings, marks, arrows: [],
      search: {
        lung_coverage_pct: slicesViewedPct, unvisited_review_areas: [], visited_review_areas: [],
        loupe_used: body.telemetry.some((e) => e.loupe), zoom_used: body.telemetry.some((e) => e.zoom > 1.05),
        slice_dwell: sliceDwell, slices_viewed_pct: slicesViewedPct, finding_slices_viewed: findingSlicesViewed,
      },
      is_normal: c.is_normal, maskvol_url: `/mock/vol/${c.case_id}.u8.gz`, modality: c.modality, provenance: c.provenance,
    },
    facts_card: { headline, lines },
    debrief_status: 'pending',
  };
}
