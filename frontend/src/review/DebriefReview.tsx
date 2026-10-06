// Debrief review (SPEC §11.1): film with overlays, learner answer, FACTS summary, the debrief; the reviewer rates
// accuracy, teaching value and safety, and may write a correction. Keyboard: 1–5 rate (accuracy, then teaching),
// Y / N safety concern, C correction, Enter submit, ← / → move through the queue. The next unrated item auto-loads.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/client';
import { labelDisplay, OUTCOME_COPY, zoneDisplay } from '../api/labels';
import type { OutcomeResult } from '../types/contracts';
import { RatingScale } from './RatingScale';
import { ReviewFigure } from './ReviewFigure';
import type { Reviewer } from './reviewer';
import type { DebriefItem } from './types';
import r from './Review.module.css';

const PROV: Record<string, string> = { ai_draft: 'AI draft content', student_reviewed: 'Student-reviewed content', radiologist_reviewed: 'Radiologist-reviewed content' };
const resultText = (res: string | undefined) => (res ? OUTCOME_COPY[res as OutcomeResult]?.text ?? res : '—');

function typing(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  return !!t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable);
}

export function DebriefReview({ items, reviewer, onNeedReviewer }: { items: DebriefItem[]; reviewer: Reviewer; onNeedReviewer: () => void }) {
  const [idx, setIdx] = useState(0);
  const [done, setDone] = useState<Set<string>>(() => new Set());
  const [accuracy, setAccuracy] = useState<number | null>(null);
  const [teaching, setTeaching] = useState<number | null>(null);
  const [safety, setSafety] = useState<boolean | null>(null);
  const [comment, setComment] = useState('');
  const [field, setField] = useState<'accuracy' | 'teaching'>('accuracy');
  const [error, setError] = useState<string | null>(null);
  const commentRef = useRef<HTMLTextAreaElement>(null);
  const item = items[Math.min(idx, items.length - 1)];

  const reset = () => { setAccuracy(null); setTeaching(null); setSafety(null); setComment(''); setField('accuracy'); setError(null); };
  const go = useCallback((i: number) => { setIdx(Math.max(0, Math.min(items.length - 1, i))); reset(); }, [items.length]);

  const submit = useMutation({
    mutationFn: () => api.rate({
      reviewer: reviewer.name.trim(), role: reviewer.role, item_type: 'debrief', item_id: item.item_id,
      accuracy: accuracy!, teaching: teaching!, safety_flag: safety === true, comment: comment.trim() || null,
    }),
    onSuccess: () => {
      const nextDone = new Set(done).add(item.item_id);
      setDone(nextDone);
      // Auto-advance to the next unrated item (wrapping), or stay if all are rated.
      for (let k = 1; k <= items.length; k++) {
        const j = (idx + k) % items.length;
        if (!nextDone.has(items[j].item_id)) { go(j); return; }
      }
      reset();
    },
    onError: (e) => setError(`The rating was not saved (${(e as Error).message.slice(0, 80)}). Try again.`),
  });

  const trySubmit = useCallback(() => {
    if (!reviewer.name.trim()) { setError('Enter your name and role above before rating.'); onNeedReviewer(); return; }
    if (accuracy == null || teaching == null || safety == null) {
      setError('Rate accuracy and teaching value, and answer the safety question, before submitting.');
      return;
    }
    setError(null);
    submit.mutate();
  }, [reviewer.name, accuracy, teaching, safety, submit, onNeedReviewer]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) {
        if (e.key === 'Enter' && typing(e) && (e.metaKey || e.ctrlKey)) { e.preventDefault(); trySubmit(); }
        return;
      }
      if (typing(e)) return;
      const t = e.target as HTMLElement | null;
      if (t?.tagName === 'BUTTON' && !t.closest('form')) return; // queue nav buttons keep native keys
      if (/^[1-5]$/.test(e.key)) {
        const v = Number(e.key);
        if (field === 'accuracy') { setAccuracy(v); setField('teaching'); } else setTeaching(v);
        e.preventDefault();
      } else if (e.key === 'y' || e.key === 'Y') setSafety(true);
      else if (e.key === 'n' || e.key === 'N') setSafety(false);
      else if (e.key === 'c' || e.key === 'C') { e.preventDefault(); commentRef.current?.focus(); }
      else if (e.key === 'a' || e.key === 'A') setField('accuracy');
      else if (e.key === 't' || e.key === 'T') setField('teaching');
      else if (e.key === 'Enter') { e.preventDefault(); trySubmit(); }
      else if (e.key === 'ArrowRight') go(idx + 1);
      else if (e.key === 'ArrowLeft') go(idx - 1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [field, trySubmit, go, idx]);

  const facts = item.facts;
  const outcomes = useMemo(() => new Map((facts?.outcomes ?? []).map((o) => [o.target, o])), [facts]);
  const d = item.debrief;
  const allDone = done.size >= items.length;

  return (
    <div data-testid="debrief-review">
      <div className={r.queueBar}>
        <button type="button" className={r.navBtn} onClick={() => go(idx - 1)} disabled={idx === 0} aria-label="Previous item">←</button>
        <span data-testid="queue-pos">Item {idx + 1} of {items.length}</span>
        <button type="button" className={r.navBtn} onClick={() => go(idx + 1)} disabled={idx >= items.length - 1} aria-label="Next item">→</button>
        <span className={r.muted} data-testid="queue-done">{done.size} rated this visit</span>
        {item.flags > 0 && <span className={r.flag} data-testid="learner-flag">Flagged by a learner ({item.flags})</span>}
        {item.case_id.startsWith('syn_') && <span className={r.synthetic}>Synthetic test item</span>}
      </div>
      {allDone && <p className={r.notice} data-testid="queue-complete">Every item in the queue has a rating from this visit. Download the CSV above, or keep going to rate again.</p>}

      <div className={r.layout}>
        <div className={r.left}>
          <ReviewFigure key={item.item_id} item={item} />
          <section className={r.block} aria-label="Learner answer">
            <h3 className={r.h3}>Learner answer</h3>
            {item.learner.declared_normal && <p className={r.p}>Called the film normal.</p>}
            {!item.learner.marks.length && !item.learner.patterns.length && !item.learner.declared_normal && <p className={r.p}>No marks, no calls.</p>}
            <ul className={r.list}>
              {item.learner.marks.map((m) => (
                <li key={m.mark_id}><strong>{m.mark_id}</strong> · {labelDisplay(m.label)} · confidence {m.confidence} · <span className={r.muted}>{resultText(outcomes.get(m.mark_id)?.result)}</span></li>
              ))}
              {item.learner.patterns.map((p) => <li key={p.label}>{labelDisplay(p.label)} (global) · confidence {p.confidence}</li>)}
            </ul>
          </section>
          {facts && (
            <section className={r.block} aria-label="Facts" data-testid="facts-summary">
              <h3 className={r.h3}>Facts the tutor was given</h3>
              <p className={r.p}>{facts.case.is_normal ? 'Normal film.' : `${facts.case.findings.length} expert finding${facts.case.findings.length === 1 ? '' : 's'}.`} Learner level {facts.learner.level}; {facts.learner.hints_used} hint{facts.learner.hints_used === 1 ? '' : 's'}; {Math.round(facts.learner.time_to_submit_s)} s to submit.</p>
              <ul className={r.list}>
                {facts.case.findings.map((f) => (
                  <li key={f.id}><strong>{f.id}</strong> · {f.display}{f.side ? ` · ${f.side}` : ''}{f.primary_zone ? ` · ${zoneDisplay(f.primary_zone)}` : ''} · <span className={r.muted}>{resultText(outcomes.get(f.id)?.result)}</span></li>
                ))}
              </ul>
              <p className={r.pSmall}>Lung coverage {Math.round(facts.search.lung_coverage_pct)}%. Not visited: {facts.search.unvisited_review_areas.length ? facts.search.unvisited_review_areas.map(zoneDisplay).join(', ') : 'none'}.</p>
            </section>
          )}
        </div>

        <div className={r.right}>
          <section className={r.debrief} aria-label="Debrief" data-testid="review-debrief">
            <div className={r.meta}>
              <span>{item.source === 'template' ? 'Built-in explanation' : item.source === 'cache' ? 'Tutor (cached)' : item.source === 'live' ? 'Tutor' : item.origin === 'curated' ? 'Curated sample' : 'Debrief'}</span>
              {item.provenance && <span>· {PROV[item.provenance] ?? item.provenance}</span>}
              {item.validator_ok != null && <span>· validator {item.validator_ok ? 'passed' : 'failed'}</span>}
            </div>
            {d ? (
              <>
                <h3 className={r.headline}>{d.headline}</h3>
                {d.findings.map((f) => (
                  <div key={f.finding_id} className={r.dItem}>
                    <p className={r.p}><strong>{f.finding_id}</strong> · {resultText(f.result)}</p>
                    {f.where_to_look && <p className={r.p}>{f.where_to_look}</p>}
                    {f.what_it_looks_like.length > 0 && <ul className={r.list}>{f.what_it_looks_like.map((x, i) => <li key={i}>{x}</li>)}</ul>}
                    {f.why && <p className={r.pSmall}>{f.why}</p>}
                  </div>
                ))}
                {d.overcalls.map((o) => (
                  <div key={o.mark_id} className={r.dItem}>
                    <p className={r.p}><strong>{o.mark_id}</strong> · {o.explanation}</p>
                    {o.possible_mimics.length > 0 && <p className={r.pSmall}>Possible mimics: {[...new Set(o.possible_mimics)].join(', ')}</p>}
                  </div>
                ))}
                {d.search_coaching && <p className={r.p}><strong>Search.</strong> {d.search_coaching}</p>}
                {d.calibration_note && <p className={r.p}><strong>Confidence.</strong> {d.calibration_note}</p>}
                {d.next_step && <p className={r.p}><strong>Next.</strong> {d.next_step}</p>}
              </>
            ) : <p className={r.p}>No debrief text on this item.</p>}
            {item.flag_comments && <p className={r.flagNote}>Learner said: “{item.flag_comments}”</p>}
          </section>

          <form className={r.form} onSubmit={(e) => { e.preventDefault(); trySubmit(); }} data-testid="rating-form">
            <RatingScale name="accuracy" label="Accuracy" value={accuracy} onChange={(v) => { setAccuracy(v); setField('teaching'); }}
              active={field === 'accuracy'} onFocus={() => setField('accuracy')} low="1 · wrong" high="5 · fully correct" />
            <RatingScale name="teaching" label="Teaching value" value={teaching} onChange={setTeaching}
              active={field === 'teaching'} onFocus={() => setField('teaching')} low="1 · useless" high="5 · excellent" />
            <fieldset className={r.scale}>
              <legend className={r.scaleLegend}>Safety concern <span className={r.keyHint}>· Y / N</span></legend>
              <div className={r.scaleRow} role="radiogroup" aria-label="Safety concern">
                <button type="button" role="radio" aria-checked={safety === false} className={`${r.ynBtn} ${safety === false ? r.scaleOn : ''}`} onClick={() => setSafety(false)} data-testid="safety-no">No</button>
                <button type="button" role="radio" aria-checked={safety === true} className={`${r.ynBtn} ${safety === true ? r.scaleOn : ''}`} onClick={() => setSafety(true)} data-testid="safety-yes">Yes</button>
              </div>
            </fieldset>
            <label className={r.field}>
              <span>Correction <span className={r.keyHint}>· C to focus, ⌘/Ctrl + Enter to submit</span></span>
              <textarea ref={commentRef} className={r.textarea} rows={3} value={comment} onChange={(e) => setComment(e.target.value)}
                placeholder="What is wrong or missing, in a sentence or two." data-testid="correction"
                onKeyDown={(e) => { if (e.key === 'Escape') (e.target as HTMLTextAreaElement).blur(); }} />
            </label>
            {error && <p className={r.error} role="alert" data-testid="rating-error">{error}</p>}
            <button type="submit" className={r.submit} disabled={submit.isPending} data-testid="submit-rating">
              {submit.isPending ? 'Saving…' : 'Submit rating'} <span className={r.keyHintLight}>Enter</span>
            </button>
            {done.has(item.item_id) && <p className={r.pSmall} data-testid="rated-note">You rated this item on this visit.</p>}
          </form>
        </div>
      </div>
    </div>
  );
}
