// Ask the tutor (SPEC §8.9): up to 3 questions about this case.
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { api } from '../api/client';
import { track } from '../analytics';
import s from './Rail.module.css';

export function AskTutor({ attemptId }: { attemptId: string }) {
  const [q, setQ] = useState('');
  const [log, setLog] = useState<{ q: string; a: string }[]>([]);
  const [remaining, setRemaining] = useState(3);
  const m = useMutation({
    mutationFn: (question: string) => api.ask(attemptId, { question }),
    onSuccess: (r, question) => {
      setLog((l) => [...l, { q: question, a: r.answer }]);
      setRemaining(r.remaining);
      setQ('');
    },
  });
  const send = () => {
    const question = q.trim();
    if (question && remaining > 0 && !m.isPending) { track('ask'); m.mutate(question); }
  };
  return (
    <section className={s.section} aria-labelledby="ask-h" data-testid="ask">
      <div className={s.row}>
        <h3 id="ask-h" className={s.h3}>Ask the tutor</h3>
        <span className={s.muted}>{remaining} {remaining === 1 ? 'question' : 'questions'} left</span>
      </div>
      {log.map((x, i) => (
        <div key={i} className={s.qa}>
          <p className={s.q}>{x.q}</p>
          <p className={s.p}>{x.a}</p>
        </div>
      ))}
      {m.isError && <p className={s.notice}>The tutor is offline. Try again in a moment.</p>}
      {remaining > 0 && (
        <form className={s.askForm} onSubmit={(e) => { e.preventDefault(); send(); }}>
          <input
            className={s.input}
            value={q}
            maxLength={300}
            placeholder="Why does air look dark here?"
            aria-label="Your question about this case"
            onChange={(e) => setQ(e.target.value)}
          />
          <button type="submit" className={s.btn} disabled={!q.trim() || m.isPending}>{m.isPending ? 'Asking…' : 'Ask the tutor'}</button>
        </form>
      )}
    </section>
  );
}
