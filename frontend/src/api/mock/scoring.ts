// A deliberately small stand-in for the backend engines (SPEC §6–§7) so the UI can be built and tested
// without the API. It is NOT the scoring of record — backend/app/scoring is. Synthetic data only.
import type {
  Arrow, AttemptSubmit, DebriefOutput, Outcome, RevealFinding, RevealMark, SubmitResult, TelemetryEvent,
} from '../../types/contracts';
import { labelDisplay, zoneDisplay } from '../labels';
import type { MockCase, MockFinding } from './types';

const RELATED = [['consolidation', 'atelectasis'], ['nodule', 'mass', 'calcification'], ['effusion', 'pleural_thickening']];
const REVIEW_AREAS = ['right_apex', 'left_apex', 'right_hilum', 'left_hilum', 'retrocardiac', 'right_costophrenic_angle', 'left_costophrenic_angle'];

function inBox(x: number, y: number, b: [number, number, number, number], pad: number): boolean {
  return x >= b[0] - pad && x <= b[2] + pad && y >= b[1] - pad && y <= b[3] + pad;
}

/** Patient-side zone for a point. Patient RIGHT is on the image LEFT (CLAUDE.md rule 3). */
export function mockZone(x: number, y: number, w: number, h: number): string {
  const side = x < w / 2 ? 'right' : 'left';
  const third = y < h / 3 ? 'upper' : y < (2 * h) / 3 ? 'mid' : 'lower';
  return `${side}_${third}_zone`;
}

function reviewAreaBox(area: string, w: number, h: number): [number, number, number, number] {
  const L: [number, number] = [0.08 * w, 0.48 * w];
  const R: [number, number] = [0.52 * w, 0.92 * w];
  switch (area) {
    case 'right_apex': return [L[0], 0.08 * h, L[1], 0.3 * h];
    case 'left_apex': return [R[0], 0.08 * h, R[1], 0.3 * h];
    case 'right_hilum': return [0.3 * w, 0.38 * h, 0.48 * w, 0.58 * h];
    case 'left_hilum': return [0.52 * w, 0.38 * h, 0.7 * w, 0.58 * h];
    case 'retrocardiac': return [0.5 * w, 0.55 * h, 0.7 * w, 0.85 * h];
    case 'right_costophrenic_angle': return [L[0], 0.75 * h, 0.3 * w, 0.95 * h];
    default: return [0.7 * w, 0.75 * h, R[1], 0.95 * h];
  }
}

/** Dwell proxy (SPEC §7.1, simplified: no zoom term). */
export function dwellMs(events: TelemetryEvent[], box: [number, number, number, number], pad: number): number {
  let total = 0;
  let still = 0;
  for (let i = 0; i + 1 < events.length; i++) {
    const e0 = events[i];
    const e1 = events[i + 1];
    const dt = Math.min(e1.t - e0.t, 250);
    if (e0.x === undefined || e0.y === undefined) continue;
    const moved = e1.x === undefined || e1.y === undefined || Math.abs(e1.x - e0.x) + Math.abs(e1.y - e0.y) > 1;
    still = moved ? 0 : still + dt;
    if (still > 1500) continue;
    if (inBox(e0.x, e0.y, box, pad)) total += dt;
  }
  return total;
}

function related(a: string, b: string): boolean {
  return RELATED.some((g) => g.includes(a) && g.includes(b));
}

