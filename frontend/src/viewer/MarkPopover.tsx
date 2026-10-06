// Label + confidence picker for one mark (SPEC §5.2). Screen-space, clamped inside the stage.
import { useEffect, useRef, type Dispatch } from 'react';
import { FOCAL_LABELS } from '../api/labels';
import type { DraftMark, ReadAction } from '../read/readState';
import type { Confidence } from '../types/contracts';
import { ConfidenceChips } from '../rail/ConfidenceChips';
import s from './Viewer.module.css';

const W = 330;
const H = 330;

export function MarkPopover({ mark, x, y, stageW, stageH, dispatch }: {
  mark: DraftMark; x: number; y: number; stageW: number; stageH: number; dispatch: Dispatch<ReadAction>;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"], button')?.focus({ preventScroll: true });
  }, [mark.mark_id]);
  const left = x + 20 + W > stageW ? Math.max(8, x - 20 - W) : x + 20;
  const top = Math.min(Math.max(8, y - 40), Math.max(8, stageH - H - 64));
  const done = () => dispatch({ type: 'closePopover' });
  return (
    <div
      ref={ref}
      className={s.popover}
      style={{ left, top, width: W }}
      role="dialog"
      aria-label={`Label for mark ${mark.mark_id}`}
      data-no-stage
      data-testid="mark-popover"
      onPointerDown={(e) => e.stopPropagation()}
      onDoubleClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => { if (e.key === 'Escape') { e.stopPropagation(); done(); } }}
    >
      <div className={s.popHead}>
        <span className={s.popId}>{mark.mark_id}</span>
        <span>What is it?</span>
      </div>
      <div className={s.popLabels}>
        {FOCAL_LABELS.map((l) => (
          <button key={l.id} type="button" className={`${s.popLabel} ${mark.label === l.id ? s.popLabelOn : ''}`}
            aria-pressed={mark.label === l.id}
            onClick={() => dispatch({ type: 'label', id: mark.mark_id, label: l.id })}>{l.display}</button>
        ))}
        <button type="button" className={`${s.popLabel} ${s.popNotSure} ${mark.label === 'not_sure' ? s.popLabelOn : ''}`}
          aria-pressed={mark.label === 'not_sure'}
          onClick={() => dispatch({ type: 'label', id: mark.mark_id, label: 'not_sure' })}>Not sure</button>
      </div>
      <div className={s.popConf}>
        <span>How sure?</span>
        <ConfidenceChips value={mark.confidence} onChange={(c: Confidence) => dispatch({ type: 'confidence', id: mark.mark_id, confidence: c })} name={`conf-${mark.mark_id}`} dark={false} />
      </div>
      <div className={s.popFoot}>
        <button type="button" className={s.popDelete} onClick={() => dispatch({ type: 'delete', id: mark.mark_id })}>Delete mark</button>
        <button type="button" className={s.popDone} onClick={done} disabled={!mark.label}>Done</button>
      </div>
    </div>
  );
}
