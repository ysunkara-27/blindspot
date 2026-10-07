// "Your read" (SPEC §5.2, §14.2), in the order of thinking:
//   1. Findings you can point to — pick what you see, then click where it is; your marks.
//   2. Findings of the whole film — no single spot to click.
//   3. Nothing abnormal — call it normal (turns 1 and 2 off until undone).
//   then hints and Submit read. Every answer needs a confidence the learner chose; nothing is preselected.
// Volumes (CT / MR): the same rail. The finding list is the scan type's; a mark row says which slice it sits on
// ("M1 · axial 12") and jumps there; a mass-like mark gets the size step ("How big is it?": Measure → Record / Skip).
import { useEffect, useRef, type Dispatch } from 'react';
import { FOCAL_LABELS_BY_MODALITY, isModality, labelDisplay, PATTERN_LABELS } from '../api/labels';
import { needsSize, submitBlockers, type DraftMark, type ReadAction, type ReadState } from '../read/readState';
import { InfoButton } from '../reference/ReferenceDrawer';
import type { HintResponse } from '../types/contracts';
import { fmtMm } from '../viewer/volume/dwell';
import { markPlace } from '../viewer/volume/nav';
import { ConfidenceChips } from './ConfidenceChips';
import { plainText } from './copy';
import s from './Rail.module.css';

export type HintsUi = { enabled: boolean; remaining: number; list: HintResponse[]; pending: boolean; error: string | null; onHint: () => void };

/** The size step (volumes): what the caliper holds right now and the three actions. */
export type SizeUi = {
  /** The mark being measured (Measure was pressed). */
  forMark: string | null;
  /** Length of the current caliper line in mm, when one is drawn. */
  drawnMm: number | null;
  onMeasure: (id: string) => void;
  onRecord: (id: string) => void;
  onSkip: (id: string) => void;
};

