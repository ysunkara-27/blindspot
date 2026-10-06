// Reading-room viewer (SPEC §5.1–§5.4). One transformed layer holds the film, the search-trace heatmap and an SVG
// overlay in image coordinates. Wheel zooms at the cursor (1×–6×), drag pans, double-click resets, click marks.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type Dispatch } from 'react';
import type { ReadAction, DraftMark } from '../read/readState';
import { clampView, clientToImage, fitView, imageToScreen, insideImage, visibleRect, zoomAt, type View } from './coords';
import type { TelemetryBuffer, Sample } from './telemetry';
import { MarkPopover } from './MarkPopover';
import { RevealLayer, type RevealView } from './RevealLayer';
import { AnatomyLayer } from './AnatomyLayer';
import type { Anatomy } from './anatomy';
import { ErrorBoundary } from '../app/ErrorBoundary';
import s from './Viewer.module.css';

const MAX_ZOOM = 6;
const PAD = 16;
const LOUPE_PX = 180;
const LOUPE_MAG = 2.5;
const DRAG_PX = 4;
const MARK_HIT_PX = 14;
const DBLCLICK_MS = 250;

export type ViewerProps = {
  caseId: string;
  imageUrl: string;
  width: number;
  height: number;
  marks: DraftMark[];
  selectedId: string | null;
  popoverId: string | null;
  dispatch: Dispatch<ReadAction>;
  canMark: boolean;
  markBlockedReason?: string;
  loupe: boolean;
  projector: boolean;
  telemetry: TelemetryBuffer;
  reveal: RevealView | null;
  onShown: () => void;
  /** "Show anatomy" (after submit only): off, or the fetched outlines and their state. */
  anatomy?: { on: boolean; status: 'pending' | 'error' | 'success'; data: Anatomy | null };
  onToggleAnatomy?: () => void;
};

type Gesture =
  | { kind: 'none' }
  | { kind: 'pending'; x0: number; y0: number; markId: string | null }
  | { kind: 'pan'; x0: number; y0: number; o0: View }
  | { kind: 'drag'; markId: string };

