// The reveal (SPEC §14.3): trace fades in → cyan outlines draw → amber arrows sweep → chips settle (rail).
// Timing lives in Viewer.module.css; prefers-reduced-motion makes it instant.
// Round 3: an arrow is drawn only from one of the learner's own wrong marks. A missed finding with no such mark gets
// a soft pulse on its outline instead (no arrow from the film centre, no detached label). Labels sit on solid dark
// pills; identical arrow labels are written once; unvisited review areas get a thin dashed amber ring.
// Volumes: a finding on the current slice comes with `rings` (marching-squares contours in display px) and, for the
// brain case, `components_rings` drawn as three cyan tints under the outline.
import type { Arrow, RevealFinding, RevealMark } from '../types/contracts';
import type { DraftMark } from '../read/readState';
import type { UnvisitedRing } from './anatomy';
import { arrowGeometry, placeLabels, quadPoint, rayToBoxEdge, shortArrowText, type Box, type Pt } from './arrows';
import type { Ring } from './volume/marching';
import { ringsPath } from './volume/sliceReveal';
import s from './Viewer.module.css';

export type RevealViewFinding = RevealFinding & { rings?: Ring[]; components_rings?: { name: string; label_value: number; rings: Ring[]; opacity: number }[] };

export type RevealView = {
  findings: RevealViewFinding[];
  marks: RevealMark[];
  arrows: Arrow[];
  heatmapUrl: string | null;
  /** "My search": the amber trace and the "not visited" rings. */
  showTrace: boolean;
  /** Review areas the learner did not visit, positioned from the anatomy outlines (empty when unavailable). */
  unvisited?: UnvisitedRing[];
};

type MarkLike = Pick<DraftMark, 'mark_id' | 'x' | 'y'>;

const isMiss = (r?: string | null) => !!r && (r.startsWith('missed') || r === 'pattern_missed');
const FONT = '"Atkinson Hyperlegible Next", "Atkinson Hyperlegible", system-ui, sans-serif';
const CHAR_EM = 0.56; // fallback advance when no canvas is available (tests, SSR)

let ctx: CanvasRenderingContext2D | null | undefined;
/** Text width in screen px at `px` font size, bold. Measured, so the pill behind a label fits it. */
function textWidth(text: string, px: number): number {
  if (ctx === undefined) ctx = typeof document === 'undefined' ? null : document.createElement('canvas').getContext('2d');
  if (!ctx) return text.length * CHAR_EM * px;
  ctx.font = `700 ${px}px ${FONT}`;
  return ctx.measureText(text).width * 1.03;
}

function centroidOf(f: RevealFinding): Pt {
  if (f.centroid) return [f.centroid[0], f.centroid[1]];
  return [(f.bbox[0] + f.bbox[2]) / 2, (f.bbox[1] + f.bbox[3]) / 2];
}

