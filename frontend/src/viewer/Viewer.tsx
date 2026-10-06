// Reading-room viewer (SPEC §5.1–§5.4). One transformed layer holds the film, the search-trace heatmap and an SVG
// overlay in image coordinates. Wheel zooms at the cursor (1×–6×), drag pans, double-click resets, click marks.
// Round 3: the film sits between two strips of its own (prompts above, image controls below) so nothing overlaps its
// edge; the film is focusable and a keyboard crosshair places marks; the magnifier is off until asked for; the view
// refits when the reveal starts; the search trace has a legend, a toggle and "not visited" rings.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type Dispatch } from 'react';
import type { ReadAction, DraftMark, MarkLabel, PopoverMode } from '../read/readState';
import { labelDisplay } from '../api/labels';
import { clampView, clientToImage, fitView, imageToScreen, insideImage, visibleRect, zoomAt, type View } from './coords';
import type { TelemetryBuffer, Sample } from './telemetry';
import { MarkPopover } from './MarkPopover';
import { RevealLayer, type RevealView } from './RevealLayer';
import { AnatomyLayer } from './AnatomyLayer';
import { SearchExplainer, SEARCH_LEGEND } from './SearchExplainer';
import type { Anatomy } from './anatomy';
import { ErrorBoundary } from '../app/ErrorBoundary';
import s from './Viewer.module.css';

const MAX_ZOOM = 6;
const PAD = 12;
export const LOUPE_PX = 180;
const LOUPE_MAG = 2.5;
const DRAG_PX = 4;
const MARK_HIT_PX = 14;
const DBLCLICK_MS = 250;
const KEY_STEP_PX = 12;
const KEY_STEP_BIG_PX = 60;
const TIP_KEY = 'blindspot.magnifierTipSeen';

export type SearchUi = {
  /** "My search" toggle (remembered across cases). */
  on: boolean;
  onToggle: () => void;
  /** Display names of every review area the learner did not visit. */
  unvisited: string[];
  /** True when the unvisited areas are drawn as rings on the film (anatomy outlines available). */
  located: boolean;
};

export type ViewerProps = {
  caseId: string;
  imageUrl: string;
  width: number;
  height: number;
  marks: DraftMark[];
  selectedId: string | null;
  popoverId: string | null;
  popoverMode?: PopoverMode;
  /** Finding type picked in the rail: the next click places a mark with this label. */
  armed?: MarkLabel | null;
  dispatch: Dispatch<ReadAction>;
  canMark: boolean;
  markBlockedReason?: string;
  /** The magnifier (telemetry field `loupe`). */
  loupe: boolean;
  onToggleLoupe?: () => void;
  projector: boolean;
  telemetry: TelemetryBuffer;
  reveal: RevealView | null;
  onShown: () => void;
  /** "Show anatomy" (after submit only): off, or the fetched outlines and their state. */
  anatomy?: { on: boolean; status: 'pending' | 'error' | 'success'; data: Anatomy | null };
  onToggleAnatomy?: () => void;
  /** Search trace controls and legend (after submit only). */
  search?: SearchUi;
};

type Gesture =
  | { kind: 'none' }
  | { kind: 'pending'; x0: number; y0: number; markId: string | null }
  | { kind: 'pan'; x0: number; y0: number; o0: View }
  | { kind: 'drag'; markId: string };

function tipSeen(): boolean {
  try { return localStorage.getItem(TIP_KEY) === '1'; } catch { return true; }
}