export function Viewer(p: ViewerProps) {
  const stageRef = useRef<HTMLDivElement>(null);
  const loupeRef = useRef<HTMLDivElement>(null);
  const loupeImgRef = useRef<HTMLImageElement>(null);
  const [stage, setStage] = useState({ w: 0, h: 0 });
  const [userView, setView] = useState<View | null>(null); // null = fit
  const [loaded, setLoaded] = useState(false);
  const [wl, setWl] = useState({ brightness: 100, contrast: 100, invert: false });
  const [panning, setPanning] = useState(false);
  const [zoomed, setZoomed] = useState(false); // quiets the "use the wheel" nudge once the reader has zoomed
  const [hoverZone, setHoverZone] = useState<string | null>(null);
  const gesture = useRef<Gesture>({ kind: 'none' });
  const overImage = useRef(false);
  const placeTimer = useRef<number | null>(null);
  const suppressClick = useRef(false);

  const fit = useMemo(() => fitView(stage.w, stage.h, p.width, p.height, PAD), [stage, p.width, p.height]);
  const view = userView ?? fit;
  const zoom = fit.scale > 0 ? view.scale / fit.scale : 1;

  // Latest values for native event handlers.
  const live = useRef({ view, fit, stage, p, zoom });
  useLayoutEffect(() => {
    live.current = { view, fit, stage, p, zoom };
  });

  const sample = useCallback((img?: { x: number; y: number }): Sample => {
    const { view: v, stage: st, p: pp, zoom: z } = live.current;
    const inside = img && insideImage(img, pp.width, pp.height);
    return {
      x: inside ? img.x : undefined, y: inside ? img.y : undefined, zoom: z,
      vp: visibleRect(st.w, st.h, v, pp.width, pp.height), loupe: pp.loupe,
    };
  }, []);

  // Stage size → fit.
  useLayoutEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setStage({ w: width, h: height });
      setView(null); // refit on resize
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // The viewer is remounted per attempt (ReadingRoom is keyed by attempt id), so no per-case reset is needed.

  // Loupe toggles are telemetry events.
  const firstLoupe = useRef(true);
  useEffect(() => {
    if (firstLoupe.current) { firstLoupe.current = false; return; }
    p.telemetry.push('loupe', sample());
    if (!p.loupe && loupeRef.current) loupeRef.current.style.display = 'none';
  }, [p.loupe, p.telemetry, sample]);

  // Wheel zoom (native listener: React's onWheel is passive and cannot preventDefault).
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const { view: v, fit: f } = live.current;
      const r = el.getBoundingClientRect();
      const factor = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015));
      const next = zoomAt(v, factor, e.clientX - r.left, e.clientY - r.top, f.scale, f.scale * MAX_ZOOM);
      const clamped = clampView(next, r.width, r.height, live.current.p.width, live.current.p.height);
      live.current.view = clamped;
      setView(clamped);
      live.current.zoom = clamped.scale / f.scale;
      if (clamped.scale !== v.scale) setZoomed(true);
      p.telemetry.push('wheel', sample(clientToImage(e.clientX, e.clientY, r, clamped)));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [p.telemetry, sample]);

  const resetView = useCallback(() => {
    setView(null);
    live.current.view = live.current.fit;
    live.current.zoom = 1;
    p.telemetry.push('wheel', sample());
  }, [p.telemetry, sample]);

  const markAt = (sx: number, sy: number): string | null => {
    let best: string | null = null;
    let bestD = MARK_HIT_PX;
    for (const m of p.marks) {
      const q = imageToScreen(m.x, m.y, view);
      const d = Math.hypot(q.x - sx, q.y - sy);
      if (d <= bestD) { best = m.mark_id; bestD = d; }
    }
    return best;
  };

  const updateLoupe = (sx: number, sy: number, img: { x: number; y: number }, show: boolean) => {
    const el = loupeRef.current;
    const im = loupeImgRef.current;
    if (!el || !im) return;
    if (!show) { el.style.display = 'none'; return; }
    const sc = view.scale * LOUPE_MAG;
    el.style.display = 'block';
    el.style.transform = `translate(${sx - LOUPE_PX / 2}px, ${sy - LOUPE_PX / 2}px)`;
    im.style.width = `${p.width * sc}px`;
    im.style.height = `${p.height * sc}px`;
    im.style.transform = `translate(${LOUPE_PX / 2 - img.x * sc}px, ${LOUPE_PX / 2 - img.y * sc}px)`;
  };

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest('[data-no-stage]')) return;
    const r = e.currentTarget.getBoundingClientRect();
    const sx = e.clientX - r.left;
    const sy = e.clientY - r.top;
    e.currentTarget.setPointerCapture(e.pointerId);
    const markId = p.canMark ? markAt(sx, sy) : null;
    gesture.current = { kind: 'pending', x0: sx, y0: sy, markId };
    p.telemetry.push('down', sample(clientToImage(e.clientX, e.clientY, r, view)));
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest('[data-no-stage]') && gesture.current.kind === 'none') {
      updateLoupe(0, 0, { x: 0, y: 0 }, false);
      return;
    }
    const r = e.currentTarget.getBoundingClientRect();
    const sx = e.clientX - r.left;
    const sy = e.clientY - r.top;
    const g = gesture.current;
    if (g.kind === 'pending' && Math.hypot(sx - g.x0, sy - g.y0) > DRAG_PX) {
      gesture.current = g.markId ? { kind: 'drag', markId: g.markId } : { kind: 'pan', x0: g.x0, y0: g.y0, o0: view };
      if (!g.markId) setPanning(true);
      if (g.markId) p.dispatch({ type: 'select', id: g.markId });
    }
    const cur = gesture.current;
    let v = view;
    if (cur.kind === 'pan') {
      v = clampView({ ...cur.o0, originX: cur.o0.originX + sx - cur.x0, originY: cur.o0.originY + sy - cur.y0 }, r.width, r.height, p.width, p.height);
      setView(v);
      live.current.view = v;
    }
    const img = clientToImage(e.clientX, e.clientY, r, v);
    const inside = insideImage(img, p.width, p.height);
    if (cur.kind === 'drag') {
      p.dispatch({ type: 'move', id: cur.markId, x: Math.min(p.width, Math.max(0, img.x)), y: Math.min(p.height, Math.max(0, img.y)) });
    }
    if (inside !== overImage.current) {
      overImage.current = inside;
      p.telemetry.push(inside ? 'enter' : 'leave', sample(img));
    }
    p.telemetry.push(cur.kind === 'pan' ? 'pan' : 'move', sample(img));
    updateLoupe(sx, sy, img, p.loupe && inside && cur.kind !== 'pan' && !p.popoverId && !p.reveal && loaded);
  };

  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    const g = gesture.current;
    if (g.kind === 'none') return;
    gesture.current = { kind: 'none' };
    setPanning(false);
    const r = e.currentTarget.getBoundingClientRect();
    p.telemetry.push('up', sample(clientToImage(e.clientX, e.clientY, r, live.current.view)));
    suppressClick.current = g.kind !== 'pending';
    if (g.kind === 'pending' && g.markId) {
      suppressClick.current = true;
      p.dispatch({ type: 'select', id: g.markId, popover: true });
    }
  };

  const onClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest('[data-no-stage]')) return;
    if (suppressClick.current) { suppressClick.current = false; return; }
    if (e.detail >= 2) {
      if (placeTimer.current) { clearTimeout(placeTimer.current); placeTimer.current = null; }
      return;
    }
    if (p.popoverId) { p.dispatch({ type: 'closePopover' }); return; }
    if (!p.canMark || p.reveal) return;
    const r = e.currentTarget.getBoundingClientRect();
    const img = clientToImage(e.clientX, e.clientY, r, view);
    if (!insideImage(img, p.width, p.height)) { p.dispatch({ type: 'select', id: null }); return; }
    // Wait out a possible double-click (which resets the view instead of marking).
    placeTimer.current = window.setTimeout(() => {
      placeTimer.current = null;
      p.dispatch({ type: 'place', x: img.x, y: img.y });
    }, DBLCLICK_MS);
  };

  const onDoubleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest('[data-no-stage]')) return;
    if (placeTimer.current) { clearTimeout(placeTimer.current); placeTimer.current = null; }
    resetView();
  };

  const onPointerLeave = () => {
    if (overImage.current) {
      overImage.current = false;
      p.telemetry.push('leave', sample());
    }
    updateLoupe(0, 0, { x: 0, y: 0 }, false);
  };

  const setWlLogged = (next: typeof wl) => {
    setWl(next);
    p.telemetry.push('wl', sample());
  };

  const boost = p.projector ? { b: 1.08, c: 1.3 } : { b: 1, c: 1 };
  const filter = `brightness(${(wl.brightness / 100) * boost.b}) contrast(${(wl.contrast / 100) * boost.c})${wl.invert ? ' invert(1)' : ''}`;
  const strokePx = p.projector ? 4 : 2;
  const k = 1 / view.scale; // image units per screen px
  const popMark = p.marks.find((m) => m.mark_id === p.popoverId);
  const popPos = popMark ? imageToScreen(popMark.x, popMark.y, view) : null;

  return (
    <div className={s.viewer}>
      <div
        ref={stageRef}
        className={`${s.stage} ${panning ? s.panning : ''} ${p.canMark && !p.reveal ? s.marking : ''}`}
        data-testid="stage"
        data-zoom={zoom.toFixed(3)}
        data-view={`${view.originX.toFixed(3)},${view.originY.toFixed(3)},${view.scale.toFixed(6)}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onPointerLeave={onPointerLeave}
        onClick={onClick}
        onDoubleClick={onDoubleClick}
      >
        <div
          className={s.layer}
          style={{ width: p.width, height: p.height, transform: `translate(${view.originX}px, ${view.originY}px) scale(${view.scale})` }}
        >
          <div className={s.film} />
          <img
            key={p.caseId}
            src={p.imageUrl}
            alt="Chest radiograph for this case"
            className={s.image}
            width={p.width}
            height={p.height}
            style={{ filter }}
            draggable={false}
            data-testid="film"
            onLoad={() => { setLoaded(true); p.onShown(); }}
          />
          {p.reveal && p.anatomy?.on && p.anatomy.data && (
            <AnatomyLayer anatomy={p.anatomy.data} width={p.width} height={p.height} k={k} hovered={hoverZone} onHover={setHoverZone} />
          )}
          {p.reveal && (
            <ErrorBoundary>
              <RevealLayer reveal={p.reveal} width={p.width} height={p.height} k={k} strokePx={strokePx} marks={p.marks} />
            </ErrorBoundary>
          )}
          <svg className={s.overlay} viewBox={`0 0 ${p.width} ${p.height}`} width={p.width} height={p.height} aria-hidden="true">
            {p.marks.map((m) => {
              const rm = p.reveal?.marks.find((x) => x.mark_id === m.mark_id);
              const sel = m.mark_id === p.selectedId;
              return (
                <g key={m.mark_id} data-mark-id={m.mark_id} className={s.mark} transform={`translate(${m.x} ${m.y})`}>
                  {rm?.result === 'false_positive' && (
                    <circle r={18 * k} className={`${s.overcallRing} ${s.settle}`} strokeWidth={strokePx * k} />
                  )}
                  <circle r={10 * k} className={s.markHalo} strokeWidth={(strokePx + 3) * k} />
                  <circle
                    r={10 * k}
                    className={s.markRing}
                    strokeWidth={(sel ? strokePx + 1.5 : strokePx) * k}
                    strokeDasharray={m.label ? undefined : `${4 * k} ${3 * k}`}
                  />
                  <circle r={1.8 * k} className={s.markDot} />
                  <text x={15 * k} y={-10 * k} className={s.markText} style={{ fontSize: (p.projector ? 18 : 13) * k, strokeWidth: 3 * k }}>
                    {m.mark_id}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>

        <div ref={loupeRef} className={s.loupe} style={{ width: LOUPE_PX, height: LOUPE_PX }} data-testid="loupe" aria-hidden="true">
          <img ref={loupeImgRef} src={p.imageUrl} alt="" className={s.loupeImg} style={{ filter }} draggable={false} />
          <span className={s.loupeCross} />
        </div>

        {!loaded && <div className={s.loading}>Loading film…</div>}
        {p.markBlockedReason && !p.reveal && <div className={s.notice}>{p.markBlockedReason}</div>}
        {loaded && p.canMark && !p.reveal && (p.marks.length === 0 || !zoomed) && (
          <div className={s.nudge} data-testid="nudge" aria-hidden="true">
            {p.marks.length === 0 && <span>Click the film to mark a finding</span>}
            {!zoomed && <span>Use the wheel to zoom</span>}
          </div>
        )}
        {p.reveal && p.anatomy?.on && (
          <div className={s.zoneName} data-testid="zone-name" aria-live="polite">
            {p.anatomy.status === 'pending' ? 'Loading anatomy…'
              : p.anatomy.status === 'error' || !p.anatomy.data?.zones.length ? 'Anatomy outlines are not available for this case.'
              : hoverZone ? (p.anatomy.data.zones.find((z) => z.id === hoverZone)?.name ?? '')
              : `Point at a zone to name it${p.anatomy.data.approximate ? ' · zones are approximate' : ''}`}
          </div>
        )}

        {popMark && popPos && (
          <MarkPopover
            mark={popMark}
            x={popPos.x}
            y={popPos.y}
            stageW={stage.w}
            stageH={stage.h}
            dispatch={p.dispatch}
          />
        )}

        <div className={s.tools} data-no-stage onPointerDown={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
          <span className={s.zoom} data-testid="zoom-readout">{zoom.toFixed(1)}×</span>
          <label className={s.slider}>
            <span>Brightness</span>
            <input type="range" min={40} max={180} value={wl.brightness} aria-label="Brightness"
              onChange={(e) => setWlLogged({ ...wl, brightness: Number(e.target.value) })} />
          </label>
          <label className={s.slider}>
            <span>Contrast</span>
            <input type="range" min={40} max={250} value={wl.contrast} aria-label="Contrast"
              onChange={(e) => setWlLogged({ ...wl, contrast: Number(e.target.value) })} />
          </label>
          <button type="button" className={`${s.tool} ${wl.invert ? s.toolOn : ''}`} aria-pressed={wl.invert}
            onClick={() => setWlLogged({ ...wl, invert: !wl.invert })}>Invert</button>
          <button type="button" className={s.tool} onClick={() => { setWlLogged({ brightness: 100, contrast: 100, invert: false }); resetView(); }}>
            Reset view
          </button>
          {p.reveal && p.onToggleAnatomy && (
            <button type="button" className={`${s.tool} ${p.anatomy?.on ? s.toolOn : ''}`} aria-pressed={!!p.anatomy?.on}
              onClick={p.onToggleAnatomy} data-testid="anatomy-toggle">
              {p.anatomy?.on ? 'Hide anatomy' : 'Show anatomy'}<kbd className={s.kbdTool}>A</kbd>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
