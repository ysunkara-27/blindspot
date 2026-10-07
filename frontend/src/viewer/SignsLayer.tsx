// Signs on the reveal (round 5): each `reveal.findings[].signs` drawn on the film in cyan (expert truth, SPEC §14) —
// polyline / polygon as a dashed line on a thin dark casing, circle as a dashed ring, segment as a solid line with end
// ticks, arrow as a cyan arrow, band as a 25 % fill — with a "Look for: {name}" pill placed by the shared label placer
// (RevealLayer hands the placed boxes in, so pills never cover outlines, arrows or each other). Hovering or focusing a
// sign shows its one-line `text`. `focused` (from viewer/signs.ts) pulses one sign for 1.5 s; reduced motion: no pulse.
import { useEffect, useState } from 'react';
import { FOCUS_MS, signBounds, useSigns, type ViewSign } from './signs';
import { signLabel, signTextWidth, wrapText } from './signLabels';
import type { Box } from './arrows';
import s from './Viewer.module.css';

function arrowPath(a: [number, number], b: [number, number], k: number): { line: string; head: string } {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  const h = 12 * k;
  const ang = (26 * Math.PI) / 180;
  const rot = (x: number, y: number, t: number): [number, number] => [x * Math.cos(t) - y * Math.sin(t), x * Math.sin(t) + y * Math.cos(t)];
  const [l1x, l1y] = rot(-ux, -uy, ang);
  const [l2x, l2y] = rot(-ux, -uy, -ang);
  return {
    line: `M ${a[0]} ${a[1]} L ${b[0] - ux * h * 0.6} ${b[1] - uy * h * 0.6}`,
    head: `M ${b[0] + l1x * h} ${b[1] + l1y * h} L ${b[0]} ${b[1]} L ${b[0] + l2x * h} ${b[1] + l2y * h}`,
  };
}

function segmentPath(a: [number, number], b: [number, number], k: number): { line: string; ticks: string } {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy) || 1;
  const nx = (-dy / len) * 5 * k;
  const ny = (dx / len) * 5 * k;
  return {
    line: `M ${a[0]} ${a[1]} L ${b[0]} ${b[1]}`,
    ticks: `M ${a[0] + nx} ${a[1] + ny} L ${a[0] - nx} ${a[1] - ny} M ${b[0] + nx} ${b[1] + ny} L ${b[0] - nx} ${b[1] - ny}`,
  };
}

const polyPath = (pts: [number, number][], close: boolean) => `M ${pts.map(([x, y]) => `${x} ${y}`).join(' L ')}${close ? ' Z' : ''}`;

