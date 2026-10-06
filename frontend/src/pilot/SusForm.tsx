// System Usability Scale (Brooke 1996): the 10 standard statements, 1 = strongly disagree … 5 = strongly agree.
// Posts to /api/sus; the server scores it (0–100) and we show the number it returns.
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

export function SusForm({ learnerId }: { learnerId: string }) {
  const [open, setOpen] = useState(false);
  const [answers, setAnswers] = useState<(number | null)[]>(() => SUS_ITEMS.map(() => null));
  const m = useMutation({
    mutationFn: () => api.sus({ learner_id: learnerId, answers: answers as [number, number, number, number, number, number, number, number, number, number] }),
  });
  const complete = answers.every((a) => a != null);
  const left = answers.filter((a) => a == null).length;

  if (m.data) {
    return (
      <section className={s.sus} data-testid="sus-done">
        <h2 className={s.h2}>Thank you</h2>
        <p className={s.p}>Your System Usability Scale score is <strong data-testid="sus-score">{m.data.score.toFixed(1)}</strong> out of 100. Scores above 68 are above average.</p>
      </section>
    );
  }
  if (!open) {
    return (
      <section className={s.sus}>
        <h2 className={s.h2}>One minute of feedback</h2>
        <p className={s.p}>Ten short statements about using Blindspot. Your answers help us improve it.</p>
        <button type="button" className={s.primary} onClick={() => setOpen(true)} data-testid="sus-open">Take the SUS survey</button>
      </section>
    );
  }
  return (
    <section className={s.sus} data-testid="sus-form">
      <h2 className={s.h2}>System Usability Scale</h2>
      <p className={s.p}>For each statement, pick how much you agree. 1 = strongly disagree, 5 = strongly agree.</p>
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
                        onChange={() => setAnswers((a) => a.map((x, j) => (j === i ? v : x)))} data-testid={`sus-${i}-${v}`} />
                      <span>{v}</span>
                    </label>
                  ))}
                  <span className={s.end}>Strongly agree</span>
                </div>
              </fieldset>
            </li>
          ))}
        </ol>
        {m.isError && <p className={s.error}>Your answers were not saved. Check the connection and submit again.</p>}
        <button type="submit" className={s.primary} disabled={!complete || m.isPending} data-testid="sus-submit">
          {m.isPending ? 'Saving…' : complete ? 'Submit survey' : `Answer all 10 (${left} left)`}
        </button>
      </form>
    </section>
  );
}
