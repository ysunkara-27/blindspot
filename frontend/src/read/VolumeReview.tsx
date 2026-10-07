// Read-only review of a CT / MR read: the axial slices (slider, ↑ / ↓), the expert outlines of the slice from the
// label volume (post-submit URL in the result), the learner's marks near the slice, and the slice dwell bar.
// Same drawing code as the reading-room reveal; nothing can be changed.
import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { assetUrl } from '../api/client';
import { ErrorBoundary } from '../app/ErrorBoundary';
import type { SubmitResult } from '../types/contracts';
import { RevealLayer, type RevealView } from '../viewer/RevealLayer';
import { DwellBar } from '../viewer/volume/DwellBar';
import { volumeMeta } from '../viewer/volume/guard';
import { PLANE_DISPLAY } from '../viewer/volume/nav';
import { planeGeom, revealSlice, sliceVisibility, voxelToDisplay, type Voxel } from '../viewer/volume/planes';
import { SliceCanvas } from '../viewer/volume/SliceCanvas';
import { findingsOnSlice } from '../viewer/volume/sliceReveal';
import { cachedGunzip, decodeMask, decodeVolume } from '../viewer/volume/volume';
import { windowLut } from '../viewer/volume/window';
import vs from '../viewer/Viewer.module.css';
import c from './CaseReview.module.css';

export type VolumeReviewMark = { mark_id: string; x: number; y: number; plane?: string | null; slice?: number | null; voxel?: number[] | null };