export function scoreAttempt(c: MockCase, body: AttemptSubmit): SubmitResult {
  const pad = 0.035 * c.width;
  const focal = c.findings.filter((f) => f.kind === 'focal');
  const patterns = c.findings.filter((f) => f.kind === 'pattern');
  const outcomes: Outcome[] = [];
  const markResults: RevealMark[] = [];
  const matchedBy = new Map<string, string>(); // finding id -> mark id

  // Greedy matching by distance to centroid (the backend uses Hungarian matching).
  const pairs: { m: number; f: MockFinding; d: number }[] = [];
  body.marks.forEach((mk, i) => {
    for (const f of focal) {
      if (inBox(mk.x, mk.y, f.bbox, pad)) pairs.push({ m: i, f, d: Math.hypot(mk.x - f.centroid[0], mk.y - f.centroid[1]) });
    }
  });
  pairs.sort((a, b) => a.d - b.d);
  const markTo = new Map<number, string>();
  for (const p of pairs) {
    if (markTo.has(p.m) || matchedBy.has(p.f.finding_id)) continue;
    markTo.set(p.m, p.f.finding_id);
    matchedBy.set(p.f.finding_id, body.marks[p.m].mark_id);
  }
  let fp = 0;
  body.marks.forEach((mk, i) => {
    const zone = mockZone(mk.x, mk.y, c.width, c.height);
    const fid = markTo.get(i);
    if (fid) {
      markResults.push({ mark_id: mk.mark_id, result: 'true_positive', matched_finding: fid, zone });
      return;
    }
    const dup = pairs.find((p) => p.m === i);
    if (dup) {
      markResults.push({ mark_id: mk.mark_id, result: 'duplicate', matched_finding: dup.f.finding_id, zone });
      outcomes.push({ target: mk.mark_id, result: 'duplicate', zone, matched: dup.f.finding_id });
      return;
    }
    fp++;
    markResults.push({ mark_id: mk.mark_id, result: 'false_positive', zone });
    outcomes.push({ target: mk.mark_id, result: 'false_positive', zone, learner_label: mk.label });
  });

  const revealFindings: RevealFinding[] = [];
  let localized = 0;
  let exact = 0;
  for (const f of focal) {
    const mid = matchedBy.get(f.finding_id);
    const dwell = Math.round(dwellMs(body.telemetry, f.bbox, pad));
    let result: Outcome['result'];
    let learnerLabel: string | null = null;
    if (mid) {
      localized++;
      const mk = body.marks.find((m) => m.mark_id === mid)!;
      learnerLabel = mk.label;
      if (mk.label === f.label) { exact++; result = 'found'; } else result = 'mislabeled';
      if (result === 'mislabeled' && related(mk.label, f.label)) exact += 0.5;
    } else result = dwell < 300 ? 'missed_search' : dwell < 1000 ? 'missed_recognition' : 'missed_decision';
    outcomes.unshift({ target: f.finding_id, result, dwell_ms: dwell, zone: f.primary_zone, matched: mid ?? null, learner_label: learnerLabel });
    revealFindings.push({
      finding_id: f.finding_id, label: f.label, display: labelDisplay(f.label), kind: 'focal', polygon: f.polygon, bbox: f.bbox,
      centroid: f.centroid, side: f.side, zones: f.zones, primary_zone: f.primary_zone, relative_location: f.relative_location,
      result, dwell_ms: dwell,
    });
  }
  let patternOk = 0;
  for (const f of patterns) {
    const sel = body.patterns.find((p) => p.label === f.label);
    const result = sel ? 'pattern_found' : 'pattern_missed';
    if (sel) patternOk++;
    outcomes.push({ target: f.finding_id, result, zone: f.primary_zone });
    revealFindings.push({
      finding_id: f.finding_id, label: f.label, display: labelDisplay(f.label), kind: 'pattern', polygon: f.polygon, bbox: f.bbox,
      centroid: f.centroid, side: f.side, zones: f.zones, primary_zone: f.primary_zone, relative_location: f.relative_location, result,
    });
  }
  const falsePatterns = body.patterns.filter((p) => !patterns.some((f) => f.label === p.label));
  for (const p of falsePatterns) outcomes.push({ target: p.label, result: 'pattern_false', learner_label: p.label });

  let score: number;
  let success: boolean;
  if (c.is_normal) {
    const tn = body.declared_normal && body.marks.length === 0;
    if (tn) outcomes.push({ target: 'case', result: 'true_negative' });
    score = Math.max(0, 100 - 25 * fp - 10 * falsePatterns.length - 5 * body.hints_used);
    success = fp === 0 && falsePatterns.length === 0;
  } else {
    const nf = focal.length;
    const patAcc = patterns.length + falsePatterns.length ? patternOk / (patterns.length + falsePatterns.length) : 1;
    score = nf
      ? 70 * (localized / nf) + 20 * (exact / nf) + 10 * patAcc - 10 * fp - 5 * body.hints_used
      : 100 * patAcc - 10 * fp - 5 * body.hints_used;
    score = Math.max(0, Math.round(score));
    success = localized === nf && fp <= 1 && patternOk === patterns.length;
  }

  // Arrows: from the nearest wrong mark (or the image centre) to each missed focal finding (SPEC §14.3 step 3).
  const arrows: Arrow[] = [];
  const wrong = body.marks.filter((m) => markResults.find((r) => r.mark_id === m.mark_id)?.result === 'false_positive');
  for (const rf of revealFindings) {
    if (rf.kind !== 'focal' || !rf.result?.startsWith('missed')) continue;
    const [cx, cy] = rf.centroid!;
    let from: (typeof wrong)[number] | null = null;
    for (const m of wrong) if (!from || Math.hypot(m.x - cx, m.y - cy) < Math.hypot(from.x - cx, from.y - cy)) from = m;
    const text = from ? relationText(from.x, from.y, cx, cy, from.mark_id) : `Here: ${rf.relative_location ?? zoneDisplay(rf.primary_zone)}`;
    arrows.push({ from_mark: from?.mark_id ?? null, to_finding: rf.finding_id, text, from_xy: from ? [from.x, from.y] : null, to_xy: [cx, cy] });
  }

  // Coverage of review areas from telemetry.
  const visited = REVIEW_AREAS.filter((a) => dwellMs(body.telemetry, reviewAreaBox(a, c.width, c.height), 0) >= 300);
  const unvisited = REVIEW_AREAS.filter((a) => !visited.includes(a));
  const cells = new Set<string>();
  for (const e of body.telemetry) if (e.x !== undefined && e.y !== undefined) cells.add(`${Math.floor((e.x / c.width) * 12)},${Math.floor((e.y / c.height) * 12)}`);
  const lungCoverage = Math.min(100, Math.round((cells.size / 80) * 100));

  const missed = revealFindings.filter((f) => f.result?.startsWith('missed') || f.result === 'pattern_missed');
  const found = revealFindings.filter((f) => f.result === 'found' || f.result === 'pattern_found');
  const headline = c.is_normal
    ? fp ? `Normal film. ${fp} mark${fp > 1 ? 's' : ''} on healthy lung.` : body.declared_normal ? 'Normal film, called normal.' : 'Normal film.'
    : missed.length === 0 && fp === 0 ? 'Every finding found.' : `${found.length} of ${revealFindings.length} found${fp ? `, ${fp} overcall${fp > 1 ? 's' : ''}` : ''}.`;
  const lines: string[] = [];
  for (const f of revealFindings) {
    const where = f.relative_location ?? zoneDisplay(f.primary_zone);
    lines.push(`${f.finding_id} ${f.display}, ${where}: ${f.result?.replace(/_/g, ' ')}${f.dwell_ms != null ? ` (dwell ${(f.dwell_ms / 1000).toFixed(1)} s)` : ''}.`);
  }
  for (const r of markResults.filter((r) => r.result === 'false_positive')) lines.push(`${r.mark_id} in the ${zoneDisplay(r.zone)}: nothing there on the expert read.`);
  lines.push(`Search covered about ${lungCoverage}% of the film. Not visited: ${unvisited.map(zoneDisplay).join(', ') || 'none'}.`);
  if (body.hints_used) lines.push(`Hints used: ${body.hints_used} (−${5 * body.hints_used} points).`);

  return {
    score, success, outcomes,
    reveal: {
      findings: revealFindings, marks: markResults, arrows,
      search: { lung_coverage_pct: lungCoverage, unvisited_review_areas: unvisited, visited_review_areas: visited, loupe_used: body.telemetry.some((e) => e.loupe), zoom_used: body.telemetry.some((e) => e.zoom > 1.05) },
      ctr: c.ctr, is_normal: c.is_normal,
    },
    facts_card: { headline, lines },
    debrief_status: 'pending',
  };
}

