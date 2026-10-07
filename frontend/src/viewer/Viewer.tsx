// Reading-room viewer (SPEC §5.1–§5.4). One transformed layer holds the film, the search-trace heatmap and an SVG
// overlay in image coordinates. Wheel zooms at the cursor (1×–6×), drag pans, double-click resets, click marks.
// Round 3: the film sits between two strips of its own (prompts above, image controls below) so nothing overlaps its
// edge; the film is focusable and a keyboard crosshair places marks; the magnifier is off until asked for; the view
// refits when the reveal starts; the search trace has a legend, a toggle and "not visited" rings.
// Volumes (CT / MR, docs/VOLUMETRIC_PLAN.md): the same room, with the volume inside the film area. It opens as a 2×2
// grid (axial, coronal, sagittal, info); a double-click on a pane opens the single-plane view where marking happens.
// The current slice is painted to a canvas through the window LUT; "image px" are the slice's display px, so the one
// screen transform (coords.ts) serves pixels, marks and outlines unchanged. Marks carry plane, slice and voxel.
// A caliper measures mass-like marks in mm (X-ray: in px). An X-ray case takes none of these paths.
// Round 5 (clinician feedback): the tools sit next to the magnifier as one segmented control — Point · Draw · Caliper.
// Draw traces a free outline (read/stroke.ts) that becomes a mark with a polygon; "My search" starts off; the reveal
// draws the radiologists' signs (SignsLayer, toggle "Signs" / S) and an outline verdict chip beside a drawn mark.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type Dispatch } from 'react';
import type { ReadAction, DraftMark, MarkLabel, PopoverMode } from '../read/readState';
import { TOOLS, type CaliperDraft, type Tool } from '../read/tools';
import { clampPolygon, finishStroke, polygonPath, type Pt } from '../read/stroke';
import { signSlice, signsOnView, useSigns } from './signs';
import { labelDisplay } from '../api/labels';
import type { TelemetryEvent } from '../types/contracts';
import { clampView, clientToImage, displayToPlane, fitView, imageToScreen, insideImage, visibleRect, zoomAt, type View } from './coords';
import type { TelemetryBuffer, Sample } from './telemetry';
import { MarkPopover } from './MarkPopover';
import { RevealLayer, type RevealView } from './RevealLayer';
import { AnatomyLayer } from './AnatomyLayer';
import { SearchExplainer, SEARCH_LEGEND } from './SearchExplainer';
import type { Anatomy } from './anatomy';
import { densityFromTelemetry, densityToDataUrl } from './heatmap';
import { ErrorBoundary } from '../app/ErrorBoundary';
import { DwellBar } from './volume/DwellBar';
import { fmtMm, type SliceDwell } from './volume/dwell';
import { PLANE_DISPLAY, setSlice, showGrid, showPlane, stepSlice, wheelNotches, type VolumeNav } from './volume/nav';
import { displayLengthMm, displayToInPlane, planeGeom, PLANES, sliceVisibility, voxelToDisplay, type Plane, type PlaneGeom, type Voxel } from './volume/planes';
import { SliceCanvas } from './volume/SliceCanvas';
import { anatomyOnSlice, findingsOnSlice, findingValues, ringsPath } from './volume/sliceReveal';
import { VolumeGrid, type PaneMove } from './volume/VolumeGrid';
import type { MaskVolume, Volume } from './volume/volume';
import { dragWindow, windowLut, type Window } from './volume/window';
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
const DEFAULT_PRESET = 'Default';
const VERDICT_TEXT: Record<string, string> = { on_target: 'On target', partly: 'Partly on it', too_broad: 'Too broad' };

export type SearchUi = {
  /** "My search" toggle (remembered across cases). */
  on: boolean;
  onToggle: () => void;
  /** Display names of every review area the learner did not visit. */
  unvisited: string[];
  /** True when the unvisited areas are drawn as rings on the film (anatomy outlines available). */
  located: boolean;
};

/** A CT / MR case: the volume lives inside the film area. */
export type VolumeUi = {
  meta: { shape: number[]; spacing: number[]; window: Window; presets?: { name: string; wc: number; ww: number }[] | null; sequence?: string | null };
  /** Decoded voxels (null while loading or on error). */
  data: Volume | null;
  status: 'pending' | 'error' | 'success';
  error?: string | null;
  modality: string;
  provenance?: unknown;
  nav: VolumeNav;
  setNav: (f: (n: VolumeNav) => VolumeNav) => void;
  /** After submit only: the label volume and the names of its anatomy values. */
  mask?: MaskVolume | null;
  maskNames?: Record<string, string>;
  sliceDwell?: SliceDwell[] | null;
  findingSlicesViewed?: Record<string, boolean> | null;
  /** The telemetry that was submitted, for the cursor splats on each slice. */
  submittedTelemetry?: TelemetryEvent[];
};

/** The film tools (Point · Draw · Caliper) and the caliper draft (volumes: the size step; X-ray: a px ruler). */
export type CaliperUi = {
  tool: Tool;
  setTool: (t: Tool) => void;
  draft: CaliperDraft | null;
  setDraft: (c: CaliperDraft | null) => void;
  /** Volumes: the mark being measured, named in the strip. */
  forMark?: string | null;
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
  /** CT / MR only. */
  volume?: VolumeUi;
  caliper?: CaliperUi;
  /** Read-only (case review): no marking, no caliper, no telemetry of note. */
  readOnly?: boolean;
};

type Gesture =
  | { kind: 'none' }
  | { kind: 'pending'; x0: number; y0: number; markId: string | null }
  | { kind: 'pan'; x0: number; y0: number; o0: View }
  | { kind: 'drag'; markId: string }
  | { kind: 'caliper'; x0: number; y0: number }
  | { kind: 'draw'; pts: Pt[] }
  | { kind: 'wl'; x0: number; y0: number; w0: Window };

