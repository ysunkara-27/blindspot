// /start — the start screen: who is reading (optional), what to practice, how many films, scan type. No training
// level is asked (the contract still carries one; "other" is sent). The mapping to POST /sessions is
// api/sessionOptions.ts::toSessionCreate.
import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { api, apiMode, isGateError } from '../api/client';
import { FOCAL_LABELS, PATTERN_LABELS } from '../api/labels';
import {
  COUNTS, loadRemembered, nextTest, readPath, remember, sameLearner, TEST_FILMS, toSessionCreate, weakSpotsNote, weakSpotsReady,
  type Count, type Practice, type StartForm,
} from '../api/sessionOptions';
import { PageShell } from '../app/Shell';
import { track } from '../analytics';
import { TutorNotice } from '../tutor/TutorNotice';
import { useTitle } from '../app/useTitle';
import { useSession } from '../state/session';
import { HALF_NORMAL } from './OnboardingPage';
import { ServerLine } from './ServerLine';
import p from './Pages.module.css';
import s from './Start.module.css';

const FINDINGS = [...FOCAL_LABELS, ...PATTERN_LABELS];

function readCount(v: unknown): number {
  const n = (v as { n_attempts?: unknown } | null)?.n_attempts;
  return typeof n === 'number' && Number.isFinite(n) ? n : 0;
}