export function VolumeReview({ result, volume, marks }: { result: SubmitResult; volume: unknown; marks: VolumeReviewMark[] }) {
  const meta = useMemo(() => volumeMeta({ volume: volume as never }), [volume]);
  const ref = useRef<HTMLDivElement>(null);
  const [boxW, setBoxW] = useState(0);
  const [slice, setSlice] = useState(() => (meta ? revealSlice(result.reveal.findings, meta.shape[0]) : 0));
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBoxW(el.clientWidth));
    ro.observe(el);
    setBoxW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  const volQ = useQuery({
    queryKey: ['volume', meta?.data_url ?? ''],
    queryFn: async () => decodeVolume(await cachedGunzip(assetUrl(meta!.data_url)), meta!),
    enabled: !!meta, staleTime: Infinity, retry: 1,
  });
  const maskUrl = result.reveal.maskvol_url ?? null;
  const maskQ = useQuery({
    queryKey: ['maskvol', 'review', maskUrl ?? ''],
    queryFn: async () => decodeMask(await cachedGunzip(assetUrl(maskUrl!)), meta!),
    enabled: !!meta && !!maskUrl, staleTime: Infinity, retry: 1,
  });
  const g = useMemo(() => (meta ? planeGeom(meta, 'axial') : null), [meta]);
  const lut = useMemo(() => (meta ? windowLut(meta.window.wc, meta.window.ww) : null), [meta]);
  if (!meta || !g || !lut) return <p className={c.note} data-testid="case-film-missing">The scan could not be identified for this read.</p>;
  const scale = boxW > 0 ? boxW / g.W : 0;
  const k = scale > 0 ? 1 / scale : 1;
  // Marks: the voxel from the scored marks (the result carries it) or from the submitted ones.
  const scored = new Map(result.reveal.marks.map((m) => [m.mark_id, m]));
  const shown = marks.flatMap((m) => {
    const vox = (m.voxel ?? scored.get(m.mark_id)?.voxel) as Voxel | undefined;
    if (!vox || vox.length < 3) return [];
    const d = voxelToDisplay(g, vox);
    const vis = sliceVisibility(d.slice, slice);
    return vis === 'hidden' ? [] : [{ mark_id: m.mark_id, x: d.x, y: d.y, vis }];
  });
  const findings = maskQ.data ? findingsOnSlice(result.reveal.findings, maskQ.data, g, slice) : [];
  const view: RevealView = { findings, marks: result.reveal.marks, arrows: [], heatmapUrl: null, showTrace: false };
  const n = result.reveal.findings.length;
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { e.preventDefault(); setSlice((s) => Math.min(g.n - 1, Math.max(0, s + (e.key === 'ArrowUp' ? -1 : 1)))); }
  };
  return (
    <figure className={c.figure} data-testid="volume-review">
      <div ref={ref} className={c.film} style={{ height: scale ? g.H * scale : undefined, aspectRatio: scale ? undefined : `${g.W} / ${g.H}` }}
        data-testid="case-figure" data-slice={slice} role="img" tabIndex={0} onKeyDown={onKey}
        aria-label={`${PLANE_DISPLAY.axial} slice ${slice + 1} of ${g.n} of the scan you read, with ${n} expert outline${n === 1 ? '' : 's'} and ${marks.length} of your marks`}>
        {volQ.isError ? (
          <p className={c.note} data-testid="case-film-missing">The scan did not load. The outcomes and the debrief are still shown.</p>
        ) : volQ.data && scale > 0 ? (
          <div className={`${vs.layer} ${vs.still}`} style={{ width: g.W, height: g.H, transform: `scale(${scale})` }}>
            <SliceCanvas volume={volQ.data} plane="axial" slice={slice} lut={lut} className={vs.image} testid="case-film" />
            <ErrorBoundary>
              <RevealLayer reveal={view} width={g.W} height={g.H} k={k} strokePx={2} marks={shown} />
            </ErrorBoundary>
            <svg className={vs.overlay} viewBox={`0 0 ${g.W} ${g.H}`} width={g.W} height={g.H} aria-hidden="true">
              {shown.map((m) => {
                const r = scored.get(m.mark_id)?.result as string | undefined;
                return (
                  <g key={m.mark_id} transform={`translate(${m.x} ${m.y})`} opacity={m.vis === 'ghost' ? 0.45 : 1} data-testid={`case-mark-${m.mark_id}`}>
                    {r === 'false_positive' && <circle r={18 * k} className={vs.overcallRing} strokeWidth={2 * k} />}
                    {r === 'unmatched' && <circle r={18 * k} className={vs.unmatchedRing} strokeWidth={2 * k} strokeDasharray={`${1.5 * k} ${3.5 * k}`} />}
                    <circle r={10 * k} className={vs.markHalo} strokeWidth={5 * k} />
                    <circle r={10 * k} className={vs.markRing} strokeWidth={2 * k} />
                    <circle r={1.8 * k} className={vs.markDot} />
                    <text x={15 * k} y={-10 * k} className={vs.markText} style={{ fontSize: 13 * k, strokeWidth: 3 * k }}>{m.mark_id}</text>
                  </g>
                );
              })}
            </svg>
          </div>
        ) : <p className={c.note}>Loading the scan…</p>}
      </div>
      <div className={c.sliceRow}>
        <label className={c.sliceLabel}>
          <span data-testid="slice-readout">Slice {slice + 1} of {g.n}</span>
          <input type="range" min={0} max={g.n - 1} value={slice} aria-label="Axial slice" data-testid="slice-slider" onChange={(e) => setSlice(Number(e.target.value))} />
        </label>
        {result.reveal.search.slice_dwell && (
          <span className={c.dwellWrap}><DwellBar dwell={result.reveal.search.slice_dwell} plane="axial" n={g.n} current={slice} onPick={setSlice} findingSlicesViewed={result.reveal.search.finding_slices_viewed} /></span>
        )}
      </div>
      <figcaption className={c.caption}>
        <span><span className={c.keyCyan} /> Expert outline</span>
        <span><span className={c.keyAmber} /> Your mark</span>
        <span>Patient right is on the image left</span>
        {maskQ.isError && <span data-testid="case-mask-missing">The expert outlines could not be loaded.</span>}
      </figcaption>
    </figure>
  );
}
