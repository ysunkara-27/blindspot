// / — the landing (SPEC §14.5): one scrolling page, no form. The dark hero says what Blindspot is and offers
// "Start reading" (→ /start) or the sample set; below it, why this exists, how it works, what you can read, a
// feedback band, and the footer. A learner this browser remembers is welcomed back. Below 900 px the page still
// reads in full; only the buttons give way to a note asking for a computer (the reading room is desktop-only).
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { api, isGateError } from '../api/client';
import { forgetLearner, loadRemembered, readPath, SAMPLE_NAME, sampleSessionCreate } from '../api/sessionOptions';
import { BrandMark } from '../app/BrandMark';
import { Nav, SyntheticBadge } from '../app/Shell';
import { track } from '../analytics';
import { SMALL_SCREEN_TEXT } from '../app/SmallScreen';
import { useNarrow } from '../app/useMediaQuery';
import { useTitle } from '../app/useTitle';
import { useSession } from '../state/session';
import { FREE_LINE } from '../landing/copy';
import { ScanCards } from '../landing/ScanCards';
import { FeedbackBand, HowSection, LandingFooter, WhySection } from '../landing/Sections';
import { LandingHero } from './LandingHero';
import s from '../app/Shell.module.css';
import l from './Landing.module.css';

export const HALF_NORMAL = 'About half the films are normal — finding nothing is a real answer.';
/** CT / MR normals are slabs the dataset labelled lesion-free, not radiologist-certified normals (About says so). */
export const HALF_NORMAL_STUDIES = 'About half the studies show no lesion — finding nothing is a real answer.';

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
      track('session_start');
      navigate(readPath());
    },
  });
  const failed = sample.isError && !isGateError(sample.error);
  const startOver = () => { forgetLearner(); setRemembered(null); };

  return (
    <div className={s.page} data-testid="landing">
      <header className={s.pageHeader}>
        <Link to="/" className={s.brand}><BrandMark size={22} className={s.brandMark} />Blindspot</Link>
        <SyntheticBadge />
        <span className={s.spacer} />
        <Nav />
      </header>
      <LandingHero>
        {narrow ? (
          <p className={l.ctaNote} data-testid="landing-small-screen">{SMALL_SCREEN_TEXT}. Open this page on a computer to start.</p>
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
            <p className={l.ctaNote} data-testid="free-line">{FREE_LINE}</p>
            {remembered && (
              <p className={l.ctaNote}>
                Not {remembered.name || 'you'}? <button type="button" className={l.heroLink} onClick={startOver} data-testid="forget-learner">Start as someone new</button>
              </p>
            )}
            {failed && <p className={l.heroError} role="alert">The server did not answer, so the sample set did not start. Check your connection and try again.</p>}
          </>
        )}
      </LandingHero>
      <main className={l.main}>
        <WhySection />
        <HowSection />
        <ScanCards />
        <FeedbackBand />
      </main>
      <LandingFooter />
    </div>
  );
}