/** Point-in-polygon (even-odd), image px. */
function insidePolygon(x: number, y: number, poly: Pt[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function tipSeen(): boolean {
  try { return localStorage.getItem(TIP_KEY) === '1'; } catch { return true; }
}

/** A mark as drawn on the current view: display px, and for volumes how near its slice is. */
type ViewMark = DraftMark & { vis: 'full' | 'ghost' };

export function Viewer(p: ViewerProps) {
  const stageRef = useRef<HTMLDivElement>(null);
  const loupeRef = useRef<HTMLDivElement>(null);
  const loupeImgRef = useRef<HTMLImageElement>(null);
  const loupeCanvasRef = useRef<HTMLCanvasElement>(null);
  const armedRef = useRef<HTMLDivElement>(null);
  const [stage, setStage] = useState({ w: 0, h: 0 });
  const [userView, setView] = useState<View | null>(null); // null = fit
  const [imgLoaded, setLoaded] = useState(false);
  const [wl, setWl] = useState({ brightness: 100, contrast: 100, invert: false });
  const [panning, setPanning] = useState(false);
  const [zoomed, setZoomed] = useState(false); // quiets the "use the wheel" nudge once the reader has zoomed
  const [hoverZone, setHoverZone] = useState<string | null>(null);
  const [kbd, setKbd] = useState<{ x: number; y: number } | null>(null); // keyboard crosshair, image px
  const [fitting, setFitting] = useState(false); // the one eased refit, when the reveal starts
  const [explain, setExplain] = useState(false);
  const [tip, setTip] = useState(false);
  const [stroke, setStroke] = useState<Pt[] | null>(null); // the outline being traced (Draw tool), image px
  const signsVisible = useSigns((st) => st.visible);
  const toggleSigns = useSigns((st) => st.toggle);
  const focusedSign = useSigns((st) => st.focused);
  const gesture = useRef<Gesture>({ kind: 'none' });
  const overImage = useRef(false);
  const placeTimer = useRef<number | null>(null);
  const suppressClick = useRef(false);
  const lastMove = useRef(-Infinity); // last zoom or pan by the learner (performance.now)
  const wheelAcc = useRef(0);

  // ---- Volume geometry: the "image" is the current plane's display size. ----
  const vol = p.volume;
  const nav = vol?.nav;
  const geom: PlaneGeom | null = useMemo(() => (vol && nav ? planeGeom(vol.meta, nav.plane) : null), [vol, nav]);
  const imgW = geom ? geom.W : p.width;
  const imgH = geom ? geom.H : p.height;
  const slice = geom && nav ? nav.slice[nav.plane] : 0;
  const gridMode = !!vol && !!nav?.grid;
  const loaded = vol ? !!vol.data : imgLoaded;
  // Window / level (volumes): the case's default, a preset, or a W/L drag.
  const [win, setWin] = useState<Window>(() => vol?.meta.window ?? { wc: 0, ww: 1 });
  const [preset, setPreset] = useState(DEFAULT_PRESET);
  const [wlTool, setWlTool] = useState(false);
  const lut = useMemo(() => (vol ? windowLut(win.wc, win.ww, wl.invert) : null), [vol, win, wl.invert]);
  const presets = useMemo(() => {
    if (!vol) return [];
    const list = [{ name: DEFAULT_PRESET, wc: vol.meta.window.wc, ww: vol.meta.window.ww }];
    for (const q of vol.meta.presets ?? []) if (q.name !== DEFAULT_PRESET) list.push(q);
    return list;
  }, [vol]);

  const fit = useMemo(() => fitView(stage.w, stage.h, imgW, imgH, PAD), [stage, imgW, imgH]);
  const view = userView ?? fit;
  const zoom = fit.scale > 0 ? view.scale / fit.scale : 1;

  // Latest values for native event handlers.
  const live = useRef({ view, fit, stage, p, zoom, userView, kbd, imgW, imgH, geom, slice, gridMode, win });
  useLayoutEffect(() => {
    live.current = { view, fit, stage, p, zoom, userView, kbd, imgW, imgH, geom, slice, gridMode, win };
  });

  const sample = useCallback((img?: { x: number; y: number }): Sample => {
    const { view: v, stage: st, p: pp, zoom: z, imgW: w, imgH: h, geom: g, slice: sl, gridMode: grid } = live.current;
    const inside = img && insideImage(img, w, h);
    const vp = visibleRect(st.w, st.h, v, w, h);
    if (!g || !pp.volume) return { x: inside ? img.x : undefined, y: inside ? img.y : undefined, zoom: z, vp, loupe: pp.loupe };
    // Volumes: x, y and the viewport in in-plane voxel coords of the current plane, plus plane and slice.
    const q = inside ? displayToInPlane(g, img.x, img.y) : null;
    return {
      x: q ? q.u : undefined, y: q ? q.v : undefined, zoom: grid ? 1 : z,
      vp: grid ? [0, 0, g.w, g.h] : [vp[0] / g.ax, vp[1] / g.ay, vp[2] / g.ax, vp[3] / g.ay], loupe: pp.loupe,
      plane: g.plane, slice: sl,
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
  // A plane change is a new image: refit, and say so in the telemetry.
  const plane = nav?.plane;
  const firstPlane = useRef(true);
  useEffect(() => {
    if (!vol) return;
    setView(null);
    setKbd(null);
    if (firstPlane.current) { firstPlane.current = false; return; }
    p.telemetry.push('plane', sample());
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plane, gridMode]);
  // Every slice change is a telemetry event (the search trace's third dimension).
  const firstSlice = useRef(true);
  useEffect(() => {
    if (!vol) return;
    if (firstSlice.current) { firstSlice.current = false; return; }
    p.telemetry.push('slice', sample());
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slice, plane]);
  // The volume is "shown" once its voxels are decoded.
  const shownOnce = useRef(false);
  useEffect(() => {
    if (!vol || !vol.data || shownOnce.current) return;
    shownOnce.current = true;
    p.onShown();
  }, [vol, p]);

  const setLoupeAt = useCallback((sx: number, sy: number, img: { x: number; y: number }, show: boolean) => {
    const el = loupeRef.current;
    const im: HTMLElement | null = live.current.p.volume ? loupeCanvasRef.current : loupeImgRef.current;
    if (!el || !im) return;
    if (!show) { el.style.display = 'none'; return; }
    const { view: v, imgW: w, imgH: h } = live.current;
    const sc = v.scale * LOUPE_MAG;
    el.style.display = 'block';
    el.style.transform = `translate(${sx - LOUPE_PX / 2}px, ${sy - LOUPE_PX / 2}px)`;
    im.style.width = `${w * sc}px`;
    im.style.height = `${h * sc}px`;
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

  // Slice navigation (volumes).
  const navTo = useCallback((f: (n: VolumeNav) => VolumeNav) => live.current.p.volume?.setNav(f), []);
  const scrollSlices = useCallback((pl: Plane, steps: number) => {
    const v = live.current.p.volume;
    if (!v || !steps) return;
    v.setNav((n) => stepSlice(n, v.meta, pl, steps));
  }, []);

  // Wheel zoom (native listener: React's onWheel is passive and cannot preventDefault).
  // Volumes: the wheel scrolls slices (of the pane under the cursor in the grid); Ctrl / Cmd + wheel zooms.
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if ((e.target as HTMLElement).closest('[data-no-stage]')) return;
      e.preventDefault();
      const { view: v, fit: f, p: pp, gridMode: grid, geom: g } = live.current;
      if (pp.volume && g && !(e.ctrlKey || e.metaKey)) {
        const pane = (e.target as HTMLElement).closest('[data-pane]')?.getAttribute('data-pane');
        const pl: Plane | null = grid ? (PLANES.find((x) => x === pane) ?? null) : g.plane;
        if (!pl) return;
        const r = wheelNotches(wheelAcc.current, e.deltaY, e.deltaMode);
        wheelAcc.current = r.acc;
        scrollSlices(pl, r.steps);
        return;
      }
      if (grid) return;
      const r = el.getBoundingClientRect();
      const factor = Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015));
      const next = zoomAt(v, factor, e.clientX - r.left, e.clientY - r.top, f.scale, f.scale * MAX_ZOOM);
      const clamped = clampView(next, r.width, r.height, live.current.imgW, live.current.imgH);
      lastMove.current = performance.now();
      applyView(clamped);
      if (clamped.scale !== v.scale) setZoomed(true);
      p.telemetry.push('wheel', sample(clientToImage(e.clientX, e.clientY, r, clamped)));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [p.telemetry, sample, applyView, scrollSlices]);

  const resetView = useCallback(() => {
    applyView(null);
    p.telemetry.push('wheel', sample());
  }, [p.telemetry, sample, applyView]);

  /** Zoom about a stage point (default: the centre). Used by the + / − buttons and keys. */
  const zoomBy = useCallback((factor: number, at?: { x: number; y: number }) => {
    const { view: v, fit: f, stage: st, p: pp, imgW: w, imgH: h } = live.current;
    const ax = at?.x ?? st.w / 2;
    const ay = at?.y ?? st.h / 2;
    const next = clampView(zoomAt(v, factor, ax, ay, f.scale, f.scale * MAX_ZOOM), st.w, st.h, w, h);
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

  // ---- Marks as drawn on this view. Volumes: projected into the current plane; near slices ghosted, others hidden. ----
  const viewMarks: ViewMark[] = useMemo(() => {
    if (!geom) return p.marks.map((m) => ({ ...m, vis: 'full' as const }));
    return p.marks.flatMap((m) => {
      if (!m.voxel) return [];
      const d = voxelToDisplay(geom, m.voxel as Voxel);
      const vis = sliceVisibility(d.slice, slice);
      if (vis === 'hidden') return [];
      // A drawn outline lives on its own plane: shown there (in display px), a point elsewhere.
      const polygon = m.polygon && m.plane === geom.plane ? m.polygon.map(([u, v]): Pt => [u * geom.ax, v * geom.ay]) : null;
      return [{ ...m, x: d.x, y: d.y, vis, polygon }];
    });
  }, [p.marks, geom, slice]);

  const markAt = (sx: number, sy: number): string | null => {
    let best: string | null = null;
    let bestD = MARK_HIT_PX;
    for (const m of viewMarks) {
      if (m.vis !== 'full') continue;
      const q = imageToScreen(m.x, m.y, view);
      const d = Math.hypot(q.x - sx, q.y - sy);
      if (d <= bestD) { best = m.mark_id; bestD = d; }
    }
    return best;
  };

  const caliperOn = !!p.caliper && p.caliper.tool === 'caliper' && !p.reveal && !p.readOnly;
  const canPlace = p.canMark && !p.reveal && !gridMode && !caliperOn && !wlTool && !p.readOnly;
  const drawOn = canPlace && !!p.caliper && p.caliper.tool === 'draw';
  /** The drawn mark whose polygon holds this image point (topmost = last placed). */
  const outlineAt = (x: number, y: number): string | null => {
    for (let i = viewMarks.length - 1; i >= 0; i--) {
      const m = viewMarks[i];
      if (m.vis === 'full' && m.polygon && m.polygon.length >= 3 && insidePolygon(x, y, m.polygon)) return m.mark_id;
    }
    return null;
  };
  const popMark = viewMarks.find((m) => m.mark_id === p.popoverId);
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

  /** The 3-D part of a mark placed or moved at display px on the current slice (volumes only). */
  const at3 = (xd: number, yd: number) => {
    if (!geom) return { x: xd, y: yd };
    const pt = displayToPlane(xd, yd, geom, slice);
    return { x: pt.x, y: pt.y, at: { plane: pt.plane, slice: pt.slice, voxel: pt.voxel } };
  };
  /** A drawn outline (display px) as stored on a mark: image px on an X-ray, in-plane coords on a volume. */
  const polygonAt = (poly: Pt[]): Pt[] => (geom ? poly.map(([x, y]) => [x / geom.ax, y / geom.ay]) : poly);

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest('[data-no-stage]')) return;
    const r = e.currentTarget.getBoundingClientRect();
    const sx = e.clientX - r.left;
    const sy = e.clientY - r.top;
    // The grid has no gestures of its own (and capturing here would redirect the pane's double-click to the stage).
    if (gridMode) { gesture.current = { kind: 'none' }; return; }
    e.currentTarget.setPointerCapture(e.pointerId);
    if (wlTool && vol) { gesture.current = { kind: 'wl', x0: sx, y0: sy, w0: win }; return; }
    if (caliperOn) {
      const img = clientToImage(e.clientX, e.clientY, r, view);
      if (insideImage(img, imgW, imgH)) {
        gesture.current = { kind: 'caliper', x0: img.x, y0: img.y };
        p.caliper!.setDraft({ plane: geom?.plane ?? null, slice: geom ? slice : null, p0: [img.x, img.y], p1: [img.x, img.y] });
        p.telemetry.push('down', sample(img));
        return;
      }
    }
    const markId = p.canMark && !p.readOnly ? markAt(sx, sy) : null;
    const img = clientToImage(e.clientX, e.clientY, r, view);
    if (drawOn && !markId && !p.popoverId && insideImage(img, imgW, imgH)) {
      // Draw: a press away from a mark's tag starts a stroke (tracing a new outline, or redrawing the selected one).
      gesture.current = { kind: 'draw', pts: [[img.x, img.y]] };
      setStroke([[img.x, img.y]]);
      setArmedTagAt(0, 0, false);
      p.telemetry.push('down', sample(img));
      return;
    }
    gesture.current = { kind: 'pending', x0: sx, y0: sy, markId };
    p.telemetry.push('down', sample(img));
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest('[data-no-stage]') && gesture.current.kind === 'none') {
      if (!p.popoverId) setLoupeAt(0, 0, { x: 0, y: 0 }, false);
      setArmedTagAt(0, 0, false);
      return;
    }
    if (gridMode) return; // panes report their own moves
    if (kbd) setKbd(null); // the pointer takes over from the keyboard crosshair
    const r = e.currentTarget.getBoundingClientRect();
    const sx = e.clientX - r.left;
    const sy = e.clientY - r.top;
    const g = gesture.current;
    if (g.kind === 'wl') {
      setWindowLogged(dragWindow(g.w0, sx - g.x0, sy - g.y0), null, true);
      return;
    }
    if (g.kind === 'caliper') {
      const img = clientToImage(e.clientX, e.clientY, r, view);
      const d = p.caliper!.draft;
      if (d) p.caliper!.setDraft({ ...d, p1: [Math.min(imgW, Math.max(0, img.x)), Math.min(imgH, Math.max(0, img.y))] });
      p.telemetry.push('move', sample(img));
      return;
    }
    if (g.kind === 'draw') {
      const img = clientToImage(e.clientX, e.clientY, r, view);
      const pt: Pt = [Math.min(imgW, Math.max(0, img.x)), Math.min(imgH, Math.max(0, img.y))];
      const last = g.pts[g.pts.length - 1];
      // Sample at ≥ 1.5 screen px apart: enough for a faithful trace, few enough to simplify quickly.
      if (Math.hypot(pt[0] - last[0], pt[1] - last[1]) * view.scale >= 1.5) {
        g.pts.push(pt);
        setStroke(g.pts.slice());
      }
      p.telemetry.push('move', sample(img));
      return;
    }
    if (g.kind === 'pending' && Math.hypot(sx - g.x0, sy - g.y0) > DRAG_PX) {
      gesture.current = g.markId ? { kind: 'drag', markId: g.markId } : { kind: 'pan', x0: g.x0, y0: g.y0, o0: view };
      if (!g.markId) setPanning(true);
      if (g.markId) p.dispatch({ type: 'select', id: g.markId });
    }
    const cur = gesture.current;
    let v = view;
    if (cur.kind === 'pan') {
      v = clampView({ ...cur.o0, originX: cur.o0.originX + sx - cur.x0, originY: cur.o0.originY + sy - cur.y0 }, r.width, r.height, imgW, imgH);
      lastMove.current = performance.now();
      applyView(v);
    }
    const img = clientToImage(e.clientX, e.clientY, r, v);
    const inside = insideImage(img, imgW, imgH);
    if (cur.kind === 'drag') {
      p.dispatch({ type: 'move', id: cur.markId, ...at3(Math.min(imgW, Math.max(0, img.x)), Math.min(imgH, Math.max(0, img.y))) });
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
    if (g.kind === 'draw') {
      setStroke(null);
      const done = finishStroke(g.pts, live.current.view.scale);
      if (!done) return;
      if (done.kind === 'point') {
        // A click inside an outline you drew selects it; elsewhere it places a point mark, as the Point tool would.
        const hit = outlineAt(done.x, done.y);
        if (hit) p.dispatch({ type: 'select', id: hit, popover: true });
        else p.dispatch({ type: 'place', ...at3(done.x, done.y) });
        return;
      }
      const polygon = clampPolygon(done.polygon, imgW, imgH);
      const [x0, y0] = g.pts[0];
      const sel = viewMarks.find((m) => m.mark_id === p.selectedId);
      // Tracing again inside the selected outline replaces it (label and confidence stay).
      if (sel?.polygon && insidePolygon(x0, y0, sel.polygon) && !p.popoverId) {
        p.dispatch({ type: 'redraw', id: sel.mark_id, polygon: polygonAt(polygon), ...at3(done.x, done.y) });
        return;
      }
      p.dispatch({ type: 'place', polygon: polygonAt(polygon), ...at3(done.x, done.y) });
      return;
    }
    if (g.kind === 'caliper') {
      // A click without a drag leaves no line.
      const d = p.caliper!.draft;
      if (d && Math.hypot(d.p1[0] - d.p0[0], d.p1[1] - d.p0[1]) * view.scale < DRAG_PX) p.caliper!.setDraft(null);
      return;
    }
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
    if (!insideImage(img, imgW, imgH)) { p.dispatch({ type: 'select', id: null }); return; }
    setArmedTagAt(0, 0, false);
    // Wait out a possible double-click (which resets the view instead of marking).
    placeTimer.current = window.setTimeout(() => {
      placeTimer.current = null;
      p.dispatch({ type: 'place', ...at3(img.x, img.y) });
    }, DBLCLICK_MS);
  };

  const onDoubleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest('[data-no-stage]')) return;
    if (placeTimer.current) { clearTimeout(placeTimer.current); placeTimer.current = null; }
    if (gridMode) return; // the pane handles its own double-click
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

  // Grid panes: the cursor over a pane counts for the search trace of that pane's plane and slice.
  const onPaneMove = useCallback((m: PaneMove) => {
    const { p: pp } = live.current;
    const g = planeGeom(pp.volume!.meta, m.plane);
    const inside = m.inside;
    if (inside !== overImage.current) {
      overImage.current = inside;
      pp.telemetry.push(inside ? 'enter' : 'leave', { x: inside ? m.u : undefined, y: inside ? m.v : undefined, zoom: 1, vp: [0, 0, g.w, g.h], loupe: pp.loupe, plane: m.plane, slice: m.slice });
    }
    pp.telemetry.push('move', { x: inside ? m.u : undefined, y: inside ? m.v : undefined, zoom: 1, vp: [0, 0, g.w, g.h], loupe: pp.loupe, plane: m.plane, slice: m.slice });
  }, []);

  // Keyboard: arrows move a crosshair over the film (Shift = larger steps), Space or Enter places a mark there,
  // + and − zoom. The crosshair counts as the cursor for the search trace. Volumes: ↑ / ↓ scroll slices and
  // PageUp / PageDown jump five (handled by the reading room), so only ← / → move the crosshair sideways; Alt + ↑ / ↓ move it up and down.
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.target !== e.currentTarget || e.metaKey || e.ctrlKey) return;
    if (vol && !e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown' || e.key === 'PageUp' || e.key === 'PageDown')) return; // bubbles to the room
    if (e.altKey && !(vol && (e.key === 'ArrowUp' || e.key === 'ArrowDown'))) return;
    if (e.key === '+' || e.key === '=' || e.key === '-' || e.key === '_') {
      e.preventDefault();
      e.stopPropagation();
      const at = kbd ? imageToScreen(kbd.x, kbd.y, view) : undefined;
      zoomBy(e.key === '-' || e.key === '_' ? 1 / 1.25 : 1.25, at);
      return;
    }
    if (!canPlace || !loaded) return;
    const centre = () => {
      const [x0, y0, x1, y1] = visibleRect(stage.w, stage.h, view, imgW, imgH);
      return { x: (x0 + x1) / 2, y: (y0 + y1) / 2 };
    };
    const dir: Record<string, [number, number]> = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    if (dir[e.key]) {
      e.preventDefault();
      e.stopPropagation();
      const step = (e.shiftKey ? KEY_STEP_BIG_PX : KEY_STEP_PX) / view.scale;
      const from = kbd ?? centre();
      const next = kbd
        ? { x: Math.min(imgW, Math.max(0, from.x + dir[e.key][0] * step)), y: Math.min(imgH, Math.max(0, from.y + dir[e.key][1] * step)) }
        : from; // the first arrow press only shows the crosshair
      // Keep the crosshair on screen when zoomed in.
      const q = imageToScreen(next.x, next.y, view);
      const m = 36;
      const dx = q.x < m ? m - q.x : q.x > stage.w - m ? stage.w - m - q.x : 0;
      const dy = q.y < m ? m - q.y : q.y > stage.h - m ? stage.h - m - q.y : 0;
      if ((dx || dy) && userView) applyView(clampView({ ...view, originX: view.originX + dx, originY: view.originY + dy }, stage.w, stage.h, imgW, imgH));
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
      p.dispatch({ type: 'place', ...at3(kbd.x, kbd.y) });
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
  /** Window change (volumes): from a preset (named) or a drag (presets clear). */
  const setWindowLogged = (next: Window, presetName: string | null, throttled = false) => {
    setWin(next);
    setPreset(presetName ?? '');
    live.current.win = next;
    p.telemetry.push(throttled ? 'window' : 'wl', sample());
  };
  const resetAll = () => {
    setWlLogged({ brightness: 100, contrast: 100, invert: false });
    if (vol) { setWin(vol.meta.window); setPreset(DEFAULT_PRESET); setWlTool(false); }
    resetView();
  };

  const boost = p.projector ? { b: 1.08, c: 1.3 } : { b: 1, c: 1 };
  // Volumes: invert goes through the LUT; brightness / contrast are replaced by the window.
  const filter = vol
    ? `brightness(${boost.b}) contrast(${boost.c})`
    : `brightness(${(wl.brightness / 100) * boost.b}) contrast(${(wl.contrast / 100) * boost.c})${wl.invert ? ' invert(1)' : ''}`;
  const strokePx = p.projector ? 4 : 2;
  const k = 1 / view.scale; // image units per screen px
  const kbdPos = kbd ? imageToScreen(kbd.x, kbd.y, view) : null;
  const armedName = p.armed ? labelDisplay(p.armed) : '';
  const anatomyOn = !!p.reveal && !!p.anatomy?.on;
  const strokeOn = !!stroke && stroke.length > 1;
  const strokeD = strokeOn ? polygonPath(stroke!) : '';
  // Signs on this view (X-ray: all of them; volume: this plane and slice), and the toggle only when the reveal has any.
  const viewSigns = useMemo(
    () => (p.reveal ? signsOnView(p.reveal.findings, geom, geom ? slice : null) : []),
    [p.reveal, geom, slice],
  );
  const hasSigns = !!p.reveal && p.reveal.findings.some((f) => (f.signs?.length ?? 0) > 0);
  // focusSign(): a volume scrolls to the sign's plane and slice (the pulse is the layer's).
  useEffect(() => {
    if (!focusedSign || !vol || !p.reveal) return;
    const at = signSlice(p.reveal.findings, focusedSign.id);
    if (!at || !PLANES.includes(at.plane as Plane)) return;
    navTo((n) => showPlane(n, vol.meta, at.plane as Plane, at.slice));
  }, [focusedSign, vol, p.reveal, navTo]);
  const zoneText = !anatomyOn ? '' : p.anatomy!.status === 'pending' ? 'Loading anatomy…'
    : p.anatomy!.status === 'error' || (!p.anatomy!.data?.zones.length && !vol?.mask) ? 'Anatomy outlines are not available for this case.'
    : hoverZone ? (p.anatomy!.data?.zones.find((z) => z.id === hoverZone)?.name ?? hoverZone)
    : `Point at a zone to name it${p.anatomy!.data?.approximate ? ' · zones are approximate' : ''}`;
  const hasTrace = !!p.reveal?.heatmapUrl;

  // ---- Volumes after submit: the outlines on this slice, the anatomy tint and the cursor splats of this slice. ----
  const sliceFindings = useMemo(
    () => (p.reveal && vol?.mask && geom ? findingsOnSlice(p.reveal.findings, vol.mask, geom, slice) : null),
    [p.reveal, vol?.mask, geom, slice],
  );
  const sliceZones = useMemo(
    () => (anatomyOn && vol?.mask && geom && p.reveal ? anatomyOnSlice(vol.mask, geom, slice, findingValues(p.reveal.findings), vol.maskNames) : []),
    [anatomyOn, vol?.mask, vol?.maskNames, geom, slice, p.reveal],
  );
  const sliceTrace = useMemo(() => {
    if (!p.reveal || !vol?.submittedTelemetry || !geom || typeof document === 'undefined') return null;
    const ev = vol.submittedTelemetry.filter((e) => e.plane === geom.plane && e.slice === slice);
    if (ev.length < 2) return null;
    return densityToDataUrl(densityFromTelemetry(ev, geom.w, geom.h));
  }, [p.reveal, vol?.submittedTelemetry, geom, slice]);
  // Arrows on a volume are drawn in the axial plane on the finding's measured slice (from_xy / to_xy are axial voxel coords).
  const sliceArrows = useMemo(() => {
    if (!p.reveal || !geom || geom.plane !== 'axial') return [];
    return p.reveal.arrows.flatMap((a) => {
      const f = p.reveal!.findings.find((x) => x.finding_id === a.to_finding);
      const at = f?.measure?.slice ?? (f?.centroid3 ? Math.round(f.centroid3[2]) : null);
      if (at == null || at !== slice) return [];
      const sc = (xy: [number, number] | null | undefined): [number, number] | null => (xy ? [xy[0] * geom.ax, xy[1] * geom.ay] : null);
      return [{ ...a, from_xy: sc(a.from_xy), to_xy: sc(a.to_xy) }];
    });
  }, [p.reveal, geom, slice]);
  const revealView: RevealView | null = p.reveal && vol && geom
    ? { ...p.reveal, findings: sliceFindings ?? [], arrows: sliceArrows, unvisited: [], heatmapUrl: sliceTrace, signs: viewSigns, showSigns: signsVisible }
    : p.reveal ? { ...p.reveal, signs: viewSigns, showSigns: signsVisible } : null;
  const sliceLabel = geom ? `Slice ${slice + 1} of ${geom.n}` : '';
  const comps = (p.reveal?.findings ?? []).find((f) => f.components?.length)?.components ?? null;
  const caliperDraft = p.caliper?.draft ?? null;
  const caliperHere = caliperDraft && (!geom ? caliperDraft.plane == null : caliperDraft.plane === geom.plane && caliperDraft.slice != null);
  const caliperVis = caliperHere && caliperDraft ? (geom ? sliceVisibility(caliperDraft.slice!, slice) : 'full') : 'hidden';
  const caliperLen = caliperDraft ? (geom ? `${fmtMm(displayLengthMm(geom, caliperDraft.p0, caliperDraft.p1))} mm` : `${Math.round(Math.hypot(caliperDraft.p1[0] - caliperDraft.p0[0], caliperDraft.p1[1] - caliperDraft.p0[1]))} px`) : '';
  const stageLabel = vol
    ? gridMode ? `${PLANE_DISPLAY.axial}, coronal and sagittal panes of the scan. Double-click a pane to open it.`
      : canPlace ? `${PLANE_DISPLAY[geom!.plane]} slice ${slice + 1} of ${geom!.n}. Up and down arrows change the slice. Left and right move a crosshair; Space places a mark. Plus and minus zoom.`
      : `${PLANE_DISPLAY[geom!.plane]} slice ${slice + 1} of ${geom!.n}. Up and down arrows change the slice. Plus and minus zoom.`
    : canPlace
      ? 'Chest radiograph. Arrow keys move a crosshair, Shift for larger steps. Space places a mark. Plus and minus zoom.'
      : 'Chest radiograph. Plus and minus zoom.';
  const toolsOn = !!p.caliper && !p.reveal && !p.readOnly;
  const curTool: Tool = p.caliper?.tool ?? 'mark';

  return (
    <div className={`${s.viewer} ${vol ? s.volumeRoom : ''}`} data-modality={vol ? vol.modality : 'cxr'}>
      {/* Strip above the film: what to do next before submit; the layer toggles after. Fixed height, so the film never jumps. */}
      <div className={s.topStrip} data-testid="viewer-strip">
        <div className={s.stripLeft}>
          {!p.reveal && p.markBlockedReason ? (
            <span className={s.stripNote} data-testid="mark-blocked">{p.markBlockedReason}</span>
          ) : !p.reveal && caliperOn ? (
            <span className={s.stripArmed} data-testid="caliper-prompt">
              <strong>Caliper</strong> — drag from edge to edge{p.caliper?.forMark ? ` of ${p.caliper.forMark}` : ''}{geom && gridMode ? ' (double-click a pane first)' : ''}
              {caliperDraft && <span className={s.stripMeasure} data-testid="caliper-readout">{caliperLen}</span>}
              <button type="button" className={s.stripLink} onClick={() => { p.caliper!.setTool('mark'); }}>Done <kbd className={s.kbdTool}>Esc</kbd></button>
            </span>
          ) : !p.reveal && p.armed && p.canMark ? (
            <span className={s.stripArmed} data-testid="armed-prompt">
              <strong>{armedName}</strong> — {gridMode ? 'double-click a pane, then click where you see it' : drawOn ? `press and drag to trace around it on the ${vol ? 'scan' : 'film'}` : vol ? 'click the scan where you see it' : 'click the film where you see it'}
              <button type="button" className={s.stripLink} onClick={() => p.dispatch({ type: 'disarm' })}>Cancel <kbd className={s.kbdTool}>Esc</kbd></button>
            </span>
          ) : drawOn ? (
            <span className={s.stripArmed} data-testid="draw-prompt">
              <strong>Draw</strong> — press and drag to trace around a finding; release to close the outline
              <button type="button" className={s.stripLink} onClick={() => p.caliper!.setTool('mark')}>Point tool <kbd className={s.kbdTool}>P</kbd></button>
            </span>
          ) : loaded && (canPlace || gridMode) && !p.reveal && !p.readOnly && (p.marks.length === 0 || !zoomed) ? (
            <span className={s.nudge} data-testid="nudge" aria-hidden="true">
              {p.marks.length === 0 && <span>{gridMode ? 'Double-click a pane to read it, then pick what you see on the right' : 'Pick what you see on the right, then click where it is'}</span>}
              {!zoomed && <span>{vol ? 'Scroll to change slice · Ctrl + scroll to zoom' : 'Use the wheel to zoom'}</span>}
            </span>
          ) : anatomyOn ? (
            <span className={s.zoneName} data-testid="zone-name" aria-live="polite">{zoneText}</span>
          ) : p.reveal ? (
            <span className={s.key} data-testid="reveal-key">
              <span className={s.keyCyan} /> Expert outline <span className={s.keyAmber} /> You
              {comps && (
                <span className={s.compKey} data-testid="component-key">
                  {comps.map((c, i) => <span key={c.label_value}><i style={{ opacity: 0.2 + i * 0.3 }} /> {c.name}</span>)}
                </span>
              )}
            </span>
          ) : null}
        </div>
        {p.reveal && (
          <div className={s.stripRight}>
            {p.search && (
              <button type="button" className={`${s.tool} ${p.search.on ? s.toolOn : ''}`} aria-pressed={p.search.on}
                onClick={p.search.onToggle} data-testid="search-toggle" data-tour="my-search" title="Show or hide where your cursor spent time">
                My search: {p.search.on ? 'on' : 'off'}
              </button>
            )}
            {hasSigns && (
              <button type="button" className={`${s.tool} ${signsVisible ? s.toolOn : ''}`} aria-pressed={signsVisible}
                onClick={toggleSigns} data-testid="signs-toggle" title="Show or hide the signs to look for (S)">
                Signs: {signsVisible ? 'on' : 'off'}<kbd className={s.kbdTool}>S</kbd>
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
        className={`${s.stage} ${panning ? s.panning : ''} ${canPlace ? s.marking : ''} ${drawOn ? s.drawing : ''} ${caliperOn && !gridMode ? s.measuring : ''} ${wlTool ? s.windowing : ''}`}
        data-tool={toolsOn ? curTool : undefined}
        data-anatomy={anatomyOn ? '1' : undefined}
        data-testid="stage"
        data-tour="film"
        data-zoom={zoom.toFixed(3)}
        data-view={`${view.originX.toFixed(3)},${view.originY.toFixed(3)},${view.scale.toFixed(6)}`}
        data-armed={p.armed ?? ''}
        data-plane={gridMode ? 'grid' : geom?.plane}
        data-slice={geom && !gridMode ? slice : undefined}
        tabIndex={0}
        role="application"
        aria-label={stageLabel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onPointerLeave={onPointerLeave}
        onClick={onClick}
        onDoubleClick={onDoubleClick}
        onKeyDown={onKeyDown}
      >
        {vol && gridMode && vol.data && lut ? (
          <VolumeGrid
            volume={vol.data} nav={nav!} lut={lut} filter={filter} marks={p.marks} findings={p.reveal?.findings ?? []} mask={vol.mask ?? null}
            window={win} caseId={p.caseId} modality={vol.modality} sequence={vol.meta.sequence} provenance={vol.provenance} revealed={!!p.reveal}
            onOpen={(pl) => navTo((n) => showPlane(n, vol.meta, pl))} onMove={onPaneMove} onLeave={onPointerLeave} strokePx={strokePx}
          />
        ) : (
          <div
            className={`${s.layer} ${fitting ? s.fitting : ''}`}
            style={{ width: imgW, height: imgH, transform: `translate(${view.originX}px, ${view.originY}px) scale(${view.scale})` }}
          >
            <div className={s.film} />
            {vol ? (
              vol.data && lut && geom ? (
                <SliceCanvas volume={vol.data} plane={geom.plane} slice={slice} lut={lut} className={s.image} style={{ filter }} testid="film"
                  alt={`${PLANE_DISPLAY[geom.plane]} slice ${slice + 1} of ${geom.n}`} />
              ) : null
            ) : (
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
            )}
            {anatomyOn && !vol && p.anatomy!.data && (
              <AnatomyLayer anatomy={p.anatomy!.data} width={imgW} height={imgH} k={k} hovered={hoverZone} onHover={setHoverZone} />
            )}
            {anatomyOn && vol && sliceZones.length > 0 && (
              <svg className={s.overlay} viewBox={`0 0 ${imgW} ${imgH}`} width={imgW} height={imgH} data-testid="anatomy-layer" aria-hidden="true">
                {sliceZones.map((z) => (
                  <path key={z.value} d={ringsPath(z.rings)} className={`${s.zoneTint} ${hoverZone === String(z.value) ? s.zoneTintOn : ''}`} fillRule="evenodd"
                    strokeWidth={1.25 * k} data-zone={z.name} onPointerEnter={() => setHoverZone(String(z.value))} onPointerLeave={() => setHoverZone(null)}>
                    <title>{z.name}</title>
                  </path>
                ))}
              </svg>
            )}
            {revealView && (
              <ErrorBoundary>
                <RevealLayer reveal={revealView} width={imgW} height={imgH} k={k} strokePx={strokePx} marks={viewMarks} />
              </ErrorBoundary>
            )}
            <svg className={s.overlay} viewBox={`0 0 ${imgW} ${imgH}`} width={imgW} height={imgH} aria-hidden="true">
              {/* Drawn outlines go under every tag; after the reveal each carries its outline verdict. */}
              {viewMarks.map((m) => {
                if (!m.polygon || m.polygon.length < 3) return null;
                const rm = p.reveal?.marks.find((x) => x.mark_id === m.mark_id);
                const sel = m.mark_id === p.selectedId;
                const unfinished = !m.label || m.confidence == null;
                const d = polygonPath(m.polygon);
                const verdict = rm?.outline_verdict && VERDICT_TEXT[rm.outline_verdict] ? VERDICT_TEXT[rm.outline_verdict] : null;
                let x1 = -Infinity, y0 = Infinity;
                for (const [x, y] of m.polygon) { x1 = Math.max(x1, x); y0 = Math.min(y0, y); }
                const vfs = (p.projector ? 16 : 12) * k;
                const vw = (verdict ? verdict.length * 0.6 * vfs : 0) + vfs * 1.2;
                const vx = Math.min(x1 - vw * 0.3, imgW - vw);
                const vy = Math.max(0, y0 - vfs * 2.1);
                return (
                  <g key={`o-${m.mark_id}`} data-outline-id={m.mark_id} data-verdict={rm?.outline_verdict ?? undefined} className={m.vis === 'ghost' ? s.markGhost : ''}>
                    <path d={d} className={s.outlineMarkCasing} strokeWidth={(strokePx + 2.5) * k} />
                    <path d={d} className={`${s.outlineMark} ${sel ? s.outlineMarkSel : ''}`} strokeWidth={(sel ? strokePx + 1 : strokePx) * k}
                      strokeDasharray={unfinished && !p.reveal ? `${5 * k} ${3 * k}` : undefined} />
                    {verdict && (
                      <g className={s.settle} data-testid={`verdict-${m.mark_id}`} data-verdict={rm!.outline_verdict!}>
                        <rect x={vx} y={vy} width={vw} height={vfs * 1.6} rx={vfs * 0.8} className={s.verdictChip} strokeWidth={1.2 * k} />
                        <text x={vx + vw / 2} y={vy + vfs * 1.15} textAnchor="middle" className={s.verdictText} style={{ fontSize: vfs }}>{verdict}</text>
                      </g>
                    )}
                  </g>
                );
              })}
              {strokeOn && <path d={strokeD} className={s.strokeLive} strokeWidth={strokePx * k} data-testid="stroke-live" />}
              {viewMarks.map((m) => {
                const rm = p.reveal?.marks.find((x) => x.mark_id === m.mark_id);
                const sel = m.mark_id === p.selectedId;
                const unfinished = !m.label || m.confidence == null;
                const unmatched = (rm?.result as string | undefined) === 'unmatched';
                const drawn = !!m.polygon && m.polygon.length >= 3;
                const r = drawn ? 6 : 10;
                return (
                  <g key={m.mark_id} data-mark-id={m.mark_id} data-label={m.label ?? ''} data-tool={drawn ? 'draw' : 'point'} data-vis={vol ? m.vis : undefined} className={`${s.mark} ${m.vis === 'ghost' ? s.markGhost : ''}`} transform={`translate(${m.x} ${m.y})`}>
                    {rm?.result === 'false_positive' && (
                      <circle r={18 * k} className={`${s.overcallRing} ${s.settle}`} strokeWidth={strokePx * k} />
                    )}
                    {unmatched && (
                      <circle r={18 * k} className={`${s.unmatchedRing} ${s.settle}`} strokeWidth={strokePx * k} strokeDasharray={`${1.5 * k} ${3.5 * k}`} data-testid={`unmatched-${m.mark_id}`} />
                    )}
                    <circle r={r * k} className={s.markHalo} strokeWidth={(strokePx + 3) * k} />
                    <circle
                      r={r * k}
                      className={s.markRing}
                      strokeWidth={(sel ? strokePx + 1.5 : strokePx) * k}
                      strokeDasharray={unfinished && !p.reveal ? `${4 * k} ${3 * k}` : undefined}
                    />
                    <circle r={1.8 * k} className={s.markDot} />
                    <text x={(drawn ? 10 : 15) * k} y={-(drawn ? 7 : 10) * k} className={s.markText} style={{ fontSize: (p.projector ? 18 : drawn ? 12 : 13) * k, strokeWidth: 3 * k }}>
                      {m.mark_id}
                    </text>
                  </g>
                );
              })}
              {caliperDraft && caliperVis !== 'hidden' && (
                <g className={`${s.caliper} ${caliperVis === 'ghost' ? s.markGhost : ''}`} data-testid="caliper-line">
                  <line x1={caliperDraft.p0[0]} y1={caliperDraft.p0[1]} x2={caliperDraft.p1[0]} y2={caliperDraft.p1[1]} className={s.caliperCasing} strokeWidth={(strokePx + 3) * k} />
                  <line x1={caliperDraft.p0[0]} y1={caliperDraft.p0[1]} x2={caliperDraft.p1[0]} y2={caliperDraft.p1[1]} className={s.caliperLine} strokeWidth={strokePx * k} />
                  {[caliperDraft.p0, caliperDraft.p1].map((pt, i) => <circle key={i} cx={pt[0]} cy={pt[1]} r={3 * k} className={s.caliperEnd} strokeWidth={1.5 * k} />)}
                  <text x={(caliperDraft.p0[0] + caliperDraft.p1[0]) / 2 + 8 * k} y={(caliperDraft.p0[1] + caliperDraft.p1[1]) / 2 - 8 * k}
                    className={s.caliperText} style={{ fontSize: (p.projector ? 18 : 13) * k, strokeWidth: 3 * k }}>{caliperLen}</text>
                </g>
              )}
            </svg>
          </div>
        )}

        <div ref={loupeRef} className={s.loupe} style={{ width: LOUPE_PX, height: LOUPE_PX }} data-testid="loupe" aria-hidden="true">
          {vol ? (
            vol.data && lut && geom ? <SliceCanvas volume={vol.data} plane={geom.plane} slice={slice} lut={lut} className={s.loupeImg} style={{ filter }} canvasRef={loupeCanvasRef} /> : null
          ) : (
            <img ref={loupeImgRef} src={p.imageUrl} alt="" className={s.loupeImg} style={{ filter }} draggable={false} />
          )}
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

        {/* Volumes: the window readout, top right. */}
        {vol && !gridMode && (
          <div className={s.wlReadout} data-no-stage data-testid="wl-readout" aria-live="off">
            W {Math.round(win.ww)} · L {Math.round(win.wc)}{preset ? ` · ${preset}` : ''}
          </div>
        )}

        {!loaded && <div className={s.loading} data-testid="film-loading">{vol?.status === 'error' ? (vol.error || 'The scan could not be loaded.') : vol ? 'Loading scan…' : 'Loading film…'}</div>}

        {/* On-film legend for the layers that are on. */}
        {p.reveal && (p.search || anatomyOn) && (
          <div className={s.legend} data-no-stage data-testid="film-legend" onPointerDown={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
            {p.search && !p.search.on && (
              <div className={`${s.legendChip} ${s.legendMuted}`} data-testid="search-legend" data-search="off">
                <span>My search is off — turn it on to see where you looked</span>
              </div>
            )}
            {p.search?.on && (
              <div className={s.legendChip} data-testid="search-legend">
                <span className={s.legendSwatch} aria-hidden="true" />
                <span>
                  {vol ? (hasTrace || !!vol.sliceDwell?.length ? `${SEARCH_LEGEND} on this slice; the bar under the film shows the slices` : 'No cursor movement was recorded on this scan') : hasTrace ? SEARCH_LEGEND : 'No cursor movement was recorded on this film'}
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
            {anatomyOn && !vol && p.anatomy!.status === 'success' && !!p.anatomy!.data?.zones.length && (
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
            {anatomyOn && vol && (
              <div className={s.legendChip} data-testid="anatomy-legend">
                <span><span className={s.legendTint} aria-hidden="true" /> Organ (from the reference segmentation){sliceZones.length === 0 ? ' · none on this slice' : ''}</span>
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
            modality={vol?.modality}
          />
        )}
      </div>

      {/* Image controls: their own strip under the film. */}
      <div className={s.tools} data-tour="controls" data-testid="viewer-tools">
        {vol && nav && (
          <>
            <span className={s.toolGroup} role="group" aria-label="Plane" data-tour={nav.grid ? 'slices' : 'planes'}>
              <button type="button" className={`${s.tool} ${nav.grid ? s.toolOn : ''}`} aria-pressed={nav.grid} onClick={() => navTo(showGrid)} data-testid="plane-all">All</button>
              {PLANES.map((pl) => (
                <button type="button" key={pl} className={`${s.tool} ${!nav.grid && nav.plane === pl ? s.toolOn : ''}`} aria-pressed={!nav.grid && nav.plane === pl}
                  onClick={() => navTo((n) => showPlane(n, vol.meta, pl))} data-testid={`plane-${pl}`}>{PLANE_DISPLAY[pl]}</button>
              ))}
            </span>
            {!nav.grid && geom && (
              <span className={s.sliceGroup} data-tour="slices">
                {p.reveal && vol.sliceDwell !== undefined && (
                  <DwellBar dwell={vol.sliceDwell} plane={geom.plane} n={geom.n} current={slice} findingSlicesViewed={vol.findingSlicesViewed} showDwell={!p.search || p.search.on} onPick={(sl) => navTo((n) => setSlice(n, vol.meta, geom.plane, sl))} />
                )}
                <label className={s.slider}>
                  <span data-testid="slice-readout">{sliceLabel}</span>
                  <input type="range" min={0} max={geom.n - 1} value={slice} aria-label={`${PLANE_DISPLAY[geom.plane]} slice`} aria-valuetext={sliceLabel}
                    className={s.sliceSlider} data-testid="slice-slider"
                    onChange={(e) => navTo((n) => setSlice(n, vol.meta, geom.plane, Number(e.target.value)))} />
                </label>
              </span>
            )}
          </>
        )}
        <span className={s.toolGroup}>
          <span className={s.toolLabel}>Zoom</span>
          <button type="button" className={s.toolSq} aria-label="Zoom out" title="Zoom out (−)" onClick={() => zoomBy(1 / 1.25)} disabled={zoom <= 1.001 || gridMode} data-testid="zoom-out">−</button>
          <span className={s.zoom} data-testid="zoom-readout">{zoom.toFixed(1)}×</span>
          <button type="button" className={s.toolSq} aria-label="Zoom in" title="Zoom in (+)" onClick={() => zoomBy(1.25)} disabled={zoom >= MAX_ZOOM - 0.001 || gridMode} data-testid="zoom-in">+</button>
        </span>
        {vol ? (
          <>
            <label className={s.slider}>
              <span>Window</span>
              <select className={s.select} value={preset} aria-label="Window preset" data-testid="window-preset"
                onChange={(e) => { const q = presets.find((x) => x.name === e.target.value); if (q) setWindowLogged({ wc: q.wc, ww: q.ww }, q.name); }}>
                {!preset && <option value="">Custom</option>}
                {presets.map((q) => <option key={q.name} value={q.name}>{q.name}</option>)}
              </select>
            </label>
            {!p.readOnly && (
              <button type="button" className={`${s.tool} ${wlTool ? s.toolOn : ''}`} aria-pressed={wlTool} onClick={() => setWlTool((v) => !v)} data-testid="wl-tool"
                title="Drag on the scan: sideways changes the window width, up and down the level">
                W/L drag: {wlTool ? 'on' : 'off'}
              </button>
            )}
          </>
        ) : (
          <>
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
          </>
        )}
        <button type="button" className={`${s.tool} ${wl.invert ? s.toolOn : ''}`} aria-pressed={wl.invert}
          onClick={() => setWlLogged({ ...wl, invert: !wl.invert })} data-testid="invert-toggle">Invert: {wl.invert ? 'on' : 'off'}</button>
        <button type="button" className={s.tool} data-testid="reset-view" onClick={resetAll}>
          Reset view
        </button>
        <span className={s.toolSpacer} />
        <span className={s.toolRight}>
        {toolsOn && (
          <span className={s.segment} role="group" aria-label="Tool" data-testid="tool-segment" data-tour="tools">
            {TOOLS.map((t) => {
              const on = curTool === t.id;
              const caliper = t.id === 'caliper';
              return (
                <button type="button" key={t.id} className={`${s.tool} ${on ? s.toolOn : ''}`} aria-pressed={on}
                  data-testid={caliper ? 'caliper-toggle' : `tool-${t.id}`} data-tour={caliper ? 'measure' : undefined}
                  onClick={() => p.caliper!.setTool(on && t.id !== 'mark' ? 'mark' : t.id)} title={t.title}>
                  {t.name}<kbd className={s.kbdTool}>{t.key}</kbd>
                </button>
              );
            })}
          </span>
        )}
        {p.onToggleLoupe && (
          <span className={s.tipAnchor}>
            <button type="button" className={`${s.tool} ${p.loupe ? s.toolOn : ''}`} aria-pressed={p.loupe} onClick={p.onToggleLoupe}
              data-testid="loupe-toggle" data-tour="magnifier" title="Magnifier: a 2.5× lens that follows your cursor (M)" aria-describedby={tip ? 'magnifier-tip' : undefined}>
              <span className={s.dot} aria-hidden="true" />{p.loupe ? 'Magnifier on' : 'Magnifier off'}<kbd className={s.kbdTool}>M</kbd>
            </button>
            {tip && (
              <span className={s.tip} role="tooltip" id="magnifier-tip" data-testid="magnifier-tip">
                The magnifier is a 2.5× lens that follows your cursor over the {vol ? 'scan' : 'film'}. Use it for fine detail; press <kbd className={s.kbdTool}>M</kbd> to put it away.
              </span>
            )}
          </span>
        )}
        </span>
      </div>

      {explain && <SearchExplainer onClose={() => setExplain(false)} />}
    </div>
  );
}