export function StartPage() {
  useTitle('Start reading');
  const navigate = useNavigate();
  const setSession = useSession((st) => st.setSession);
  const projector = useSession((st) => st.projector);
  const [remembered] = useState(loadRemembered);
  const [name, setName] = useState(remembered?.name ?? '');
  const [editing, setEditing] = useState(!remembered);
  const [practice, setPractice] = useState<Practice>('mixed');
  const [finding, setFinding] = useState<string>(FINDINGS[0].id);
  const [count, setCount] = useState<Count>(10);

  const known = sameLearner(remembered, name);
  const mock = apiMode().mode === 'mock';
  // How many films this learner has read decides whether "My weak spots" has anything to go on.
  const log = useQuery({
    queryKey: ['learner-dashboard', remembered?.learnerId],
    queryFn: () => api.learnerDashboard(remembered!.learnerId),
    enabled: !!remembered && !mock,
    retry: false,
  });
  const reads = known && log.data ? readCount(log.data) : known && log.isPending && !mock ? null : 0;
  const weakOk = weakSpotsReady(reads);
  const chosen: Practice = practice === 'weak' && !weakOk ? 'mixed' : practice;
  const test = nextTest(known ? remembered.tests : []);

  const begin = useMutation({
    mutationFn: (form: StartForm) => api.createSession(toSessionCreate(form, { remembered, reads, projector })),
    onSuccess: (r, form) => {
      const typed = form.name.trim();
      remember(r.learner_id, typed);
      track('session_start');
      setSession({
        sessionId: r.session_id, learnerId: r.learner_id, displayName: typed, level: 'other', mode: r.mode,
        drillLabel: r.mode === 'drill' ? form.finding : undefined,
      });
      navigate(readPath());
    },
  });
  const failed = begin.isError && !isGateError(begin.error);

  const choice = (id: Practice, title: string, note: React.ReactNode, disabled = false, extra?: React.ReactNode) => (
    <label className={`${s.choice} ${chosen === id ? s.choiceOn : ''} ${disabled ? s.choiceOff : ''}`} data-testid={`choice-${id}`}>
      <input type="radio" name="practice" value={id} checked={chosen === id} disabled={disabled} onChange={() => setPractice(id)} data-testid={`practice-${id}`} />
      <span>
        <span className={s.name}>{title}</span>
        <span className={s.note} data-testid={`note-${id}`}>{note}</span>
        {extra}
      </span>
    </label>
  );

  return (
    <PageShell>
      <h1 className={p.h1}>Start reading</h1>
      <TutorNotice className={s.tutorNotice} />
      <form onSubmit={(e) => { e.preventDefault(); if (!begin.isPending) begin.mutate({ name, practice: chosen, finding, count }); }} data-testid="start-form">
        <section className={s.block} aria-labelledby="who-q">
          <h2 id="who-q" className={s.q}>Who is reading?</h2>
          {remembered && !editing ? (
            <>
              <p className={s.welcome} data-testid="welcome-back">{remembered.name ? `Welcome back, ${remembered.name}.` : 'Welcome back.'}</p>
              <p className={s.hint}>
                Your reading log continues from where you left it.{' '}
                <button type="button" className={s.linkBtn} onClick={() => { setEditing(true); setName(''); }} data-testid="change-name">Read as someone else</button>
              </p>
            </>
          ) : (
            <>
              <label htmlFor="start-name" className="sr-only">Your name or a personal code (optional)</label>
              <input id="start-name" className={s.input} value={name} onChange={(e) => setName(e.target.value)} maxLength={60} autoComplete="nickname"
                placeholder="Your name or a personal code (optional)" data-testid="name" />
              <p className={s.hint}>
                Leave blank to stay anonymous on this device. This browser remembers you, so your reading log carries on next time.
                A personal code such as MK-2041 opens the same log on another computer.
              </p>
            </>
          )}
        </section>

        <div className={s.block}><fieldset className={s.plain}>
          <legend className={s.q}>What do you want to practice?</legend>
          <div className={s.choices}>
            {choice('mixed', 'A mixed set', 'Films chosen to suit how you have read so far. The usual place to start.')}
            {choice('weak', 'My weak spots', reads == null ? 'Checking your reading log…' : weakSpotsNote(reads), !weakOk)}
            {choice('finding', 'One finding type', 'One kind of finding at a time, mixed with normal films, so you learn its look.', false, (
              <span className={s.pick}>
                <label htmlFor="finding-pick">Finding</label>
                <select id="finding-pick" className={s.select} value={finding} onChange={(e) => { setFinding(e.target.value); setPractice('finding'); }}
                  onFocus={() => setPractice('finding')} data-testid="finding-pick">
                  {FINDINGS.map((x) => <option key={x.id} value={x.id}>{x.display}</option>)}
                </select>
              </span>
            ))}
            {choice('test', 'Test myself', `A fixed set of ${TEST_FILMS} films with no hints. Feedback comes at the end.${
              test.set === 'B' ? ' You have taken the first set, so this is the second.' : test.repeat ? ' You have taken both sets, so this repeats the first.' : ''}`)}
          </div>
        </fieldset></div>

        <div className={s.block}><fieldset className={s.plain}>
          <legend className={s.q}>How many films?</legend>
          {chosen === 'test' ? (
            <p className={s.hint} style={{ margin: 0 }} data-testid="count-fixed">The test is always {TEST_FILMS} films.</p>
          ) : (
            <div className={s.counts} role="radiogroup" aria-label="How many films">
              {COUNTS.map((c) => (
                <label key={c} className={`${s.count} ${count === c ? s.countOn : ''}`}>
                  <input type="radio" name="count" value={c} checked={count === c} onChange={() => setCount(c)} data-testid={`count-${c}`} />
                  <span>{c}</span>
                </label>
              ))}
            </div>
          )}
        </fieldset></div>

        <section className={s.block} aria-labelledby="scan-q">
          <h2 id="scan-q" className={s.q}>Scan type</h2>
          <div className={s.scanRow}>
            <span className={s.chip} data-testid="scan-type">Chest X-ray</span>
            <span className={s.planned}>More body regions are planned</span>
          </div>
        </section>

        <div className={s.go}>
          <p className={s.half} data-testid="half-normal">{HALF_NORMAL}</p>
          {failed && (
            <p className={s.error} role="alert" data-testid="start-error">
              The server did not answer, so no set was started. Check your connection and press Start reading again.
            </p>
          )}
          <button type="submit" className={s.primary} disabled={begin.isPending} data-testid="start">
            {begin.isPending ? 'Starting…' : 'Start reading'}
          </button>
          <ServerLine className={s.health} />
        </div>
      </form>
    </PageShell>
  );
}
