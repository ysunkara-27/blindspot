// /feedback — the short feedback form (the same questions as the one on ysunkara.com/feedback, in Blindspot's own
// report-paper dress): role and years as pills, four 1–5 ratings as the reading room's "How sure?" chips, the
// verdict, what's missing (600 characters), an optional name or email, "Send feedback". The POST goes to the
// stats worker (feedbackModel.ts::feedbackEndpoint). Nothing is required but the ratings and the verdict.
import { useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { track } from '../analytics';
import { PageShell } from '../app/Shell';
import { useTitle } from '../app/useTitle';
import { useSession } from '../state/session';
import {
  EMPTY_FORM, failureMessage, feedbackEndpoint, MAX_CONTACT, MAX_MISSING, missingAnswer, RATING_QUESTIONS, ROLE_LABELS, ROLES, toPayload,
  VERDICT_LABELS, VERDICTS, YEARS, YEARS_LABELS, type FeedbackForm, type Rating, type RatingKey,
} from './feedbackModel';
import p from './Pages.module.css';
import s from './Feedback.module.css';

const LEVELS: Rating[] = [1, 2, 3, 4, 5];
const ENDPOINT = feedbackEndpoint(import.meta.env.VITE_ANALYTICS_URL as string | undefined);

type Status = { kind: 'idle' } | { kind: 'sending' } | { kind: 'sent' } | { kind: 'failed'; message: string };

/** A row of pills; one or none chosen. Clicking the chosen pill clears it, so an optional answer can be taken back. */
function Pills<T extends string>({ options, labels, value, onChange, name, label }: {
  options: readonly T[]; labels: Record<T, string>; value: T | null; onChange: (v: T | null) => void; name: string; label: string;
}) {
  return (
    <div className={s.pills} role="radiogroup" aria-label={label} data-testid={`fb-${name}`} data-value={value ?? ''}>
      {options.map((o) => (
        <button key={o} type="button" role="radio" aria-checked={value === o} className={`${s.pill} ${value === o ? s.pillOn : ''}`}
          onClick={() => onChange(value === o ? null : o)} data-testid={`fb-${name}-${o}`}>
          {labels[o]}
        </button>
      ))}
    </div>
  );
}

export function FeedbackPage() {
  useTitle('Feedback');
  const inSet = useSession((st) => !!st.session);
  const [form, setForm] = useState<FeedbackForm>(EMPTY_FORM);
  const [status, setStatus] = useState<Status>({ kind: 'idle' });
  // After a first attempt, whatever is still missing is framed in amber until it is answered.
  const [tried, setTried] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const missing = missingAnswer(form);
  const set = <K extends keyof FeedbackForm>(k: K, v: FeedbackForm[K]) => setForm((f) => ({ ...f, [k]: v }));
  const rate = (k: RatingKey, v: Rating) => setForm((f) => ({ ...f, ratings: { ...f.ratings, [k]: v } }));
  const needs = (field: RatingKey | 'verdict') => tried && (field === 'verdict' ? !form.verdict : form.ratings[field] == null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (status.kind === 'sending') return;
    setTried(true);
    const payload = toPayload(form);
    if (!payload || missing) {
      setStatus({ kind: 'failed', message: missing?.message ?? '' });
      formRef.current?.querySelector<HTMLElement>(`[data-testid="fb-${missing?.field}"] button`)?.focus();
      return;
    }
    setStatus({ kind: 'sending' });
    let res: Response;
    try {
      res = await fetch(ENDPOINT, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
    } catch {
      setStatus({ kind: 'failed', message: failureMessage(null, null) });
      return;
    }
    if (!res.ok) {
      let body: unknown = null;
      try { body = await res.json(); } catch { /* no JSON: the plain line is shown */ }
      setStatus({ kind: 'failed', message: failureMessage(res.status, body) });
      return;
    }
    track('feedback_sent');
    setStatus({ kind: 'sent' });
  };

  if (status.kind === 'sent') {
    return (
      <PageShell>
        <section data-testid="feedback-done" aria-live="polite">
          <h1 className={p.h1}>Thank you — received.</h1>
          <p className={p.lede}>Your answers help decide what Blindspot becomes next.</p>
          <p><Link to={inSet ? '/read' : '/start'} className={p.primaryLink} data-testid="feedback-back">Back to reading</Link></p>
        </section>
      </PageShell>
    );
  }

  const block = (title: string, note: ReactNode, body: ReactNode, testId: string, optional = true) => (
    <div className={s.block} data-testid={testId}>
      <fieldset className={s.plain}>
        <legend className={s.q}>{title}{optional && <span className={s.opt}>optional</span>}</legend>
        {note && <p className={s.hint}>{note}</p>}
        {body}
      </fieldset>
    </div>
  );

  return (
    <PageShell>
      <h1 className={p.h1}>Feedback</h1>
      <p className={p.lede}>
        Thanks for trying Blindspot. Five quick questions, about two minutes. Everything is optional except the
        four ratings and the last question.
      </p>
      <form ref={formRef} onSubmit={submit} noValidate data-testid="feedback-form">
        {block('Your role', null,
          <Pills options={ROLES} labels={ROLE_LABELS} value={form.role} onChange={(v) => set('role', v)} name="role" label="Your role" />, 'fb-role-block')}

        {block('Years in practice', null,
          <Pills options={YEARS} labels={YEARS_LABELS} value={form.years} onChange={(v) => set('years', v)} name="years" label="Years in practice" />, 'fb-years-block')}

        <div className={s.block} data-testid="fb-ratings">
          <h2 className={s.q}>How was it?</h2>
          <p className={s.hint}>Pick 1 to 5 for each; the ends are labelled.</p>
          <ol className={s.ratings}>
            {RATING_QUESTIONS.map((r) => {
              const value = form.ratings[r.key] ?? null;
              return (
                <li key={r.key} className={s.rating}>
                  <span className={s.ratingQ} id={`fb-q-${r.key}`}>{r.question}</span>
                  <span className={s.chipsCaptioned}>
                    <span className={s.cap} aria-hidden="true">{r.low}</span>
                    <span className={`${s.chips} ${needs(r.key) ? s.chipsNeeded : ''}`} role="radiogroup" aria-labelledby={`fb-q-${r.key}`}
                      data-testid={`fb-${r.key}`} data-value={value ?? ''}>
                      {LEVELS.map((c) => (
                        <button key={c} type="button" role="radio" aria-checked={value === c} aria-label={`${c} of 5`}
                          title={c === 1 ? `1 = ${r.low}` : c === 5 ? `5 = ${r.high}` : undefined}
                          className={`${s.chip} ${value === c ? s.chipOn : ''}`} onClick={() => rate(r.key, c)} data-testid={`fb-${r.key}-${c}`}>
                          {c}
                        </button>
                      ))}
                    </span>
                    <span className={s.cap} aria-hidden="true">{r.high}</span>
                  </span>
                </li>
              );
            })}
          </ol>
        </div>

        <div className={s.block} data-testid="fb-verdict-block">
          <fieldset className={s.plain}>
            <legend className={s.q}>Could this become a real tool?</legend>
            <div className={needs('verdict') ? s.needed : undefined}>
              <Pills options={VERDICTS} labels={VERDICT_LABELS} value={form.verdict} onChange={(v) => set('verdict', v)} name="verdict" label="Could this become a real tool?" />
            </div>
          </fieldset>
        </div>

        <div className={s.block}>
          <label htmlFor="fb-missing" className={s.q}>What's missing, or what would you change?<span className={s.opt}>optional</span></label>
          <textarea id="fb-missing" className={s.textarea} rows={4} maxLength={MAX_MISSING} value={form.missing}
            onChange={(e) => set('missing', e.target.value)} data-testid="fb-missing"
            placeholder="Cases you wanted, outlines that looked off, anything that got in the way…" />
          <p className={s.counter} aria-live="polite" data-testid="fb-missing-count">{form.missing.length} / {MAX_MISSING}</p>
        </div>

        <div className={s.block}>
          <label htmlFor="fb-contact" className={s.q}>Name or email<span className={s.opt}>optional, if we may follow up</span></label>
          <input id="fb-contact" className={s.input} type="text" maxLength={MAX_CONTACT} autoComplete="name" value={form.contact}
            onChange={(e) => set('contact', e.target.value)} placeholder="Dr A. Example · a@example.org" data-testid="fb-contact" />
        </div>

        <div className={s.go}>
          {status.kind === 'failed' && status.message && <p className={s.error} role="alert" data-testid="fb-error">{status.message}</p>}
          <button type="submit" className={s.primary} disabled={status.kind === 'sending'} data-testid="fb-send">
            {status.kind === 'sending' ? 'Sending…' : 'Send feedback'}
          </button>
          <p className={s.privacy}>Answers are stored privately and read by Yashaswi Sunkara. Nothing from your reads is attached.</p>
        </div>
      </form>
    </PageShell>
  );
}
