// Optional feedback after a test set. The ten statements are the standard System Usability Scale (Brooke 1996),
// 1 = strongly disagree … 5 = strongly agree, so answers stay comparable over time; the learner just sees
// "Give feedback". Posts to /api/sus; the server scores it (0–100) and we show the number it returns.
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/client';
import s from './Sus.module.css';

const SUS_ITEMS = [
  'I think that I would like to use this system frequently.',
  'I found the system unnecessarily complex.',
  'I thought the system was easy to use.',
  'I think that I would need the support of a technical person to be able to use this system.',
  'I found the various functions in this system were well integrated.',
  'I thought there was too much inconsistency in this system.',
  'I would imagine that most people would learn to use this system very quickly.',
  'I found the system very cumbersome to use.',
  'I felt very confident using the system.',
  'I needed to learn a lot of things before I could get going with this system.',
] as const;

const SCALE = [1, 2, 3, 4, 5] as const;

export function FeedbackForm({ learnerId }: { learnerId: string }) {
  const [open, setOpen] = useState(false);
  const [answers, setAnswers] = useState<(number | null)[]>(() => SUS_ITEMS.map(() => null));
  const m = useMutation({
    mutationFn: () => api.sus({ learner_id: learnerId, answers: answers as [number, number, number, number, number, number, number, number, number, number] }),
  });
  const complete = answers.every((a) => a != null);
  const left = answers.filter((a) => a == null).length;

  if (m.data) {
    return (
      <section className={s.sus} data-testid="feedback-done">
        <h2 className={s.h2}>Thank you</h2>
        <p className={s.p}>
          Your answers are saved. On the standard usability scale they come to{' '}
          <strong data-testid="feedback-score">{m.data.score.toFixed(1)}</strong> out of 100; products average about 68.
        </p>
      </section>
    );
  }
  if (!open) {
    return (
      <section className={s.sus}>
        <h2 className={s.h2}>How was Blindspot to use?</h2>
        <p className={s.p}>Optional. Ten short statements to agree or disagree with; it takes about a minute and helps us improve it.</p>
        <button type="button" className={s.secondary} onClick={() => setOpen(true)} data-testid="feedback-open">Give feedback</button>
      </section>
    );
  }
  return (
    <section className={s.sus} data-testid="feedback-form">
      <h2 className={s.h2}>Your feedback</h2>
      <p className={s.p}>For each statement, pick how much you agree. 1 = strongly disagree, 5 = strongly agree. “This system” means Blindspot.</p>
      <form onSubmit={(e) => { e.preventDefault(); if (complete) m.mutate(); }}>
        <ol className={s.items}>
          {SUS_ITEMS.map((q, i) => (
            <li key={i} className={s.item}>
              <fieldset className={s.fieldset}>
                <legend className={s.q}>{i + 1}. {q}</legend>
                <div className={s.scale}>
                  <span className={s.end}>Strongly disagree</span>
                  {SCALE.map((v) => (
                    <label key={v} className={`${s.opt} ${answers[i] === v ? s.optOn : ''}`}>
                      <input type="radio" name={`sus-${i}`} value={v} checked={answers[i] === v}
                        onChange={() => setAnswers((a) => a.map((x, j) => (j === i ? v : x)))} data-testid={`feedback-${i}-${v}`} />
                      <span>{v}</span>
                    </label>
                  ))}
                  <span className={s.end}>Strongly agree</span>
                </div>
              </fieldset>
            </li>
          ))}
        </ol>
        {m.isError && <p className={s.error}>Your answers were not saved. Check your connection and press Send feedback again.</p>}
        <button type="submit" className={s.primary} disabled={!complete || m.isPending} data-testid="feedback-submit">
          {m.isPending ? 'Saving…' : complete ? 'Send feedback' : `Answer all 10 (${left} left)`}
        </button>
      </form>
    </section>
  );
}
