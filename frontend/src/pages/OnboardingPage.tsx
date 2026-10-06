// / — the landing (SPEC §14.5): what Blindspot is, the three-line promise, then "Start reading" (→ /start) or a
// sample set. A learner this browser remembers is welcomed back. Below 900 px the page explains and asks for a computer.
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { api, isGateError } from '../api/client';
import { forgetLearner, loadRemembered, readPath, SAMPLE_NAME, sampleSessionCreate } from '../api/sessionOptions';
import { PageShell } from '../app/Shell';
import { SMALL_SCREEN_TEXT } from '../app/SmallScreen';
import { useNarrow } from '../app/useMediaQuery';
import { useTitle } from '../app/useTitle';
import { useSession } from '../state/session';
import { LandingHero } from './LandingHero';
import { ServerLine } from './ServerLine';
import l from './Landing.module.css';

export const HALF_NORMAL = 'About half the films are normal — finding nothing is a real answer.';

export function OnboardingPage() {
  useTitle(null);
  const navigate = useNavigate();
  const narrow = useNarrow();
  const setSession = useSession((st) => st.setSession);
  const projector = useSession((st) => st.projector);
  const [remembered, setRemembered] = useState(loadRemembered);

  const sample = useMutation({
    mutationFn: () => api.createSession(sampleSessionCreate({ projector })),
    onSuccess: (r) => {
      setSession({ sessionId: r.session_id, learnerId: r.learner_id, displayName: SAMPLE_NAME, level: 'other', mode: 'practice' });
      navigate(readPath());
    },
  });
  const failed = sample.isError && !isGateError(sample.error);
  const startOver = () => { forgetLearner(); setRemembered(null); };

  const hero = (
    <LandingHero>
      {narrow ? (
        <p className={l.ctaNote}>{SMALL_SCREEN_TEXT}. Open this page on a computer to start.</p>
      ) : (
        <>
          {remembered && (
            <p className={l.welcome} data-testid="welcome-back">
              {remembered.name ? `Welcome back, ${remembered.name}.` : 'Welcome back.'} Your reading log is where you left it.
            </p>
          )}
          <div className={l.ctaRow}>
            <Link to="/start" className={l.cta} data-testid="start-reading">{remembered ? 'Continue' : 'Start reading'}</Link>
            <button type="button" className={l.ctaSecond} onClick={() => sample.mutate()} disabled={sample.isPending} data-testid="try-sample">
              {sample.isPending ? 'Starting…' : 'Try a sample set'}
            </button>
          </div>
          <p className={l.ctaNote}>
            {HALF_NORMAL} The sample set is six films picked to show what the feedback looks like. No sign-up.
          </p>
          {remembered && (
            <p className={l.ctaNote}>
              Not {remembered.name || 'you'}? <button type="button" className={l.heroLink} onClick={startOver} data-testid="forget-learner">Start as someone new</button>
            </p>
          )}
          {failed && <p className={l.heroError} role="alert">The server did not answer, so the sample set did not start. Check your connection and try again.</p>}
        </>
      )}
    </LandingHero>
  );

  return (
    <PageShell hero={hero} width={1040}>
      {narrow && <p className={l.phone} data-testid="landing-small-screen">{SMALL_SCREEN_TEXT}. Here is what to expect when you open it on a computer.</p>}
      <div className={l.below}>
        <section className={l.section} aria-labelledby="how-h" data-testid="how-it-works">
          <h2 id="how-h" className={l.h2}>How it works</h2>
          <ol className={l.steps}>
            <li>
              <h3>Read the film</h3>
              <p>Zoom, pan and use the magnifier, as on a workstation. Click what you think is a finding and name it, or call the film normal.</p>
            </li>
            <li>
              <h3>See what was there</h3>
              <p>Radiologists outlined every finding on these films. Your marks are scored against those outlines: a mark counts when it lands on the outline or just beside it.</p>
            </li>
            <li>
              <h3>See how you looked</h3>
              <p>Your cursor, magnifier and zoom are replayed over the film. Each miss is sorted: never looked there, looked past it, looked and judged it normal, or found it and named it wrong.</p>
            </li>
            <li>
              <h3>Get a short debrief</h3>
              <p>Claude explains the read using only facts the software computed, and a validator checks the text against them. If it fails, you get a built-in explanation instead.</p>
            </li>
          </ol>
          <p className={l.fine}>
            The cursor is a stand-in for your eyes, not eye tracking, so treat a miss type as a strong hint rather than a verdict.
          </p>
        </section>

        <aside className={l.side}>
          <section className={l.section} aria-labelledby="practice-h" data-testid="what-you-can-do">
            <h2 id="practice-h" className={l.h2}>What you can practice</h2>
            <dl className={l.options}>
              <dt>A mixed set</dt><dd>Films chosen to suit how you have read so far.</dd>
              <dt>Your weak spots</dt><dd>More of what you have missed, once you have read a few films.</dd>
              <dt>One finding type</dt><dd>Pneumothorax, nodule, effusion and ten more, mixed with normal films.</dd>
              <dt>A test</dt><dd>Twenty fixed films, no hints, feedback at the end.</dd>
            </dl>
          </section>
          <section className={l.section} aria-label="More">
            <ul className={l.links} data-testid="landing-links">
              <li><Link to="/reference">Finding library</Link></li>
              <li><Link to="/progress">Reading log</Link></li>
              <li><Link to="/about">About Blindspot</Link></li>
            </ul>
            <ServerLine className={l.health} />
          </section>
        </aside>
      </div>
    </PageShell>
  );
}
