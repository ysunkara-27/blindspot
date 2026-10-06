// Read-only film for expert review: the image, the viewer's reveal layer (expert outlines in cyan) without
// animation, and the learner's marks in amber. Geometry comes from the full case (reviewer-only route; the attempt is
// long submitted). Fits the column width; no zoom or pan. Key it by item id so per-item state resets.
import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { ErrorBoundary } from '../app/ErrorBoundary';
import type { Arrow, OutcomeResult, RevealFinding, RevealMark } from '../types/contracts';
import { RevealLayer, type RevealView } from '../viewer/RevealLayer';
import type { DraftMark } from '../read/readState';
import vs from '../viewer/Viewer.module.css';
import type { DebriefItem } from './types';
import r from './Review.module.css';

const shortId = (id: string) => id.split('#').pop() ?? id;

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el);
    setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

export function ReviewFigure({ item }: { item: DebriefItem }) {
  const [wrapRef, boxW] = useWidth<HTMLDivElement>();
  const [imgFailed, setImgFailed] = useState(false);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);
  const cq = useQuery({ queryKey: ['dev-case', item.case_id], queryFn: () => api.devCase(item.case_id), enabled: !!item.case_id, retry: false, staleTime: Infinity });

  const c = cq.data;
  const width = c?.width ?? natural?.w ?? 1024;
  const height = c?.height ?? natural?.h ?? 1024;
  const scale = boxW > 0 ? boxW / width : 0;
  const k = scale > 0 ? 1 / scale : 1;
  const outcome = new Map((item.facts?.outcomes ?? []).map((o) => [o.target, o]));
  const factFinding = new Map((item.facts?.case.findings ?? []).map((f) => [f.id, f]));

  const findings: RevealFinding[] = (c?.findings ?? []).map((f) => {
    const id = shortId(f.finding_id);
    const ff = factFinding.get(id);
    return {
      finding_id: id,
      label: f.label,
      display: ff?.display ?? f.label,
      kind: f.kind,
      polygon: f.geometry.polygon ?? null,
      bbox: f.geometry.bbox,
      centroid: f.centroid,
      side: f.side ?? null,
      zones: f.zones ?? [],
      primary_zone: f.primary_zone ?? null,
      relative_location: f.relative_location ?? null,
      result: outcome.get(id)?.result as OutcomeResult | undefined,
    };
  });
  const marks: RevealMark[] = item.learner.marks.map((m) => {
    const res = outcome.get(m.mark_id)?.result;
    return { mark_id: m.mark_id, result: res === 'true_positive' || res === 'duplicate' ? res : 'false_positive', matched_finding: outcome.get(m.mark_id)?.matched ?? null };
  });
  // No arrows here: the spatial relations are long sentences without the on-film short label, and the reviewer
  // reads them in the facts list. Outlines + marks are what the reviewer needs on the film.
  const arrows: Arrow[] = [];
  const draft: DraftMark[] = item.learner.marks.map((m) => ({ ...m, label: m.label as DraftMark['label'], confidence: Math.min(5, Math.max(1, Math.round(m.confidence))) as DraftMark['confidence'] }));
  const view: RevealView = { findings, marks, arrows, heatmapUrl: null, showTrace: false };
  const imageUrl = item.image_url ?? api.imageUrl(item.case_id);
  // Expert geometry comes from /api/dev/cases (off unless BLINDSPOT_DEV=1). Without it: film + marks, and say so.
  const noOutlines = cq.isError;

  return (
    <figure className={r.figure}>
      <div ref={wrapRef} className={r.film} style={{ height: scale ? height * scale : undefined, aspectRatio: scale ? undefined : '1 / 1' }} data-testid="review-figure">
        {imgFailed ? (
          <p className={r.filmNote} data-testid="review-film-missing">
            The film for {item.case_id || 'this item'} could not be loaded{item.origin === 'curated' ? ' (curated bench item)' : ''}. Review the facts and debrief text instead.
          </p>
        ) : scale > 0 && (c || noOutlines) ? (
          <div className={`${vs.layer} ${vs.still}`} style={{ width, height, transform: `scale(${scale})` }}>
            <img src={imageUrl} alt={`Chest radiograph ${item.case_id}`} className={vs.image} width={width} height={height}
              onError={() => setImgFailed(true)} onLoad={(e) => !c && setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} data-testid="review-film" />
            {c && (
              <ErrorBoundary>
                <RevealLayer reveal={view} width={width} height={height} k={k} strokePx={2} marks={draft} />
              </ErrorBoundary>
            )}
            <svg className={vs.overlay} viewBox={`0 0 ${width} ${height}`} width={width} height={height} aria-hidden="true">
              {draft.map((m) => {
                const rm = marks.find((x) => x.mark_id === m.mark_id);
                return (
                  <g key={m.mark_id} transform={`translate(${m.x} ${m.y})`} data-testid={`review-mark-${m.mark_id}`}>
                    {rm?.result === 'false_positive' && <circle r={18 * k} className={vs.overcallRing} strokeWidth={2 * k} />}
                    <circle r={10 * k} className={vs.markHalo} strokeWidth={5 * k} />
                    <circle r={10 * k} className={vs.markRing} strokeWidth={2 * k} />
                    <circle r={1.8 * k} className={vs.markDot} />
                    <text x={15 * k} y={-10 * k} className={vs.markText} style={{ fontSize: 13 * k, strokeWidth: 3 * k }}>{m.mark_id}</text>
                  </g>
                );
              })}
            </svg>
          </div>
        ) : (
          <p className={r.filmNote}>Loading the film…</p>
        )}
      </div>
      <figcaption className={r.figcaption}>
        {noOutlines
          ? <span data-testid="review-no-outlines">Expert outlines are not available here (the case-geometry route is off); the findings are listed below.</span>
          : <><span className={r.keyCyan} /> Expert outline</>}
        <span className={r.keyAmber} /> Learner mark · patient right on image left
      </figcaption>
    </figure>
  );
}
