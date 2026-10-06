// Read-only review of one submitted read, from a stored SubmitResult (GET /attempts/{aid}/result) and the film:
// the radiograph with the expert outlines in cyan, the learner's marks in amber and, when the result carries it, the
// search trace. Nothing animates and nothing can be changed. Same drawing code as the reading-room reveal.
// Props are the ones agreed with the pages side (docs/PROGRESS.md, FRONTEND SEAMS round 3); `summary` adds the
// merged "what was there" list and the search summary under the film.
import { useEffect, useRef, useState } from 'react';
import { ErrorBoundary } from '../app/ErrorBoundary';
import { ResultSummary } from '../rail/ResultSummary';
import type { SubmitResult } from '../types/contracts';
import { colorizeServerHeatmap } from '../viewer/heatmap';
import { RevealLayer, type RevealView } from '../viewer/RevealLayer';
import { SEARCH_LEGEND } from '../viewer/SearchExplainer';
import vs from '../viewer/Viewer.module.css';
import c from './CaseReview.module.css';

export type CaseReviewMark = { mark_id: string; x: number; y: number; label?: string | null; confidence?: number | null };
export type CaseReviewProps = {
  result: SubmitResult;
  imageUrl: string;
  width: number;
  height: number;
  marks: CaseReviewMark[];
  /** Also render the outcome list and the search summary under the film (default: the film only). */
  summary?: boolean;
};

export function CaseReview({ result, imageUrl, width, height, marks, summary = false }: CaseReviewProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [boxW, setBoxW] = useState(0);
  const [failed, setFailed] = useState(false);
  const [trace, setTrace] = useState<string | null>(null);
  const [showTrace, setShowTrace] = useState(true);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setBoxW(el.clientWidth));
    ro.observe(el);
    setBoxW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  const b64 = result.reveal.search.heatmap_png_b64;
  useEffect(() => {
    let live = true;
    if (!b64) return;
    colorizeServerHeatmap(b64).then((u) => { if (live) setTrace(u); }).catch(() => { /* no trace: outlines and marks still show */ });
    return () => { live = false; };
  }, [b64]);

  const scale = boxW > 0 && width > 0 ? boxW / width : 0;
  const k = scale > 0 ? 1 / scale : 1;
  const view: RevealView = {
    findings: result.reveal.findings, marks: result.reveal.marks, arrows: result.reveal.arrows,
    heatmapUrl: b64 ? trace : null, showTrace,
  };
  const verdict = new Map(result.reveal.marks.map((m) => [m.mark_id, m.result]));
  const n = result.reveal.findings.length;

  return (
    <div className={c.review} data-testid="case-review">
      <figure className={c.figure}>
        <div ref={ref} className={c.film} style={{ height: scale ? height * scale : undefined, aspectRatio: scale ? undefined : `${width} / ${height}` }}
          data-testid="case-figure" role="img" aria-label={`The film you read, with ${n} expert outline${n === 1 ? '' : 's'} and ${marks.length} of your marks`}>
          {failed ? (
            <p className={c.note} data-testid="case-film-missing">The film did not load. The outcomes and the debrief are still shown.</p>
          ) : scale > 0 ? (
            <div className={`${vs.layer} ${vs.still}`} style={{ width, height, transform: `scale(${scale})` }}>
              <img src={imageUrl} alt="" className={vs.image} width={width} height={height} draggable={false} onError={() => setFailed(true)} data-testid="case-film" />
              <ErrorBoundary>
                <RevealLayer reveal={view} width={width} height={height} k={k} strokePx={2} marks={marks} />
              </ErrorBoundary>
              <svg className={vs.overlay} viewBox={`0 0 ${width} ${height}`} width={width} height={height} aria-hidden="true">
                {marks.map((m) => (
                  <g key={m.mark_id} transform={`translate(${m.x} ${m.y})`} data-testid={`case-mark-${m.mark_id}`}>
                    {verdict.get(m.mark_id) === 'false_positive' && <circle r={18 * k} className={vs.overcallRing} strokeWidth={2 * k} />}
                    <circle r={10 * k} className={vs.markHalo} strokeWidth={5 * k} />
                    <circle r={10 * k} className={vs.markRing} strokeWidth={2 * k} />
                    <circle r={1.8 * k} className={vs.markDot} />
                    <text x={15 * k} y={-10 * k} className={vs.markText} style={{ fontSize: 13 * k, strokeWidth: 3 * k }}>{m.mark_id}</text>
                  </g>
                ))}
              </svg>
            </div>
          ) : null}
        </div>
        <figcaption className={c.caption}>
          <span><span className={c.keyCyan} /> Expert outline</span>
          <span><span className={c.keyAmber} /> Your mark</span>
          <span>Patient right is on the image left</span>
          {b64 && trace && (
            <button type="button" className={c.toggle} aria-pressed={showTrace} onClick={() => setShowTrace((v) => !v)} data-testid="case-search-toggle"
              title={SEARCH_LEGEND}>
              My search: {showTrace ? 'on' : 'off'}
            </button>
          )}
        </figcaption>
        {b64 && trace && showTrace && <p className={c.proxy}>{SEARCH_LEGEND}. A proxy, not a measurement.</p>}
      </figure>
      {summary && <div className={c.summary}><ResultSummary result={result} settle={false} /></div>}
    </div>
  );
}