export function RevealLayer({ reveal, width, height, k, strokePx, marks }: {
  reveal: RevealView; width: number; height: number; k: number; strokePx: number; marks: MarkLike[];
}) {
  const sw = strokePx * k;
  const fsPx = strokePx > 2 ? 19 : 14; // projector mode: larger labels
  const fs = fsPx * k;
  const lh = fs * 1.55; // pill height
  const padX = fs * 0.55;
  const tagFs = fs * 0.84;
  const tagW = textWidth('missed', fsPx * 0.84) * k + tagFs * 0.9;

  // Finding labels: above the outline (or below if at the top edge); "missed" leads the label inside the pill.
  const fLabels = reveal.findings.map((f) => {
    const title = `${f.finding_id} · ${f.display}`;
    const miss = isMiss(f.result);
    const w = padX * 2 + (miss ? tagW + fs * 0.4 : 0) + textWidth(title, fsPx) * k;
    const above = f.bbox[1] - lh - 5 * k > 0;
    return { f, title, miss, box: { x: f.bbox[0], y: above ? f.bbox[1] - lh - 5 * k : f.bbox[3] + 5 * k, w, h: lh } as Box };
  });

  // Arrows: only from a wrong mark the learner placed. Geometry + text anchored at the middle of the sweep.
  const seenText = new Set<string>();
  const arrows = reveal.arrows.flatMap((a) => {
    const f = reveal.findings.find((x) => x.finding_id === a.to_finding);
    if (!f || !a.from_mark) return [];
    const m = marks.find((x) => x.mark_id === a.from_mark);
    const from: Pt | null = m ? [m.x, m.y] : a.from_xy ? [a.from_xy[0], a.from_xy[1]] : null;
    if (!from) return [];
    const to: Pt = a.to_xy ? [a.to_xy[0], a.to_xy[1]] : centroidOf(f);
    const r = rayToBoxEdge(from, to, f.bbox);
    const g = arrowGeometry(from, to, r, k);
    const mid = quadPoint(g.start, g.ctrl, g.end, 0.5);
    // Contract: `label` is the backend's short on-film phrase; the full sentence stays in the tooltip.
    const label = a.label?.trim() || shortArrowText(a.text);
    const w = padX * 2 + textWidth(label, fsPx) * k;
    // Findings drawn with the same outline (e.g. consolidation + effusion on one polygon) get one arrow, not two.
    const key = `${label}|${Math.round(from[0] / 12)},${Math.round(from[1] / 12)}|${f.bbox.map((v) => Math.round(v / 12)).join(',')}`;
    return [{ a, g, label, key, box: { x: mid[0] - w / 2, y: mid[1] - lh - 4 * k, w, h: lh } as Box }];
  }).filter((x, i, all) => all.findIndex((y) => y.key === x.key) === i)
    // The same words from the same mark are written once: two arrows may share one label, never a stack of copies.
    .map((x) => {
      const tk = `${x.a.from_mark}|${x.label.toLowerCase()}`;
      const repeat = seenText.has(tk);
      seenText.add(tk);
      return { ...x, showLabel: !repeat };
    });
  const pointedAt = new Set(arrows.map((x) => x.a.to_finding));
  const labelled = arrows.filter((x) => x.showLabel);

  // Unvisited review areas (only with "My search" on).
  const ringFsPx = fsPx * 0.88;
  const ringFs = ringFsPx * k;
  const ringH = ringFs * 1.5;
  const ringW = textWidth('not visited', ringFsPx) * k + ringFs * 1.0;
  const rings = reveal.showTrace ? (reveal.unvisited ?? []) : [];
  // The tag sits on the top edge of its ring, like a label on a specimen jar.
  const ringBoxes: Box[] = rings.map((r) => {
    const ry = Math.max(r.ry, 14 * k);
    return { x: r.cx - ringW / 2, y: r.cy - ry - ringH / 2, w: ringW, h: ringH };
  });

  // Learner marks (ring + "M1" tag) are fixed obstacles: labels never cover them.
  const markBoxes: Box[] = marks.map((m) => ({ x: m.x - 20 * k, y: m.y - 26 * k, w: 64 * k, h: 46 * k }));
  // Expert outlines are soft obstacles: a finding's label avoids every OTHER outline; arrow text avoids all of them.
  const pad = 3 * k;
  const outlineBox = (f: RevealFinding): Box => ({ x: f.bbox[0] - pad, y: f.bbox[1] - pad, w: f.bbox[2] - f.bbox[0] + 2 * pad, h: f.bbox[3] - f.bbox[1] + 2 * pad });
  const outlines = reveal.findings.map(outlineBox);
  const avoid = [
    ...fLabels.map((_, i) => outlines.filter((_, j) => j !== i)),
    ...labelled.map(() => outlines),
    ...ringBoxes.map(() => outlines),
  ];
  const placed = placeLabels([...fLabels.map((l) => l.box), ...labelled.map((x) => x.box), ...ringBoxes], width, height, markBoxes, avoid);
  const fPlaced = placed.slice(0, fLabels.length);
  const aPlaced = placed.slice(fLabels.length, fLabels.length + labelled.length);
  const rPlaced = placed.slice(fLabels.length + labelled.length);

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
        {rings.map((r) => (
          <ellipse key={`ring-${r.id}`} cx={r.cx} cy={r.cy} rx={Math.max(r.rx, 14 * k)} ry={Math.max(r.ry, 14 * k)}
            className={`${s.unvisitedRing} ${s.revealRing}`} strokeWidth={1.25 * k} strokeDasharray={`${5 * k} ${4 * k}`}
            data-testid={`unvisited-${r.id}`}>
            <title>{`${r.name}: not visited`}</title>
          </ellipse>
        ))}
        {fLabels.map(({ f, miss }, i) => {
          const pts = f.polygon && f.polygon.length > 2 ? f.polygon.map(([x, y]) => `${x},${y}`).join(' ') : null;
          const [x0, y0, x1, y1] = f.bbox;
          const delay = { animationDelay: `${300 + i * 60}ms` };
          // A missed finding nobody pointed an arrow at: a soft halo pulses on the outline itself.
          const halo = miss && !pointedAt.has(f.finding_id);
          const shape = (cls: string, strokeWidth: number, style?: React.CSSProperties, extra?: Record<string, string>) => f.rings?.length
            ? <path d={ringsPath(f.rings)} pathLength={1} className={cls} strokeWidth={strokeWidth} style={style} fillRule="evenodd" {...extra} />
            : pts
            ? <polygon points={pts} pathLength={1} className={cls} strokeWidth={strokeWidth} style={style} {...extra} />
            : <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0} pathLength={1} className={cls} strokeWidth={strokeWidth} style={style} {...extra} />;
          return (
            <g key={f.finding_id} data-testid={`outline-${f.finding_id}`} data-result={f.result ?? ''} data-halo={halo ? '1' : undefined}>
              {f.components_rings?.map((c) => (
                <path key={c.label_value} d={ringsPath(c.rings)} className={`${s.component} ${s.revealLabel}`} fillRule="evenodd" style={{ fillOpacity: c.opacity }}
                  data-testid={`component-${f.finding_id}-${c.label_value}`} data-component={c.name} />
              ))}
              {halo && shape(`${s.outlineHalo} ${s.revealHalo}`, sw * 3.5, undefined, { 'data-testid': `halo-${f.finding_id}` })}
              {shape(`${s.outline} ${s.revealOutline}`, sw, delay)}
            </g>
          );
        })}
        {arrows.map(({ a, g }, i) => (
          <g key={`${a.to_finding}-${i}`} data-testid={`arrow-${a.to_finding}`} filter="url(#pencil)">
            <path d={g.d} pathLength={1} className={`${s.arrowCasing} ${s.revealArrow}`} strokeWidth={sw * 1.4 + 2.5 * k} />
            <path d={g.d} pathLength={1} className={`${s.arrow} ${s.revealArrow}`} strokeWidth={sw * 1.4} />
            <path d={g.head} pathLength={1} className={`${s.arrow} ${s.revealArrowHead}`} strokeWidth={sw * 1.4} />
          </g>
        ))}
        {/* Labels last so they sit above every line. Each is plain text on a solid dark pill. */}
        {rings.map((r, i) => {
          const b = rPlaced[i];
          return (
            <g key={`rl-${r.id}`} className={s.revealRing} data-testid="unvisited-label" data-zone={r.id}>
              <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={b.h / 2} className={s.pill} />
              <text x={b.x + b.w / 2} y={b.y + b.h * 0.7} textAnchor="middle" className={s.ringText} style={{ fontSize: ringFs }}>not visited</text>
            </g>
          );
        })}
        {fLabels.map(({ f, title, miss }, i) => {
          const b = fPlaced[i];
          const base = b.y + lh * 0.69;
          const tx = b.x + padX;
          return (
            <g key={`lbl-${f.finding_id}`} className={s.revealLabel} data-testid={`label-${f.finding_id}`}>
              <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={b.h / 2} className={s.pill} />
              {miss && (
                <g transform={`translate(${tx} ${b.y + (lh - tagFs * 1.4) / 2})`}>
                  <rect width={tagW} height={tagFs * 1.4} rx={tagFs * 0.7} className={s.missChip} strokeWidth={1.2 * k} />
                  <text x={tagW / 2} y={tagFs * 1.02} textAnchor="middle" className={s.missChipText} style={{ fontSize: tagFs }}>missed</text>
                </g>
              )}
              <text x={tx + (miss ? tagW + fs * 0.4 : 0)} y={base} className={s.findingText} style={{ fontSize: fs }}>{title}</text>
            </g>
          );
        })}
        {labelled.map(({ a, label }, i) => {
          const b = aPlaced[i];
          return (
            <g key={`at-${a.to_finding}-${i}`} className={s.revealArrowText} data-testid="arrow-label" data-label={label}>
              <title>{a.text}</title>
              <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={b.h / 2} className={s.pill} />
              <text x={b.x + padX} y={b.y + lh * 0.69} className={s.arrowText} style={{ fontSize: fs }}>{label}</text>
            </g>
          );
        })}
      </svg>
    </>
  );
}
