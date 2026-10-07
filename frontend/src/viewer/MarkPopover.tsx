// Label + confidence picker for one mark (SPEC §5.2). Screen-space. It sits beside the mark, never on top of it or of
// the magnifier lens around it, and a thin connector joins the two (round 3 audit fix).
// Two modes: 'full' (what is it? + how sure?) for a click with nothing armed, and 'confidence' (the label came from the
// finding picked in the rail; only "How sure are you?" is asked, and choosing closes it).
import { useEffect, useLayoutEffect, useRef, useState, type Dispatch } from 'react';
import { FOCAL_LABELS_BY_MODALITY, isModality, labelDisplay } from '../api/labels';
import type { DraftMark, PopoverMode, ReadAction } from '../read/readState';
import type { Confidence } from '../types/contracts';
import { ConfidenceChips } from '../rail/ConfidenceChips';
import { InfoButton } from '../reference/ReferenceDrawer';
import { placePopover } from './popoverPlace';
import s from './Viewer.module.css';

const W_FULL = 384;
const W_SHORT = 304;

export function MarkPopover({ mark, mode, x, y, stageW, stageH, clear, dispatch, modality }: {
  mark: DraftMark; mode: PopoverMode; x: number; y: number; stageW: number; stageH: number;
  /** Radius around the mark to keep uncovered: the lens radius when the magnifier is on, else the mark ring. */
  clear: number;
  dispatch: Dispatch<ReadAction>;
  /** The scan type picks the finding list (X-ray when absent). */
  modality?: string | null;
}) {
  const labels = FOCAL_LABELS_BY_MODALITY[isModality(modality) ? modality : 'cxr'];
  const ref = useRef<HTMLDivElement>(null);
  const short = mode === 'confidence' && !!mark.label;
  const w = short ? W_SHORT : W_FULL;
  const [h, setH] = useState(short ? 150 : 330);
  // Measured, so the placement uses the real height (the two modes differ a lot).
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setH((prev) => (Math.abs(el.offsetHeight - prev) > 1 ? el.offsetHeight : prev)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    // Full: focus the chosen (or first) label. Short: focus the dialog itself, so 1–5 work and Enter cannot hit a button.
    (ref.current?.querySelector<HTMLElement>('[data-autofocus]') ?? ref.current)?.focus({ preventScroll: true });
  }, [mark.mark_id, short]);
  const place = placePopover({ x, y }, { w, h }, { w: stageW, h: stageH }, clear);
  const done = () => dispatch({ type: 'closePopover' });
  const setConf = (c: Confidence) => dispatch({ type: 'confidence', id: mark.mark_id, confidence: c });
  const missing = !mark.label ? 'Pick what it is' : mark.confidence == null ? 'Say how sure you are' : null;
  return (
    <>
      <svg className={s.connector} width={stageW} height={stageH} aria-hidden="true" data-testid="popover-connector">
        <line x1={place.from.x} y1={place.from.y} x2={place.to.x} y2={place.to.y} className={s.connectorCasing} />
        <line x1={place.from.x} y1={place.from.y} x2={place.to.x} y2={place.to.y} className={s.connectorLine} />
        <circle cx={place.to.x} cy={place.to.y} r={3} className={s.connectorDot} />
      </svg>
      <div
        ref={ref}
        className={s.popover}
        style={{ left: place.left, top: place.top, width: w }}
        role="dialog"
        tabIndex={-1}
        aria-label={short ? `How sure are you about mark ${mark.mark_id}?` : `Label for mark ${mark.mark_id}`}
        data-no-stage
        data-testid="mark-popover"
        data-mode={short ? 'confidence' : 'full'}
        data-side={place.side}
        onPointerDown={(e) => e.stopPropagation()}
        onDoubleClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); done(); } }}
      >
        {short ? (
          <>
            <div className={s.popHead}>
              <span className={s.popId}>{mark.mark_id}</span>
              <span data-testid="popover-label">{labelDisplay(mark.label)}</span>
              {mark.label !== 'not_sure' && <InfoButton label={mark.label!} />}
              <button type="button" className={s.popChange} onClick={() => dispatch({ type: 'select', id: mark.mark_id, popover: true })}>Change</button>
            </div>
            <p className={s.popAsk} id={`ask-${mark.mark_id}`}>How sure are you?</p>
            <div className={s.popConfRow}>
              <ConfidenceChips value={mark.confidence} onChange={setConf} name={`conf-${mark.mark_id}`} captions />
            </div>
            <p className={s.popKeys}>Keys <kbd>1</kbd>–<kbd>5</kbd> work too.</p>
            <div className={s.popFoot}>
              <button type="button" className={s.popDelete} onClick={() => dispatch({ type: 'delete', id: mark.mark_id })}>Delete mark</button>
            </div>
          </>
        ) : (
          <>
            <div className={s.popHead}>
              <span className={s.popId}>{mark.mark_id}</span>
              <span>What is it?</span>
            </div>
            <div className={s.popLabels}>
              {labels.map((l, i) => (
                <span key={l.id} className={s.popLabelRow}>
                  <button type="button" className={`${s.popLabel} ${mark.label === l.id ? s.popLabelOn : ''}`}
                    aria-pressed={mark.label === l.id}
                    data-autofocus={mark.label === l.id || (!mark.label && i === 0) ? '' : undefined}
                    onClick={() => dispatch({ type: 'label', id: mark.mark_id, label: l.id })}>{l.display}</button>
                  <InfoButton label={l.id} display={l.display} />
                </span>
              ))}
              <span className={s.popLabelRow}>
                <button type="button" className={`${s.popLabel} ${s.popNotSure} ${mark.label === 'not_sure' ? s.popLabelOn : ''}`}
                  aria-pressed={mark.label === 'not_sure'}
                  data-autofocus={mark.label === 'not_sure' ? '' : undefined}
                  onClick={() => dispatch({ type: 'label', id: mark.mark_id, label: 'not_sure' })}>Not sure what it is</button>
              </span>
            </div>
            <p className={s.popAsk}>How sure are you?</p>
            <div className={s.popConfRow}>
              <ConfidenceChips value={mark.confidence} onChange={setConf} name={`conf-${mark.mark_id}`} captions />
            </div>
            <div className={s.popFoot}>
              <button type="button" className={s.popDelete} onClick={() => dispatch({ type: 'delete', id: mark.mark_id })}>Delete mark</button>
              <span className={s.popMissing} aria-live="polite">{missing ?? ''}</span>
              <button type="button" className={s.popDone} onClick={done} disabled={!mark.label}>Done</button>
            </div>
          </>
        )}
      </div>
    </>
  );
}