export function Viewer(p: ViewerProps) {
  const stageRef = useRef<HTMLDivElement>(null);
  const loupeRef = useRef<HTMLDivElement>(null);
  const loupeImgRef = useRef<HTMLImageElement>(null);
  const armedRef = useRef<HTMLDivElement>(null);
  const [stage, setStage] = useState({ w: 0, h: 0 });
  const [userView, setView] = useState<View | null>(null); // null = fit
  const [loaded, setLoaded] = useState(false);
  const [wl, setWl] = useState({ brightness: 100, contrast: 100, invert: false });
  const [panning, setPanning] = useState(false);
  const [zoomed, setZoomed] = useState(false); // quiets the "use the wheel" nudge once the reader has zoomed
  const [hoverZone, setHoverZone] = useState<string | null>(null);
  const [kbd, setKbd] = useState<{ x: number; y: number } | null>(null); // keyboard crosshair, image px
  const [fitting, setFitting] = useState(false); // the one eased refit, when the reveal starts
  const [explain, setExplain] = useState(false);
  const [tip, setTip] = useState(false);
  const gesture = useRef<Gesture>({ kind: 'none' });
  const overImage = useRef(false);
  const placeTimer = useRef<number | null>(null);
  const suppressClick = useRef(false);
  const lastMove = useRef(-Infinity); // last zoom or pan by the learner (performance.now)

  const fit = useMemo(() => fitView(stage.w, stage.h, p.width, p.height, PAD), [stage, p.width, p.height]);
  const view = userView ?? fit;
  const zoom = fit.scale > 0 ? view.scale / fit.scale : 1;

  // Latest values for native event handlers.
  const live = useRef({ view, fit, stage, p, zoom, userView, kbd });
  useLayoutEffect(() => {
    live.current = { view, fit, stage, p, zoom, userView, kbd };
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
      setStage((st) => (Math.abs(st.w - width) < 0.5 && Math.abs(st.h - height) < 0.5 ? st : { w: width, h: height }));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // Refit when the stage really changes size (the strips around it have fixed heights, so the reveal does not).
  const sized = useRef({ w: 0, h: 0 });
  useLayoutEffect(() => {
    if (sized.current.w !== stage.w || sized.current.h !== stage.h) {
      sized.current = stage;
      setView(null);
    }
  }, [stage]);
  // The viewer is remounted per attempt (ReadingRoom is keyed by attempt id), so no per-case reset is needed.

  const setLoupeAt = useCallback((sx: number, sy: number, img: { x: number; y: number }, show: boolean) => {
    const el = loupeRef.current;
    const im = loupeImgRef.current;
    if (!el || !im) return;
    if (!show) { el.style.display = 'none'; return; }
    const { view: v, p: pp } = live.current;
    const sc = v.scale * LOUPE_MAG;
    el.style.display = 'block';
    el.style.transform = `translate(${sx - LOUPE_PX / 2}px, ${sy - LOUPE_PX / 2}px)`;
    im.style.width = `${pp.width * sc}px`;
    im.style.height = `${pp.height * sc}px`;
    im.style.transform = `translate(${LOUPE_PX / 2 - img.x * sc}px, ${LOUPE_PX / 2 - img.y * sc}px)`;
  }, []);
  const setArmedTagAt = useCallback((sx: number, sy: number, show: boolean) => {
    const el = armedRef.current;
    if (!el) return;
    if (!show) { el.style.display = 'none'; return; }
    el.style.display = 'block';
    // Beside the cursor; below the lens when the magnifier is on, so it never covers the magnified view.
    el.style.transform = live.current.p.loupe
      ? `translate(${sx}px, ${sy + LOUPE_PX / 2 + 8}px) translateX(-50%)`
      : `translate(${sx + 16}px, ${sy + 18}px)`;
  }, []);

  // Magnifier toggles are telemetry events. The first time it is turned on, a short tip says what it does.
  const [prevLoupe, setPrevLoupe] = useState(p.loupe);
  if (prevLoupe !== p.loupe) {
    setPrevLoupe(p.loupe);
    setTip(p.loupe && !tipSeen());
  }
  const firstLoupe = useRef(true);
  useEffect(() => {
    if (firstLoupe.current) { firstLoupe.current = false; return; }
    p.telemetry.push('loupe', sample());
    if (!p.loupe) setLoupeAt(0, 0, { x: 0, y: 0 }, false);
    else { try { localStorage.setItem(TIP_KEY, '1'); } catch { /* storage blocked: the tip may show again */ } }
  }, [p.loupe, p.telemetry, sample, setLoupeAt]);
  useEffect(() => {
    if (!tip) return;
    const off = () => setTip(false);
    const t = window.setTimeout(off, 9000);
    const arm = window.setTimeout(() => {
      window.addEventListener('pointerdown', off, true);
      window.addEventListener('keydown', off, true);
    }, 0);
    return () => {
      clearTimeout(t);
      clearTimeout(arm);
      window.removeEventListener('pointerdown', off, true);
      window.removeEventListener('keydown', off, true);
    };
  }, [tip]);

  useEffect(() => { if (!p.armed) setArmedTagAt(0, 0, false); }, [p.armed, setArmedTagAt]);

  const applyView = useCallback((next: View | null) => {
    const { fit: f } = live.current;
    live.current.view = next ?? f;
    live.current.userView = next;
    live.current.zoom = (next ?? f).scale / f.scale;
    setFitting(false);
    setView(next);
  }, []);

  // Wheel zoom (native listener: React's onWheel is passive and cannot preventDefault).
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if ((e.target as HTMLElement).closest('[data-no-stage]')) return;
      e.preventDefault();
      const { view: v, fit: f } = live.current;
      const r = el.getBoundingClientRect();
      const factor = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015));
      const next = zoomAt(v, factor, e.clientX - r.left, e.clientY - r.top, f.scale, f.scale * MAX_ZOOM);
      const clamped = clampView(next, r.width, r.height, live.current.p.width, live.current.p.height);
      lastMove.current = performance.now();
      applyView(clamped);
      if (clamped.scale !== v.scale) setZoomed(true);
      p.telemetry.push('wheel', sample(clientToImage(e.clientX, e.clientY, r, clamped)));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [p.telemetry, sample, applyView]);

  const resetView = useCallback(() => {
    applyView(null);
    p.telemetry.push('wheel', sample());
  }, [p.telemetry, sample, applyView]);

  /** Zoom about a stage point (default: the centre). Used by the + / − buttons and keys. */
  const zoomBy = useCallback((factor: number, at?: { x: number; y: number }) => {
    const { view: v, fit: f, stage: st, p: pp } = live.current;
    const ax = at?.x ?? st.w / 2;
    const ay = at?.y ?? st.h / 2;
    const next = clampView(zoomAt(v, factor, ax, ay, f.scale, f.scale * MAX_ZOOM), st.w, st.h, pp.width, pp.height);
    lastMove.current = performance.now();
    applyView(next.scale <= f.scale * 1.001 ? null : next);
    if (next.scale !== v.scale) setZoomed(true);
    pp.telemetry.push('wheel', sample());
  }, [applyView, sample]);

  // The reveal starts with the whole film in view: if the learner was zoomed in or panned away, ease back to fit —
  // unless they are moving the film right now (their hand wins).
  const revealed = !!p.reveal;
  useEffect(() => {
    if (!revealed || !live.current.userView) return;
    if (gesture.current.kind !== 'none' || performance.now() - lastMove.current < 400) return;
    applyView(null);
    setFitting(true);
    const t = window.setTimeout(() => setFitting(false), 500);
    return () => clearTimeout(t);
  }, [revealed, applyView]);

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

  const canPlace = p.canMark && !p.reveal;
  const popMark = p.marks.find((m) => m.mark_id === p.popoverId);
  const popPos = popMark ? imageToScreen(popMark.x, popMark.y, view) : null;
  const lensOn = p.loupe && canPlace && loaded;

  // While a popover is open the lens stays on its mark (it does not chase the cursor into the popover).
  const pinX = popPos?.x;
  const pinY = popPos?.y;
  const pinIx = popMark?.x;
  const pinIy = popMark?.y;
  useLayoutEffect(() => {
    if (pinX === undefined || pinY === undefined || pinIx === undefined || pinIy === undefined || !lensOn) return;
    setLoupeAt(pinX, pinY, { x: pinIx, y: pinIy }, true);
    return () => setLoupeAt(0, 0, { x: 0, y: 0 }, false);
  }, [pinX, pinY, pinIx, pinIy, lensOn, setLoupeAt]);

  // A keyboard reader gets the film back when the popover closes.
  const hadPopover = useRef(false);
  useEffect(() => {
    if (hadPopover.current && !p.popoverId && live.current.kbd) stageRef.current?.focus({ preventScroll: true });
    hadPopover.current = !!p.popoverId;
  }, [p.popoverId]);

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
      if (!p.popoverId) setLoupeAt(0, 0, { x: 0, y: 0 }, false);
      setArmedTagAt(0, 0, false);
      return;
    }
    if (kbd) setKbd(null); // the pointer takes over from the keyboard crosshair
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
      lastMove.current = performance.now();
      applyView(v);
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
    if (!p.popoverId) setLoupeAt(sx, sy, img, lensOn && inside && cur.kind !== 'pan');
    setArmedTagAt(sx, sy, !!p.armed && canPlace && inside && cur.kind === 'none' && !p.popoverId);
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
    if (!canPlace) return;
    const r = e.currentTarget.getBoundingClientRect();
    const img = clientToImage(e.clientX, e.clientY, r, view);
    if (!insideImage(img, p.width, p.height)) { p.dispatch({ type: 'select', id: null }); return; }
    setArmedTagAt(0, 0, false);
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
    if (!p.popoverId) setLoupeAt(0, 0, { x: 0, y: 0 }, false);
    setArmedTagAt(0, 0, false);
  };

  // Keyboard: arrows move a crosshair over the film (Shift = larger steps), Space or Enter places a mark there,
  // + and − zoom. The crosshair counts as the cursor for the search trace.
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === '+' || e.key === '=' || e.key === '-' || e.key === '_') {
      e.preventDefault();
      e.stopPropagation();
      const at = kbd ? imageToScreen(kbd.x, kbd.y, view) : undefined;
      zoomBy(e.key === '-' || e.key === '_' ? 1 / 1.25 : 1.25, at);
      return;
    }
    if (!canPlace || !loaded) return;
    const centre = () => {
      const [x0, y0, x1, y1] = visibleRect(stage.w, stage.h, view, p.width, p.height);
      return { x: (x0 + x1) / 2, y: (y0 + y1) / 2 };
    };
    const dir: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    if (dir[e.key]) {
      e.preventDefault();
      e.stopPropagation();
      const step = (e.shiftKey ? KEY_STEP_BIG_PX : KEY_STEP_PX) / view.scale;
      const from = kbd ?? centre();
      const next = kbd
        ? { x: Math.min(p.width, Math.max(0, from.x + dir[e.key][0] * step)), y: Math.min(p.height, Math.max(0, from.y + dir[e.key][1] * step)) }
        : from; // the first arrow press only shows the crosshair
      // Keep the crosshair on screen when zoomed in.
      const q = imageToScreen(next.x, next.y, view);
      const m = 36;
      const dx = q.x < m ? m - q.x : q.x > stage.w - m ? stage.w - m - q.x : 0;
      const dy = q.y < m ? m - q.y : q.y > stage.h - m ? stage.h - m - q.y : 0;
      if ((dx || dy) && userView) applyView(clampView({ ...view, originX: view.originX + dx, originY: view.originY + dy }, stage.w, stage.h, p.width, p.height));
      setKbd(next);
      p.telemetry.push('move', sample(next));
      const q2 = imageToScreen(next.x, next.y, live.current.view);
      if (!p.popoverId) setLoupeAt(q2.x, q2.y, next, lensOn);
      return;
    }
    if (e.key === ' ' || (e.key === 'Enter' && kbd)) {
      e.preventDefault();
      e.stopPropagation();
      if (p.popoverId) { p.dispatch({ type: 'closePopover' }); return; }
      if (!kbd) { setKbd(centre()); return; }
      p.telemetry.push('down', sample(kbd));
      p.dispatch({ type: 'place', x: kbd.x, y: kbd.y });
      return;
    }
    if (e.key === 'Escape' && kbd && !p.armed && !p.selectedId) {
      setKbd(null);
      setLoupeAt(0, 0, { x: 0, y: 0 }, false);
    }
  };

  const setWlLogged = (next: typeof wl) => {
    setWl(next);
    p.telemetry.push('wl', sample());
  };

  const boost = p.projector ? { b: 1.08, c: 1.3 } : { b: 1, c: 1 };
  const filter = `brightness(${(wl.brightness / 100) * boost.b}) contrast(${(wl.contrast / 100) * boost.c})${wl.invert ? ' invert(1)' : ''}`;
  const strokePx = p.projector ? 4 : 2;
  const k = 1 / view.scale; // image units per screen px
  const kbdPos = kbd ? imageToScreen(kbd.x, kbd.y, view) : null;
  const armedName = p.armed ? labelDisplay(p.armed) : '';
  const anatomyOn = !!p.reveal && !!p.anatomy?.on;
  const zoneText = !anatomyOn ? '' : p.anatomy!.status === 'pending' ? 'Loading anatomy…'
    : p.anatomy!.status === 'error' || !p.anatomy!.data?.zones.length ? 'Anatomy outlines are not available for this case.'
    : hoverZone ? (p.anatomy!.data.zones.find((z) => z.id === hoverZone)?.name ?? '')
    : `Point at a zone to name it${p.anatomy!.data.approximate ? ' · zones are approximate' : ''}`;
  const hasTrace = !!p.reveal?.heatmapUrl;

  return (
    <div className={s.viewer}>
      {/* Strip above the film: what to do next before submit; the layer toggles after. Fixed height, so the film never jumps. */}
      <div className={s.topStrip} data-testid="viewer-strip">
        <div className={s.stripLeft}>
          {!p.reveal && p.markBlockedReason ? (
            <span className={s.stripNote} data-testid="mark-blocked">{p.markBlockedReason}</span>
          ) : !p.reveal && p.armed && p.canMark ? (
            <span className={s.stripArmed} data-testid="armed-prompt">
              <strong>{armedName}</strong> — click the film where you see it
              <button type="button" className={s.stripLink} onClick={() => p.dispatch({ type: 'disarm' })}>Cancel <kbd className={s.kbdTool}>Esc</kbd></button>
            </span>
          ) : loaded && canPlace && (p.marks.length === 0 || !zoomed) ? (
            <span className={s.nudge} data-testid="nudge" aria-hidden="true">
              {p.marks.length === 0 && <span>Pick what you see on the right, then click where it is</span>}
              {!zoomed && <span>Use the wheel to zoom</span>}
            </span>
          ) : anatomyOn ? (
            <span className={s.zoneName} data-testid="zone-name" aria-live="polite">{zoneText}</span>
          ) : p.reveal ? (
            <span className={s.key} data-testid="reveal-key">
              <span className={s.keyCyan} /> Expert outline <span className={s.keyAmber} /> You
            </span>
          ) : null}
        </div>
        {p.reveal && (
          <div className={s.stripRight}>
            {p.search && (
              <button type="button" className={`${s.tool} ${p.search.on ? s.toolOn : ''}`} aria-pressed={p.search.on}
                onClick={p.search.onToggle} data-testid="search-toggle" title="Show or hide where your cursor spent time">
                My search: {p.search.on ? 'on' : 'off'}
              </button>
            )}
            {p.onToggleAnatomy && (
              <button type="button" className={`${s.tool} ${p.anatomy?.on ? s.toolOn : ''}`} aria-pressed={!!p.anatomy?.on}
                onClick={p.onToggleAnatomy} data-testid="anatomy-toggle">
                {p.anatomy?.on ? 'Hide anatomy' : 'Show anatomy'}<kbd className={s.kbdTool}>A</kbd>
              </button>
            )}
          </div>
        )}
      </div>

      <div
        ref={stageRef}
        className={`${s.stage} ${panning ? s.panning : ''} ${canPlace ? s.marking : ''}`}
        data-testid="stage"
        data-tour="film"
        data-zoom={zoom.toFixed(3)}
        data-view={`${view.originX.toFixed(3)},${view.originY.toFixed(3)},${view.scale.toFixed(6)}`}
        data-armed={p.armed ?? ''}
        tabIndex={0}
        role="application"
        aria-label={canPlace
          ? 'Chest radiograph. Arrow keys move a crosshair, Shift for larger steps. Space places a mark. Plus and minus zoom.'
          : 'Chest radiograph. Plus and minus zoom.'}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onPointerLeave={onPointerLeave}
        onClick={onClick}
        onDoubleClick={onDoubleClick}
        onKeyDown={onKeyDown}
      >
        <div
          className={`${s.layer} ${fitting ? s.fitting : ''}`}
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
          {anatomyOn && p.anatomy!.data && (
            <AnatomyLayer anatomy={p.anatomy!.data} width={p.width} height={p.height} k={k} hovered={hoverZone} onHover={setHoverZone} />
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
              const unfinished = !m.label || m.confidence == null;
              return (
                <g key={m.mark_id} data-mark-id={m.mark_id} data-label={m.label ?? ''} className={s.mark} transform={`translate(${m.x} ${m.y})`}>
                  {rm?.result === 'false_positive' && (
                    <circle r={18 * k} className={`${s.overcallRing} ${s.settle}`} strokeWidth={strokePx * k} />
                  )}
                  <circle r={10 * k} className={s.markHalo} strokeWidth={(strokePx + 3) * k} />
                  <circle
                    r={10 * k}
                    className={s.markRing}
                    strokeWidth={(sel ? strokePx + 1.5 : strokePx) * k}
                    strokeDasharray={unfinished && !p.reveal ? `${4 * k} ${3 * k}` : undefined}
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

        {/* The armed finding rides with the cursor. */}
        <div ref={armedRef} className={s.armedTag} data-testid="armed-cursor" aria-hidden="true">{armedName}</div>

        {kbdPos && canPlace && (
          <div className={s.crosshair} style={{ transform: `translate(${kbdPos.x}px, ${kbdPos.y}px)` }} data-testid="crosshair"
            data-x={kbd!.x.toFixed(1)} data-y={kbd!.y.toFixed(1)} aria-hidden="true">
            {p.armed && <span className={s.crosshairTag}>{armedName}</span>}
          </div>
        )}

        {!loaded && <div className={s.loading}>Loading film…</div>}

        {/* On-film legend for the layers that are on. */}
        {p.reveal && ((p.search && p.search.on) || anatomyOn) && (
          <div className={s.legend} data-no-stage data-testid="film-legend" onPointerDown={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
            {p.search?.on && (
              <div className={s.legendChip} data-testid="search-legend">
                <span className={s.legendSwatch} aria-hidden="true" />
                <span>
                  {hasTrace ? SEARCH_LEGEND : 'No cursor movement was recorded on this film'}
                  {' · '}
                  <button type="button" className={s.legendLink} onClick={() => setExplain(true)} data-testid="search-what">What is this?</button>
                  {p.search.unvisited.length > 0 && (
                    <span className={s.legendLine} data-testid="search-unvisited">
                      <span className={s.legendRing} aria-hidden="true" />
                      {p.search.located ? 'Dashed ring: a review area you did not visit' : `Not visited: ${p.search.unvisited.join(', ')}`}
                    </span>
                  )}
                </span>
              </div>
            )}
            {anatomyOn && p.anatomy!.status === 'success' && !!p.anatomy!.data?.zones.length && (
              <div className={s.legendChip} data-testid="anatomy-legend">
                <span>
                  <svg className={s.legendKey} viewBox="0 0 22 8" aria-hidden="true">
                    <line x1="1" y1="4" x2="21" y2="4" stroke="rgba(236,241,245,0.85)" strokeWidth="4" strokeLinecap="round" />
                    <line x1="1" y1="4" x2="21" y2="4" stroke="#07090b" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  Zone
                  <svg className={`${s.legendKey} ${s.legendGap}`} viewBox="0 0 22 8" aria-hidden="true">
                    <line x1="1" y1="4" x2="21" y2="4" stroke="rgba(236,241,245,0.85)" strokeWidth="4" strokeDasharray="5 4" />
                    <line x1="1" y1="4" x2="21" y2="4" stroke="#07090b" strokeWidth="2" strokeDasharray="5 4" />
                  </svg>
                  Review area (where findings hide){p.anatomy!.data.approximate ? ' · approximate' : ''}
                </span>
              </div>
            )}
          </div>
        )}

        {popMark && popPos && (
          <MarkPopover
            mark={popMark}
            mode={p.popoverMode ?? 'full'}
            x={popPos.x}
            y={popPos.y}
            stageW={stage.w}
            stageH={stage.h}
            clear={lensOn ? LOUPE_PX / 2 : 34}
            dispatch={p.dispatch}
          />
        )}
      </div>

      {/* Image controls: their own strip under the film. */}
      <div className={s.tools} data-tour="controls" data-testid="viewer-tools">
        <span className={s.toolGroup}>
          <span className={s.toolLabel}>Zoom</span>
          <button type="button" className={s.toolSq} aria-label="Zoom out" title="Zoom out (−)" onClick={() => zoomBy(1 / 1.25)} disabled={zoom <= 1.001} data-testid="zoom-out">−</button>
          <span className={s.zoom} data-testid="zoom-readout">{zoom.toFixed(1)}×</span>
          <button type="button" className={s.toolSq} aria-label="Zoom in" title="Zoom in (+)" onClick={() => zoomBy(1.25)} disabled={zoom >= MAX_ZOOM - 0.001} data-testid="zoom-in">+</button>
        </span>
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
          onClick={() => setWlLogged({ ...wl, invert: !wl.invert })} data-testid="invert-toggle">Invert: {wl.invert ? 'on' : 'off'}</button>
        <button type="button" className={s.tool} data-testid="reset-view" onClick={() => { setWlLogged({ brightness: 100, contrast: 100, invert: false }); resetView(); }}>
          Reset view
        </button>
        <span className={s.toolSpacer} />
        {p.onToggleLoupe && (
          <span className={s.tipAnchor}>
            <button type="button" className={`${s.tool} ${p.loupe ? s.toolOn : ''}`} aria-pressed={p.loupe} onClick={p.onToggleLoupe}
              data-testid="loupe-toggle" data-tour="magnifier" title="Magnifier: a 2.5× lens that follows your cursor (M)" aria-describedby={tip ? 'magnifier-tip' : undefined}>
              <span className={s.dot} aria-hidden="true" />{p.loupe ? 'Magnifier on' : 'Magnifier off'}<kbd className={s.kbdTool}>M</kbd>
            </button>
            {tip && (
              <span className={s.tip} role="tooltip" id="magnifier-tip" data-testid="magnifier-tip">
                The magnifier is a 2.5× lens that follows your cursor over the film. Use it for fine detail; press <kbd className={s.kbdTool}>M</kbd> to put it away.
              </span>
            )}
          </span>
        )}
      </div>

      {explain && <SearchExplainer onClose={() => setExplain(false)} />}
    </div>
  );
}