export function ReadRail({ read, dispatch, hints, confirmNormal, setConfirmNormal, onSubmit, submitting, submitError, alreadyRecorded, onNext, modality, onJump, size }: {
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
  /** The scan type picks the finding lists (X-ray when absent). */
  modality?: string | null;
  /** Volumes: show the slice a mark sits on. */
  onJump?: (m: DraftMark) => void;
  /** Volumes: the size step. */
  size?: SizeUi;
}) {
  const mod = isModality(modality) ? modality : 'cxr';
  const focal = FOCAL_LABELS_BY_MODALITY[mod];
  const patterns = mod === 'cxr' ? PATTERN_LABELS : [];
  const film = mod === 'cxr' ? 'film' : 'scan'; // X-ray copy stays byte-identical; a CT / MR study is "the scan"
  const nPicked = read.marks.length + Object.keys(read.patterns).length;
  const blockers = submitBlockers(read);
  const off = read.declaredNormal;
  const offNote = off ? <p className={s.offNote}>Off while the {film} is called normal.</p> : null;
  // What the learner just asked for must be on screen: the normal call's "How sure?" and the newest hint sit low in
  // the rail, behind the sticky Submit bar on a laptop.
  const normalRef = useRef<HTMLDivElement>(null);
  const hintsRef = useRef<HTMLOListElement>(null);
  useEffect(() => { if (off) normalRef.current?.scrollIntoView({ block: 'nearest' }); }, [off]);
  const nHints = hints.list.length;
  useEffect(() => { if (nHints) hintsRef.current?.lastElementChild?.scrollIntoView({ block: 'nearest' }); }, [nHints]);
  return (
    <div className={s.read}>
      <h2 className={s.h2}>Your read</h2>

      {/* 1 — findings you can point to */}
      <section className={`${s.section} ${off ? s.groupOff : ''}`} aria-labelledby="point-h" data-testid="group-point">
        <h3 id="point-h" className={s.h3}><span className={s.step}>1</span>Findings you can point to</h3>
        <p className={s.help}>Pick what you see, then click where it is on the {film}.</p>
        {offNote}
        <div data-tour="pick">
          <p className={s.sub} id="pick-h">What do you see?</p>
          <div className={s.pickGrid} role="group" aria-labelledby="pick-h">
            {focal.map((l) => (
              <span key={l.id} className={s.pickCell}>
                <button type="button" className={`${s.pick} ${read.armed === l.id ? s.pickOn : ''}`} aria-pressed={read.armed === l.id}
                  disabled={off} onClick={() => dispatch({ type: 'arm', label: l.id })} data-testid={`arm-${l.id}`}>
                  {l.display}
                </button>
                <InfoButton label={l.id} display={l.display} />
              </span>
            ))}
            <span className={s.pickCell}>
              <button type="button" className={`${s.pick} ${s.pickNotSure} ${read.armed === 'not_sure' ? s.pickOn : ''}`} aria-pressed={read.armed === 'not_sure'}
                disabled={off} onClick={() => dispatch({ type: 'arm', label: 'not_sure' })} data-testid="arm-not_sure">
                Not sure what it is
              </button>
            </span>
          </div>
          <p className={s.armedLine} aria-live="polite" data-testid="armed-line">
            {read.armed ? <><strong>{labelDisplay(read.armed)}</strong> picked. Now click the {film} where you see it.</> : `Or click the ${film} first and name it there.`}
          </p>
        </div>

        <div data-tour="confidence" className={s.marksBlock}>
          <p className={s.sub}>Your marks <span className={s.count} data-testid="mark-count">{read.marks.length}</span></p>
          {read.marks.length === 0 ? (
            <p className={s.mutedLine}>{off ? 'No marks on a normal call.' : 'None yet. Each mark also asks how sure you are.'}</p>
          ) : (
            <ul className={s.markList}>
              {read.marks.map((m) => {
                const need = !m.label && m.confidence == null ? 'needs a label and a confidence' : !m.label ? 'needs a label' : m.confidence == null ? 'needs a confidence' : null;
                const place = read.volumetric ? markPlace(m) : null;
                const st = read.sizes[m.mark_id];
                const askSize = read.volumetric && !!size && needsSize(m.label) && m.confidence != null;
                const measuring = askSize && size!.forMark === m.mark_id;
                return (
                  <li key={m.mark_id} className={`${s.markRow} ${read.selectedId === m.mark_id ? s.markRowOn : ''}`} data-testid={`mark-row-${m.mark_id}`}>
                    <button type="button" className={s.markPick} onClick={() => { onJump?.(m); dispatch({ type: 'select', id: m.mark_id, popover: true }); }} title={place ? `Change this mark (on ${place})` : 'Change this mark'}>
                      <span className={s.markId}>{m.mark_id}</span>
                      <span>
                        {m.label ? labelDisplay(m.label) : <em className={s.muted}>No label yet</em>}
                        {place ? <span className={s.markPlace} data-testid={`mark-place-${m.mark_id}`}> · {place}</span> : null}
                      </span>
                    </button>
                    <ConfidenceChips value={m.confidence} name={m.mark_id} needed onChange={(c) => dispatch({ type: 'confidence', id: m.mark_id, confidence: c })} />
                    <button type="button" className={s.x} aria-label={`Delete ${m.mark_id}`} onClick={() => dispatch({ type: 'delete', id: m.mark_id })}>×</button>
                    {need && <span className={s.need} data-testid={`mark-need-${m.mark_id}`}>{need}</span>}
                    {askSize && (
                      <div className={s.sizeStep} data-testid={`size-${m.mark_id}`} data-state={st?.kind ?? (measuring ? 'measuring' : 'pending')}>
                        {st?.kind === 'recorded' ? (
                          <>
                            <span className={s.sizeLabel}>Size: <strong>{fmtMm(st.m.long_mm)} mm</strong></span>
                            <button type="button" className={s.linkBtn} onClick={() => size!.onMeasure(m.mark_id)} data-testid={`remeasure-${m.mark_id}`}>Measure again</button>
                          </>
                        ) : st?.kind === 'skipped' ? (
                          <>
                            <span className={s.sizeLabel}>Size: <em className={s.muted}>skipped</em></span>
                            <button type="button" className={s.linkBtn} onClick={() => size!.onMeasure(m.mark_id)} data-testid={`remeasure-${m.mark_id}`}>Measure</button>
                          </>
                        ) : (
                          <>
                            <span className={s.sizeLabel}>How big is it?</span>
                            {measuring ? (
                              <>
                                <span className={s.sizeHint} aria-live="polite" data-testid={`size-readout-${m.mark_id}`}>
                                  {size!.drawnMm != null ? `${fmtMm(size!.drawnMm)} mm` : 'Drag from edge to edge on the scan'}
                                </span>
                                <button type="button" className={s.btn} disabled={size!.drawnMm == null} onClick={() => size!.onRecord(m.mark_id)} data-testid={`record-${m.mark_id}`}>
                                  Record <kbd className={s.kbd}>Enter</kbd>
                                </button>
                              </>
                            ) : (
                              <button type="button" className={s.btn} onClick={() => size!.onMeasure(m.mark_id)} data-testid={`measure-${m.mark_id}`} data-tour="measure">
                                Measure <kbd className={s.kbd}>C</kbd>
                              </button>
                            )}
                            <button type="button" className={s.linkBtn} onClick={() => size!.onSkip(m.mark_id)} data-testid={`skip-${m.mark_id}`}>Skip</button>
                          </>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </section>

      <div data-tour="whole-normal">
        {/* 2 — findings of the whole film */}
        <section className={`${s.section} ${off ? s.groupOff : ''}`} aria-labelledby="global-h" data-testid="group-whole">
          <h3 id="global-h" className={s.h3}><span className={s.step}>2</span>Findings of the whole {film}</h3>
          <p className={s.help}>No single spot to click; tick it if the whole {film} shows it.</p>
          {offNote}
          {patterns.length === 0 && <p className={s.mutedLine} data-testid="no-patterns">None for this scan type.</p>}
          <ul className={s.checkGrid}>
            {patterns.map((p) => (
              <li key={p.id} className={s.checkRow}>
                <label className={s.check}>
                  <input type="checkbox" checked={p.id in read.patterns} disabled={off}
                    onChange={() => dispatch({ type: 'togglePattern', label: p.id })} data-testid={`pattern-${p.id}`} />
                  <span>{p.display}</span>
                </label>
                <InfoButton label={p.id} display={p.display} />
              </li>
            ))}
          </ul>
          {/* Each ticked finding asks how sure, on its own line under the list. */}
          {patterns.filter((p) => p.id in read.patterns).map((p) => (
            <div key={p.id} className={s.sureRow} data-testid={`sure-${p.id}`}>
              <span className={s.sureLabel}><strong>{p.display}</strong> · How sure?</span>
              <ConfidenceChips value={read.patterns[p.id]} name={p.id} needed captions onChange={(c) => dispatch({ type: 'patternConfidence', label: p.id, confidence: c })} />
            </div>
          ))}
        </section>

        {/* 3 — nothing abnormal */}
        <section className={s.section} aria-labelledby="normal-h" data-testid="group-normal">
          <h3 id="normal-h" className={s.h3}><span className={s.step}>3</span>Nothing abnormal</h3>
          <p className={s.help}>Use this only if you see no findings at all.</p>
          {read.declaredNormal ? (
            <div className={s.normalOn} data-testid="normal-called" ref={normalRef}>
              <p className={s.normalText}>You called this {film} normal.</p>
              <div className={s.sureRow}>
                <span className={s.sureLabel}>How sure?</span>
                <ConfidenceChips value={read.normalConfidence} name="normal" needed captions onChange={(c) => dispatch({ type: 'normalConfidence', confidence: c })} />
              </div>
              <button type="button" className={s.btn} onClick={() => dispatch({ type: 'undoNormal' })} data-testid="undo-normal">Undo normal call</button>
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
      </div>

      {hints.enabled && (
        <section className={s.section} aria-labelledby="hints-h" data-tour="hints">
          <div className={s.row}>
            <h3 id="hints-h" className={s.h3} data-testid="hints-left">Hints — {hints.remaining} left</h3>
            <button type="button" className={s.btn} disabled={hints.remaining <= 0 || hints.pending} onClick={hints.onHint} data-testid="hint-btn">
              {hints.pending ? 'Getting a hint…' : 'Get a hint'} <kbd className={s.kbd}>H</kbd>
            </button>
          </div>
          {hints.list.length > 0 && (
            <ol className={s.hintList} data-testid="hint-list" ref={hintsRef}>
              {hints.list.map((h, i) => (
                <li key={h.level} className={s.hintCard}>
                  <span className={s.hintN}>Hint {i + 1}</span>
                  {plainText(h.text)}
                </li>
              ))}
            </ol>
          )}
          {hints.error && <p className={s.error}>{hints.error}</p>}
        </section>
      )}

      <div className={s.submitBar} data-tour="submit">
        {submitError && <p className={s.error}>{submitError}</p>}
        {alreadyRecorded && onNext ? (
          <button type="button" className={s.primary} onClick={onNext} data-testid="next-case">
            Next case <kbd className={s.kbdLight}>→</kbd>
          </button>
        ) : (
          <button type="button" className={s.primary} disabled={blockers.length > 0 || submitting} onClick={onSubmit} data-testid="submit"
            aria-describedby={blockers.length ? 'submit-help' : undefined}>
            {submitting ? 'Submitting…' : 'Submit read'} <kbd className={s.kbdLight}>Enter</kbd>
          </button>
        )}
        {blockers.length > 0 && !alreadyRecorded && (
          <p className={s.submitHelp} id="submit-help" data-testid="submit-help" aria-live="polite">
            {blockers.length === 1 ? (/[.?!]$/.test(blockers[0]) ? blockers[0] : `${blockers[0]}.`) : `${blockers.join(' · ')}.`}
          </p>
        )}
      </div>
    </div>
  );
}
