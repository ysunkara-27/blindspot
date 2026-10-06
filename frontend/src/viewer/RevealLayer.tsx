// The reveal (SPEC §14.3): trace fades in → cyan outlines draw → amber arrows sweep → chips settle (rail).
// Timing lives in Viewer.module.css; prefers-reduced-motion makes it instant.
import type { Arrow, RevealFinding, RevealMark } from '../types/contracts';
import type { DraftMark } from '../read/readState';
import { arrowGeometry, placeLabels, quadPoint, rayToBoxEdge, shortArrowText, type Box, type Pt } from './arrows';
import s from './Viewer.module.css';

export type RevealView = {
  findings: RevealFinding[];
  marks: RevealMark[];
  arrows: Arrow[];
  heatmapUrl: string | null;
  showTrace: boolean;
};

const isMiss = (r?: string | null) => !!r && (r.startsWith('missed') || r === 'pattern_missed');
const CHAR_EM = 0.56; // approximate advance of Atkinson Hyperlegible Next bold

function centroidOf(f: RevealFinding): Pt {
  if (f.centroid) return [f.centroid[0], f.centroid[1]];
  return [(f.bbox[0] + f.bbox[2]) / 2, (f.bbox[1] + f.bbox[3]) / 2];
}

export function RevealLayer({ reveal, width, height, k, strokePx, marks }: {
  reveal: RevealView; width: number; height: number; k: number; strokePx: number; marks: DraftMark[];
}) {
  const sw = strokePx * k;
  const fs = (strokePx > 2 ? 19 : 14) * k; // projector mode: larger labels
  const lh = fs * 1.35;
  const chipW = fs * 3.7;

  // Finding labels: above the outline (or below if at the top edge); "missed" chip leads the label.
  const fLabels = reveal.findings.map((f) => {
    const title = `${f.finding_id} · ${f.display}`;
    const miss = isMiss(f.result);
    const w = (miss ? chipW + fs * 0.4 : 0) + title.length * CHAR_EM * fs;
    const above = f.bbox[1] - lh - 4 * k > 0;
    return { f, title, miss, box: { x: f.bbox[0], y: above ? f.bbox[1] - lh - 4 * k : f.bbox[3] + 4 * k, w, h: lh } as Box };
  });

  // Arrows: geometry + text anchored at the middle of the sweep.
  const arrows = reveal.arrows.flatMap((a) => {
    const f = reveal.findings.find((x) => x.finding_id === a.to_finding);
    if (!f) return [];
    const to: Pt = a.to_xy ? [a.to_xy[0], a.to_xy[1]] : centroidOf(f);
    const m = a.from_mark ? marks.find((x) => x.mark_id === a.from_mark) : null;
    const from: Pt = a.from_xy ? [a.from_xy[0], a.from_xy[1]] : m ? [m.x, m.y] : [width / 2, height / 2];
    const r = rayToBoxEdge(from, to, f.bbox);
    const g = arrowGeometry(from, to, r, k);
    const mid = quadPoint(g.start, g.ctrl, g.end, 0.5);
    // Contract: `label` is the backend's short on-film phrase; the full sentence stays in the tooltip.
    const label = a.label?.trim() || shortArrowText(a.text);
    const w = label.length * CHAR_EM * fs;
    // Findings drawn with the same outline (e.g. consolidation + effusion on one polygon) get one arrow, not two.
    const key = `${label}|${Math.round(from[0] / 12)},${Math.round(from[1] / 12)}|${f.bbox.map((v) => Math.round(v / 12)).join(',')}`;
    return [{ a, g, label, key, box: { x: mid[0] - w / 2, y: mid[1] - lh - 4 * k, w, h: lh } as Box }];
  }).filter((x, i, all) => all.findIndex((y) => y.key === x.key) === i);

  // Learner marks (ring + "M1" tag) are fixed obstacles: labels never cover them.
  const markBoxes: Box[] = marks.map((m) => ({ x: m.x - 20 * k, y: m.y - 26 * k, w: 64 * k, h: 46 * k }));
  // Expert outlines are soft obstacles: a finding's label avoids every OTHER outline; arrow text avoids all of them.
  const pad = 3 * k;
  const outlineBox = (f: RevealFinding): Box => ({ x: f.bbox[0] - pad, y: f.bbox[1] - pad, w: f.bbox[2] - f.bbox[0] + 2 * pad, h: f.bbox[3] - f.bbox[1] + 2 * pad });
  const outlines = reveal.findings.map(outlineBox);
  const avoid = [
    ...fLabels.map((_, i) => outlines.filter((_, j) => j !== i)),
    ...arrows.map(() => outlines),
  ];
  const placed = placeLabels([...fLabels.map((l) => l.box), ...arrows.map((x) => x.box)], width, height, markBoxes, avoid);
  const fPlaced = placed.slice(0, fLabels.length);
  const aPlaced = placed.slice(fLabels.length);

  return (
    <>
      {reveal.heatmapUrl && reveal.showTrace && (
        <img src={reveal.heatmapUrl} alt="" className={`${s.trace} ${s.revealTrace}`} width={width} height={height} data-testid="search-trace" />
      )}
      <svg className={s.overlay} viewBox={`0 0 ${width} ${height}`} width={width} height={height} data-testid="reveal-layer">
        <defs>
          <filter id="pencil" filterUnits="userSpaceOnUse" x={0} y={0} width={width} height={height}>
            <feTurbulence type="fractalNoise" baseFrequency={0.9} numOctaves={1} seed={7} />
            <feDisplacementMap in="SourceGraphic" scale={1.8 * k} />
          </filter>
        </defs>
        {fLabels.map(({ f }, i) => {
          const pts = f.polygon && f.polygon.length > 2 ? f.polygon.map(([x, y]) => `${x},${y}`).join(' ') : null;
          const [x0, y0, x1, y1] = f.bbox;
          return (
            <g key={f.finding_id} data-testid={`outline-${f.finding_id}`} data-result={f.result ?? ''}>
              {pts ? (
                <polygon points={pts} pathLength={1} className={`${s.outline} ${s.revealOutline}`} strokeWidth={sw}
                  style={{ animationDelay: `${300 + i * 60}ms` }} />
              ) : (
                <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} pathLength={1} className={`${s.outline} ${s.revealOutline}`} strokeWidth={sw}
                  style={{ animationDelay: `${300 + i * 60}ms` }} />
              )}
            </g>
          );
        })}
        {arrows.map(({ a, g }, i) => (
          <g key={`${a.to_finding}-${i}`} data-testid={`arrow-${a.to_finding}`} filter="url(#pencil)">
            <path d={g.d} pathLength={1} className={`${s.arrow} ${s.revealArrow}`} strokeWidth={sw * 1.4} />
            <path d={g.head} pathLength={1} className={`${s.arrow} ${s.revealArrowHead}`} strokeWidth={sw * 1.4} />
          </g>
        ))}
        {/* Labels last so they sit above every line. */}
        {fLabels.map(({ f, title, miss }, i) => {
          const b = fPlaced[i];
          const base = b.y + lh * 0.78;
          return (
            <g key={`lbl-${f.finding_id}`} className={s.revealLabel}>
              {miss && (
                <g transform={`translate(${b.x} ${b.y + (lh - fs * 1.25) / 2})`}>
                  <rect width={chipW} height={fs * 1.25} rx={fs * 0.62} className={s.missChip} strokeWidth={1.2 * k} />
                  <text x={chipW / 2} y={fs * 0.92} textAnchor="middle" className={s.missChipText} style={{ fontSize: fs * 0.82 }}>missed</text>
                </g>
              )}
              <text x={b.x + (miss ? chipW + fs * 0.4 : 0)} y={base} className={s.findingText} style={{ fontSize: fs, strokeWidth: 3.5 * k }}>{title}</text>
            </g>
          );
        })}
        {arrows.map(({ a, label }, i) => {
          const b = aPlaced[i];
          return (
            <text key={`at-${a.to_finding}-${i}`} x={b.x} y={b.y + lh * 0.78} className={`${s.arrowText} ${s.revealArrowText}`}
              style={{ fontSize: fs, strokeWidth: 3.5 * k }}>
              <title>{a.text}</title>
              {label}
            </text>
          );
        })}
      </svg>
    </>
  );
}