/** Spatial relation phrased in the patient's frame: image left = patient right. */
export function relationText(fx: number, fy: number, tx: number, ty: number, fromId: string): string {
  const dx = tx - fx;
  const dy = ty - fy;
  const parts: string[] = [];
  if (Math.abs(dy) > 8) parts.push(dy > 0 ? 'down' : 'up');
  if (Math.abs(dx) > 8) parts.push(dx > 0 ? "toward the patient's left" : "toward the patient's right");
  const rel = parts.length ? parts.join(' and ') : 'right beside';
  return `From ${fromId}: ${rel}`;
}

const SIGNS: Record<string, string[]> = {
  pneumothorax: ['A thin white pleural line', 'No lung markings beyond the line'],
  effusion: ['Blunted costophrenic angle', 'A meniscus curving up the chest wall'],
  consolidation: ['Hazy white lung that hides vessels', 'Air bronchograms'],
  atelectasis: ['Volume loss with shifted fissures', 'A band of increased density'],
  nodule: ['A small round opacity', 'Sharp or lobulated edges'],
  mass: ['A large round opacity', 'May distort nearby structures'],
  cardiomegaly: ['Heart wider than half the chest', 'Check the cardiothoracic ratio'],
};
const WHY: Record<string, string> = {
  missed_search: 'Your search never paused in this area. Make it a stop on every film.',
  missed_recognition: 'Your cursor passed through but did not stop. Slow down where the shape changes.',
  missed_decision: 'You spent time here and judged it normal. Compare with the same zone on the other side.',
  mislabeled: 'You found it. The label differs; compare the key signs.',
  found: 'Found and named correctly.',
  pattern_found: 'Called correctly.',
  pattern_missed: 'This global finding was not selected.',
};