export function SignsLayer({ signs, placed, k, strokePx, fsPx, width }: {
  signs: ViewSign[]; placed: Box[]; k: number; strokePx: number; fsPx: number; width: number;
}) {
  const focused = useSigns((st) => st.focused);
  const clearFocus = useSigns((st) => st.clearFocus);
  const [hover, setHover] = useState<string | null>(null);
  // The pulse ends by itself; the store forgets the request so a later one pulses again.
  useEffect(() => {
    if (!focused) return;
    const t = window.setTimeout(clearFocus, FOCUS_MS);
    return () => clearTimeout(t);
  }, [focused, clearFocus]);
  if (signs.length === 0) return null;
  const sw = strokePx * k;
  const fs = fsPx * k;
  const lh = fs * 1.55;
  const padX = fs * 0.55;
  const tipFsPx = fsPx * 0.9;
  const tipFs = tipFsPx * k;
  const dash = `${6 * k} ${4 * k}`;
  // The hovered sign's sentence, drawn last so it sits above every pill: under the sign's own pill, kept on the film.
  const tipAt = hover ? signs.findIndex((sg) => sg.id === hover) : -1;
  const tip = tipAt >= 0 ? (() => {
    const sg = signs[tipAt];
    const b = placed[tipAt];
    const lines = wrapText(sg.text);
    const w = padX * 2 + Math.max(...lines.map((l) => signTextWidth(l, tipFsPx, 400))) * k;
    const lh2 = tipFs * 1.4;
    const h = lh2 * lines.length + tipFs * 0.5;
    const x = Math.min(Math.max(0, b.x), Math.max(0, width - w));
    const y = b.y + b.h + 3 * k;
    return { sg, lines, x, y, w, h, lh2 };
  })() : null;
  const shape = (sg: ViewSign) => {
    const pts = sg.points;
    switch (sg.kind) {
      case 'polyline':
      case 'polygon': {
        const d = polyPath(pts, sg.kind === 'polygon');
        return (
          <>
            <path d={d} className={s.signCasing} strokeWidth={sw + 2 * k} strokeDasharray={dash} />
            <path d={d} className={s.signLine} strokeWidth={sw} strokeDasharray={dash} />
          </>
        );
      }
      case 'circle': {
        const [cx, cy] = pts[0];
        return (
          <>
            <circle cx={cx} cy={cy} r={sg.radius ?? 0} className={s.signCasing} strokeWidth={sw + 2 * k} strokeDasharray={dash} />
            <circle cx={cx} cy={cy} r={sg.radius ?? 0} className={s.signLine} strokeWidth={sw} strokeDasharray={dash} />
          </>
        );
      }
      case 'segment': {
        const { line, ticks } = segmentPath(pts[0], pts[pts.length - 1], k);
        return (
          <>
            <path d={`${line} ${ticks}`} className={s.signCasing} strokeWidth={sw + 2 * k} />
            <path d={line} className={s.signLine} strokeWidth={sw} />
            <path d={ticks} className={s.signLine} strokeWidth={sw} />
          </>
        );
      }
      case 'arrow': {
        const { line, head } = arrowPath(pts[0], pts[pts.length - 1], k);
        return (
          <>
            <path d={`${line} ${head}`} className={s.signCasing} strokeWidth={sw * 1.3 + 2 * k} />
            <path d={line} className={s.signLine} strokeWidth={sw * 1.3} />
            <path d={head} className={s.signLine} strokeWidth={sw * 1.3} />
          </>
        );
      }
      case 'band':
        return <path d={polyPath(pts, true)} className={s.signBand} strokeWidth={0.75 * k} />;
    }
  };
  return (
    <g data-testid="signs-layer">
      {signs.map((sg, i) => {
        const b = placed[i];
        const pulse = focused?.id === sg.id;
        // A pill the placer pushed away from its sign gets a thin leader back to the shape's box.
        const [sx0, sy0, sx1, sy1] = signBounds(sg);
        const pcx = b.x + b.w / 2;
        const pcy = b.y + b.h / 2;
        const tx = Math.min(Math.max(pcx, sx0), sx1);
        const ty = Math.min(Math.max(pcy, sy0), sy1);
        const far = Math.hypot(tx - pcx, ty - pcy) > b.h * 1.6;
        const lead = far ? { x: Math.min(Math.max(tx, b.x), b.x + b.w), y: ty < b.y ? b.y : ty > b.y + b.h ? b.y + b.h : pcy } : null;
        return (
          <g
            key={pulse ? `${sg.id}-${focused!.at}` : sg.id}
            className={`${s.sign} ${s.revealSign} ${pulse ? s.signPulse : ''}`}
            data-testid={`sign-${sg.id}`}
            data-sign-kind={sg.kind}
            data-finding={sg.finding_id}
            data-focused={pulse ? '1' : undefined}
            tabIndex={0}
            role="img"
            aria-label={`${signLabel(sg)}. ${sg.text}`}
            onPointerEnter={() => setHover(sg.id)}
            onPointerLeave={() => setHover((h) => (h === sg.id ? null : h))}
            onFocus={() => setHover(sg.id)}
            onBlur={() => setHover((h) => (h === sg.id ? null : h))}
          >
            <title>{sg.text}</title>
            {shape(sg)}
            {lead && (
              <>
                <line x1={lead.x} y1={lead.y} x2={tx} y2={ty} className={s.signCasing} strokeWidth={3 * k} />
                <line x1={lead.x} y1={lead.y} x2={tx} y2={ty} className={s.signLeader} strokeWidth={1.25 * k} data-testid={`sign-leader-${sg.id}`} />
              </>
            )}
            <g data-testid={`sign-label-${sg.id}`}>
              <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={b.h / 2} className={s.pill} />
              <text x={b.x + padX} y={b.y + lh * 0.69} className={s.signText} style={{ fontSize: fs }}>{signLabel(sg)}</text>
            </g>
          </g>
        );
      })}
      {tip && (
        <g data-testid={`sign-tip-${tip.sg.id}`} className={s.signTipBox}>
          <rect x={tip.x} y={tip.y} width={tip.w} height={tip.h} rx={4 * k} className={s.pill} />
          <text x={tip.x + padX} y={tip.y + tipFs * 1.15} className={s.signTip} style={{ fontSize: tipFs }}>
            {tip.lines.map((l, i) => <tspan key={i} x={tip.x + padX} dy={i === 0 ? 0 : tip.lh2}>{l}</tspan>)}
          </text>
        </g>
      )}
    </g>
  );
}
