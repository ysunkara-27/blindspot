// "Your read" (SPEC §5.2, §14.2): marks, global findings, call it normal, hints, submit.
import type { Dispatch } from 'react';
import { labelDisplay, PATTERN_LABELS } from '../api/labels';
import { canSubmit, type ReadAction, type ReadState } from '../read/readState';
import type { HintResponse } from '../types/contracts';
import { ConfidenceChips } from './ConfidenceChips';
import s from './Rail.module.css';

export type HintsUi = { enabled: boolean; remaining: number; list: HintResponse[]; pending: boolean; error: string | null; onHint: () => void };

export function ReadRail({ read, dispatch, hints, confirmNormal, setConfirmNormal, onSubmit, submitting, submitError, alreadyRecorded, onNext }: {
  read: ReadState;
  dispatch: Dispatch<ReadAction>;
  hints: HintsUi;
  confirmNormal: boolean;
  setConfirmNormal: (v: boolean) => void;
  onSubmit: () => void;
  submitting: boolean;
  submitError: string | null;
  alreadyRecorded?: boolean;
  onNext?: () => void;
}) {
  const nPicked = read.marks.length + Object.keys(read.patterns).length;
  return (
    <div className={s.read}>
      <h2 className={s.h2}>Your read</h2>

      <section className={s.section} aria-labelledby="marks-h">
        <h3 id="marks-h" className={s.h3}>Marks <span className={s.count} data-testid="mark-count">{read.marks.length}</span></h3>
        {read.marks.length === 0 ? (
          <p className={s.muted}>{read.declaredNormal ? 'No marks on a normal call.' : 'Click the film where you see a finding.'}</p>
        ) : (
          <ul className={s.markList}>
            {read.marks.map((m) => (
              <li key={m.mark_id} className={`${s.markRow} ${read.selectedId === m.mark_id ? s.markRowOn : ''}`}>
                <button type="button" className={s.markPick} onClick={() => dispatch({ type: 'select', id: m.mark_id, popover: true })}>
                  <span className={s.markId}>{m.mark_id}</span>
                  <span>{m.label ? labelDisplay(m.label) : <em className={s.muted}>No label yet</em>}</span>
                </button>
                <ConfidenceChips value={m.confidence} name={m.mark_id} onChange={(c) => dispatch({ type: 'confidence', id: m.mark_id, confidence: c })} />
                <button type="button" className={s.x} aria-label={`Delete ${m.mark_id}`} onClick={() => dispatch({ type: 'delete', id: m.mark_id })}>×</button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={s.section} aria-labelledby="global-h">
        <h3 id="global-h" className={s.h3}>Global findings</h3>
        <ul className={s.checkList}>
          {PATTERN_LABELS.map((p) => {
            const conf = read.patterns[p.id];
            return (
              <li key={p.id} className={s.checkRow}>
                <label className={s.check}>
                  <input type="checkbox" checked={conf !== undefined} disabled={read.declaredNormal}
                    onChange={() => dispatch({ type: 'togglePattern', label: p.id })} />
                  <span>{p.display}</span>
                </label>
                {conf !== undefined && (
                  <ConfidenceChips value={conf} name={p.id} onChange={(c) => dispatch({ type: 'patternConfidence', label: p.id, confidence: c })} />
                )}
              </li>
            );
          })}
        </ul>
      </section>

      <section className={s.section} aria-labelledby="normal-h">
        <h3 id="normal-h" className={s.visuallyHidden}>Normal call</h3>
        {read.declaredNormal ? (
          <div className={s.normalOn} data-testid="normal-called">
            <p className={s.normalText}>You called this film normal.</p>
            <div className={s.row}>
              <span className={s.muted}>How sure?</span>
              <ConfidenceChips value={read.normalConfidence} name="normal" onChange={(c) => dispatch({ type: 'normalConfidence', confidence: c })} />
            </div>
            <button type="button" className={s.linkBtn} onClick={() => dispatch({ type: 'undoNormal' })}>Undo normal call</button>
          </div>
        ) : confirmNormal ? (
          <div className={s.confirm} role="alertdialog" aria-label="Confirm normal call">
            <p>This clears your {nPicked} {nPicked === 1 ? 'selection' : 'selections'}. Call it normal?</p>
            <div className={s.row}>
              <button type="button" className={s.btn} onClick={() => { dispatch({ type: 'callNormal' }); setConfirmNormal(false); }}>Clear and call it normal</button>
              <button type="button" className={s.linkBtn} onClick={() => setConfirmNormal(false)}>Keep my marks</button>
            </div>
          </div>
        ) : (
          <button type="button" className={s.btn} data-testid="call-normal"
            onClick={() => (nPicked ? setConfirmNormal(true) : dispatch({ type: 'callNormal' }))}>
            Call it normal <kbd className={s.kbd}>N</kbd>
          </button>
        )}
      </section>

      {hints.enabled && (
        <section className={s.section} aria-labelledby="hints-h">
          <div className={s.row}>
            <h3 id="hints-h" className={s.h3}>Hints</h3>
            <span className={s.muted} data-testid="hints-left">{hints.remaining} left · each costs 5 points</span>
          </div>
          {hints.list.length > 0 && (
            <ol className={s.hintList} data-testid="hint-list">
              {hints.list.map((h) => <li key={h.level}>{h.text}</li>)}
            </ol>
          )}
          {hints.error && <p className={s.error}>{hints.error}</p>}
          <button type="button" className={s.btn} disabled={hints.remaining <= 0 || hints.pending} onClick={hints.onHint} data-testid="hint-btn">
            {hints.pending ? 'Getting a hint…' : 'Get a hint'} <kbd className={s.kbd}>H</kbd>
          </button>
        </section>
      )}

      <div className={s.submitBar}>
        {submitError && <p className={s.error}>{submitError}</p>}
        {alreadyRecorded && onNext ? (
          <button type="button" className={s.primary} onClick={onNext} data-testid="next-case">
            Next case <kbd className={s.kbdLight}>→</kbd>
          </button>
        ) : (
          <button type="button" className={s.primary} disabled={!canSubmit(read) || submitting} onClick={onSubmit} data-testid="submit">
            {submitting ? 'Submitting…' : 'Submit read'} <kbd className={s.kbdLight}>Enter</kbd>
          </button>
        )}
        {!canSubmit(read) && <p className={s.mutedSmall}>Mark a finding, tick a global finding, or call it normal.</p>}
      </div>
    </div>
  );
}
