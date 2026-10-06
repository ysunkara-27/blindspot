// / — landing + onboarding (SPEC §14.5): what Blindspot is, "Try the demo", then name or participant code, level and
// mode. The three-line explanation stays. Below 900 px the page explains and asks for a computer instead of starting.
import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { api, apiMode, isGateError } from '../api/client';
import { FOCAL_LABELS, LEVELS } from '../api/labels';
import { PageShell } from '../app/Shell';
import { SMALL_SCREEN_TEXT } from '../app/SmallScreen';
import { useNarrow } from '../app/useMediaQuery';
import { useTitle } from '../app/useTitle';
import { useSession } from '../state/session';
import type { Level, Mode } from '../types/contracts';
import { HeroFilm } from './HeroFilm';
import l from './Landing.module.css';

const looksLikeCode = (v: string) => /^[A-Za-z]{0,4}[-_]?\d{2,6}$/.test(v.trim());
/** The backend serves the curated demo playlist to this display name. */
export const DEMO_NAME = 'Demo';

type Start = { name: string; level: Level; mode: Mode; drillLabel?: string };

export function OnboardingPage() {
  useTitle(null);
  const navigate = useNavigate();
  const narrow = useNarrow();
  const setSession = useSession((st) => st.setSession);
  const projector = useSession((st) => st.projector);
  const [name, setName] = useState('');
  const [level, setLevel] = useState<Level>('MS3');
  const [mode, setMode] = useState<Mode>('practice');
  const [drillLabel, setDrillLabel] = useState('pneumothorax');

  const health = useQuery({ queryKey: ['health'], queryFn: api.health, retry: false });
  const begin = useMutation({
    mutationFn: (st: Start) => api.createSession({
      display_name: st.name,
      level: st.level,
      participant_code: looksLikeCode(st.name) ? st.name : null,
      mode: st.mode,
      settings: { projector, ...(st.mode === 'drill' ? { label: st.drillLabel } : {}) },
    }),
    onSuccess: (r, st) => {
      setSession({ sessionId: r.session_id, learnerId: r.learner_id, displayName: st.name, level: st.level, mode: st.mode, drillLabel: st.mode === 'drill' ? st.drillLabel : undefined });
      navigate('/read');
    },
  });
  const demoPending = begin.isPending && begin.variables?.name === DEMO_NAME;
  const formPending = begin.isPending && !demoPending;
  const failed = begin.isError && !isGateError(begin.error);
  const startDemo = () => begin.mutate({ name: DEMO_NAME, level, mode: 'practice' });

  const hero = (
    <section className={l.hero} aria-labelledby="landing-h">
      <div className={l.heroInner}>
        <div>
          <h1 id="landing-h" className={l.title}>Blindspot</h1>
          <p className={l.what}>
            A chest X-ray perception trainer for medical students. You read real radiographs that radiologists outlined,
            then see your own search replayed over the film.
          </p>
          <div className={l.lines} data-testid="three-lines">
            <p>Mark what you see. We'll show you how you looked.</p>
            <p>Each chest film has expert outlines behind it. After you submit, your search appears over the film.</p>
            <p>Miss types are based on your cursor, loupe and zoom — a proxy for where you looked.</p>
          </div>
          {narrow ? (
            <p className={l.demoNote}>{SMALL_SCREEN_TEXT}. Open this page on a computer to start.</p>
          ) : (
            <div className={l.ctaRow}>
              <button type="button" className={l.demo} onClick={startDemo} disabled={begin.isPending} data-testid="try-demo">
                {demoPending ? 'Starting…' : 'Try the demo'}
              </button>
              <span className={l.demoNote}>A short curated practice set. No sign-up.</span>
            </div>
          )}
          {failed && demoPending === false && begin.variables?.name === DEMO_NAME && (
            <p className={l.heroError} role="alert">The server did not answer, so the demo did not start. Reload the page and try again.</p>
          )}
        </div>
        <figure className={l.figure}>
          <div className={l.film}><HeroFilm /></div>
          <figcaption className={l.caption}>
            <span className={l.cyan}>Cyan</span> is the expert outline. <span className={l.amber}>Amber</span> is you: your marks and where you looked.
          </figcaption>
        </figure>
      </div>
    </section>
  );

  return (
    <PageShell hero={hero} width={1040}>
      <div className={l.below}>
      <section className={`${l.section} ${l.start}`} id="start" aria-labelledby="start-h">
        <h2 id="start-h" className={l.h2}>Start your own session</h2>
        {narrow && <p className={l.phone} data-testid="landing-small-screen">{SMALL_SCREEN_TEXT}. The modes are below so you know what to expect.</p>}
        <form onSubmit={(e) => { e.preventDefault(); if (name.trim() && !narrow) begin.mutate({ name: name.trim(), level, mode, drillLabel }); }}>
          <div className={l.who}>
            <label className={l.field}>
              <span>Your name or participant code <span className={l.hint}>(a code like P‑014 keeps your log across visits)</span></span>
              <input className={l.input} value={name} onChange={(e) => setName(e.target.value)} required maxLength={60} data-testid="name" autoComplete="nickname" />
            </label>
            <label className={l.field}>
              <span>Training level</span>
              <select className={l.input} value={level} onChange={(e) => setLevel(e.target.value as Level)} data-testid="level">
                {LEVELS.map((x) => <option key={x} value={x}>{x}</option>)}
              </select>
            </label>
          </div>

          <fieldset className={l.modes}>
            <legend>Mode</legend>
            <div className={l.modeGrid}>
              <div className={`${l.mode} ${mode === 'practice' || mode === 'review' ? l.modeOn : ''}`} data-testid="mode-practice">
                <label className={l.choice}>
                  <input type="radio" name="mode" value="practice" checked={mode === 'practice'} onChange={() => setMode('practice')} />
                  <span className={l.modeName}>Practice</span>
                </label>
                <p className={l.note}>Cases chosen for your level. Feedback, search replay and a debrief after every case.</p>
                <label className={l.subChoice}>
                  <input type="radio" name="mode" value="review" checked={mode === 'review'} onChange={() => setMode('review')} />
                  <span>Review missed: cases like the ones you missed before</span>
                </label>
              </div>
              <div className={`${l.mode} ${mode === 'drill' ? l.modeOn : ''}`} data-testid="mode-drill">
                <label className={l.choice}>
                  <input type="radio" name="mode" value="drill" checked={mode === 'drill'} onChange={() => setMode('drill')} />
                  <span className={l.modeName}>Drill</span>
                </label>
                <p className={l.note}>One finding at a time, mixed with normals, so you learn its look.</p>
                <label className={l.drillPick}>
                  <span>Drill on</span>
                  <select className={l.input} value={drillLabel} onChange={(e) => { setDrillLabel(e.target.value); setMode('drill'); }}
                    onFocus={() => setMode('drill')} data-testid="drill-label">
                    {FOCAL_LABELS.map((x) => <option key={x.id} value={x.id}>{x.display}</option>)}
                  </select>
                </label>
              </div>
              <div className={`${l.mode} ${mode === 'assess_A' || mode === 'assess_B' ? l.modeOn : ''}`} data-testid="mode-assessment">
                <span className={l.modeName}>Assessment</span>
                <p className={l.note}>A fixed 20-case set with no hints. Feedback at the end. Take A before practice and B after.</p>
                <label className={l.subChoice}>
                  <input type="radio" name="mode" value="assess_A" checked={mode === 'assess_A'} onChange={() => setMode('assess_A')} />
                  <span>Assessment A</span>
                </label>
                <label className={l.subChoice}>
                  <input type="radio" name="mode" value="assess_B" checked={mode === 'assess_B'} onChange={() => setMode('assess_B')} />
                  <span>Assessment B</span>
                </label>
              </div>
            </div>
          </fieldset>

          {failed && begin.variables?.name !== DEMO_NAME && (
            <p className={l.notice} role="alert">
              The server did not answer, so no session was started. Start it with <code>make api</code>, or open <code>/?mock=1</code> for the synthetic demo.
            </p>
          )}
          {!narrow && (
            <div className={l.startRow}>
              <button type="submit" className={l.primary} disabled={!name.trim() || begin.isPending} data-testid="start">
                {formPending ? 'Starting…' : 'Start reading'}
              </button>
            </div>
          )}
          <p className={l.health} data-testid="health">
            {health.isPending ? 'Checking the server…' : health.data?.ok
              ? apiMode().mode === 'mock'
                ? `Server: ok · synthetic demo, the cases are drawn shapes, not radiographs (${apiMode().reason}).`
                : `Server: ok · ${health.data.cases.toLocaleString()} cases${health.data.offline ? ' · tutor offline: built-in explanations' : ''}.`
              : 'Server: not reachable.'}
          </p>
        </form>
      </section>

      <aside className={l.side}>
      <section className={l.section} aria-labelledby="how-h" data-testid="how-it-works">
        <h2 id="how-h" className={l.h2}>How it works</h2>
        <p className={l.how}>
          Every film comes from ChestX-Det, where radiologists outlined each finding. When you submit, your marks are scored
          against those outlines: a mark counts when it lands on the expert mask or within a small margin of it. While you read, Blindspot records your cursor,
          loupe and zoom, and replays that search over the film. Each miss is then sorted with Kundel's types: never looked
          there (search), looked past it (recognition), looked and judged it normal (decision), or found it and named it wrong
          (interpretation); calls with no finding behind them are overcalls. Claude writes a short debrief only from facts the
          software computed, and a validator checks it against those facts; if it fails, you get a built-in explanation instead.
          The cursor is a proxy for where you looked, not eye tracking, so treat miss types as a strong hint rather than a verdict.
        </p>
      </section>

      <section className={l.section} aria-label="More">
        <ul className={l.links} data-testid="landing-links">
          <li><Link to="/progress">Reading log</Link></li>
          <li><Link to="/about">About</Link></li>
          <li><Link to="/cohort">Instructor (cohort)</Link></li>
          <li><Link to="/review">Expert review</Link></li>
        </ul>
      </section>
      </aside>
      </div>
    </PageShell>
  );
}