export function templateDebrief(r: SubmitResult): DebriefOutput {
  const f = r.reveal.findings;
  const missed = f.filter((x) => x.result?.startsWith('missed') || x.result === 'pattern_missed');
  const fps = r.reveal.marks.filter((m) => m.result === 'false_positive');
  const verdict: DebriefOutput['verdict'] = r.reveal.is_normal
    ? fps.length ? 'missed_normal_call' : 'correct_normal'
    : missed.length === 0 ? fps.length ? 'overcall' : 'all_found' : missed.length === f.length ? 'missed' : 'partly_found';
  return {
    headline: r.facts_card.headline,
    verdict,
    findings: f.map((x) => ({
      finding_id: x.finding_id,
      result: (x.result ?? 'found') as DebriefOutput['findings'][number]['result'],
      where_to_look: x.relative_location ? `The ${x.relative_location}.` : 'See the outline.',
      what_it_looks_like: SIGNS[x.label] ?? ['See the teaching card'],
      why: WHY[x.result ?? 'found'] ?? '',
    })),
    overcalls: fps.map((m) => ({ mark_id: m.mark_id, explanation: `Nothing on the expert read in the ${zoneDisplay(m.zone)}.`, possible_mimics: ['Overlapping ribs', 'Vessels seen end-on'] })),
    search_coaching: r.reveal.search.unvisited_review_areas.length
      ? `Next time, stop at: ${r.reveal.search.unvisited_review_areas.slice(0, 3).map(zoneDisplay).join(', ')}.`
      : 'You visited every review area.',
    calibration_note: 'Compare your confidence with the outcome for each mark.',
    next_step: missed.length ? `Try another ${missed[0].display.toLowerCase()} case.` : 'Try a harder case.',
    fact_ids: f.map((x) => x.finding_id),
  };
}
