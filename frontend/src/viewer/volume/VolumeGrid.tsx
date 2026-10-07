// The 2×2 grid a volume opens in: axial, coronal, sagittal panes and an info panel. Each pane fits its slice, shows
// the learner's marks that sit on (or next to) that slice and, after submit, the expert outlines on it. The wheel
// over a pane scrolls that pane (handled by the stage's wheel listener through `data-pane`); a double-click opens the
// pane as the single-plane view where marking happens. No zoom or pan here: that is the single-plane view's job.
import { useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { ProvenanceBadge } from '../../app/ProvenanceBadge';
import { modalityDisplay } from '../../api/labels';
import type { DraftMark } from '../../read/readState';
import type { RevealFinding } from '../../types/contracts';
import { fitView, screenToImage, type View } from '../coords';
import { PLANE_DISPLAY, type VolumeNav } from './nav';
import { planeGeom, PLANES, sliceVisibility, voxelToDisplay, type Plane, type Voxel } from './planes';
import { SliceCanvas } from './SliceCanvas';
import { findingsOnSlice, ringsPath } from './sliceReveal';
import type { MaskVolume, Volume } from './volume';
import type { Window } from './window';
import s from '../Viewer.module.css';

export type PaneMove = { plane: Plane; slice: number; u: number; v: number; inside: boolean };

export function VolumeGrid({ volume, nav, lut, filter, marks, findings, mask, window: win, caseId, modality, sequence, provenance, revealed, onOpen, onMove, onLeave, strokePx }: {
  volume: Volume; nav: VolumeNav; lut: Uint8Array; filter: string; marks: DraftMark[];
  findings: RevealFinding[]; mask: MaskVolume | null; window: Window;
  caseId: string; modality: string; sequence?: string | null; provenance: unknown; revealed: boolean;
  onOpen: (plane: Plane) => void; onMove: (m: PaneMove) => void; onLeave: () => void; strokePx: number;
}) {
  const comps = findings.find((f) => f.components?.length)?.components ?? null;
  const [sz, sy, sx] = volume.spacing;
  return (
    <div className={s.grid} data-testid="volume-grid">
      {PLANES.map((plane) => (
        <Pane key={plane} plane={plane} volume={volume} slice={nav.slice[plane]} lut={lut} filter={filter} marks={marks}
          findings={findings} mask={mask} onOpen={onOpen} onMove={onMove} onLeave={onLeave} strokePx={strokePx} />
      ))}
      <div className={s.paneInfo} data-pane="info" data-testid="volume-info">
        <dl className={s.infoList}>
          <div><dt>Case</dt><dd>{caseId}</dd></div>
          <div><dt>Scan</dt><dd>{modalityDisplay(modality, 'short')}{sequence ? ` · ${sequence}` : ''}</dd></div>
          <div><dt>Voxel</dt><dd>{fmt(sx)} × {fmt(sy)} × {fmt(sz)} mm</dd></div>
          <div><dt>Size</dt><dd>{volume.shape[0]} slices · {volume.shape[2]} × {volume.shape[1]} px</dd></div>
          <div><dt>Window</dt><dd data-testid="info-window">W {Math.round(win.ww)} · L {Math.round(win.wc)}</dd></div>
        </dl>
        <ProvenanceBadge provenance={provenance} modality={modality} className={s.infoBadge} />
        {revealed && (
          <div className={s.infoKey} data-testid="grid-colour-key">
            <span className={s.key}><span className={s.keyCyan} /> Expert outline <span className={s.keyAmber} /> You</span>
            {comps && (
              <span className={s.compKey}>
                {comps.map((c, i) => (
                  <span key={c.label_value}><i style={{ opacity: 0.2 + i * 0.3 }} /> {c.name}</span>
                ))}
              </span>
            )}
          </div>
        )}
        <p className={s.infoHint}>Double-click a pane to read it. Scroll a pane to move through its slices.</p>
      </div>
    </div>
  );
}

const fmt = (v: number) => (Number.isInteger(v) ? v.toFixed(1) : String(Math.round(v * 100) / 100));

function Pane({ plane, volume, slice, lut, filter, marks, findings, mask, onOpen, onMove, onLeave, strokePx }: {
  plane: Plane; volume: Volume; slice: number; lut: Uint8Array; filter: string; marks: DraftMark[];
  findings: RevealFinding[]; mask: MaskVolume | null; onOpen: (plane: Plane) => void; onMove: (m: PaneMove) => void; onLeave: () => void; strokePx: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setBox({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const g = useMemo(() => planeGeom(volume, plane), [volume, plane]);
  const view: View = useMemo(() => fitView(box.w, box.h, g.W, g.H, 8), [box, g]);
  const k = 1 / view.scale;
  const shown = marks.flatMap((m) => {
    if (!m.voxel) return [];
    const d = voxelToDisplay(g, m.voxel as Voxel);
    const vis = sliceVisibility(d.slice, slice);
    return vis === 'hidden' ? [] : [{ ...m, dx: d.x, dy: d.y, ghost: vis === 'ghost' }];
  });
  const outlines = useMemo(() => (mask ? findingsOnSlice(findings, mask, g, slice) : []), [mask, findings, g, slice]);
  const style: CSSProperties = { width: g.W, height: g.H, transform: `translate(${view.originX}px, ${view.originY}px) scale(${view.scale})` };
  return (
    <div ref={ref} className={s.pane} data-pane={plane} data-testid={`pane-${plane}`} data-slice={slice}
      onDoubleClick={(e) => { e.stopPropagation(); onOpen(plane); }}
      onPointerMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect();
        const d = screenToImage(e.clientX - r.left, e.clientY - r.top, view);
        const inside = d.x >= 0 && d.y >= 0 && d.x <= g.W && d.y <= g.H;
        onMove({ plane, slice, u: d.x / g.ax, v: d.y / g.ay, inside });
      }}
      onPointerLeave={onLeave}
      title={`${PLANE_DISPLAY[plane]} · double-click to open`}
    >
      {box.w > 0 && (
        <div className={s.layer} style={style}>
          <div className={s.film} />
          <SliceCanvas volume={volume} plane={plane} slice={slice} lut={lut} className={s.image} style={{ filter }} />
          <svg className={s.overlay} viewBox={`0 0 ${g.W} ${g.H}`} width={g.W} height={g.H} aria-hidden="true">
            {outlines.map((f) => (
              <path key={f.finding_id} d={ringsPath(f.rings)} className={s.outline} strokeWidth={strokePx * k} fillRule="evenodd" data-testid={`pane-outline-${plane}-${f.finding_id}`} />
            ))}
            {shown.map((m) => (
              <g key={m.mark_id} transform={`translate(${m.dx} ${m.dy})`} opacity={m.ghost ? 0.45 : 1} data-testid={`pane-mark-${plane}-${m.mark_id}`}>
                <circle r={7 * k} className={s.markHalo} strokeWidth={4 * k} />
                <circle r={7 * k} className={s.markRing} strokeWidth={strokePx * k} />
                <circle r={1.5 * k} className={s.markDot} />
              </g>
            ))}
          </svg>
        </div>
      )}
      <span className={s.paneTag}>{PLANE_DISPLAY[plane]} · slice {slice + 1} of {g.n}</span>
    </div>
  );
}
