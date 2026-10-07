// The landing's paper sections: why this exists, how it works, tell us what you think, and the footer.
// The scan cards live in ScanCards.tsx (they read the library's health and provenance).
import { Link } from 'react-router-dom';
import { DISCLAIMER } from '../app/Shell';
import { FACTS, FEEDBACK_URL, PROXY_CAVEAT } from './copy';
import { GlyphExpert, GlyphLooked, GlyphMark } from './glyphs';
import l from '../pages/Landing.module.css';

export function WhySection() {
  return (
    <section className={l.band} aria-labelledby="why-h" data-testid="why-this-exists">
      <div className={l.inner}>
        <h2 id="why-h" className={l.h2}>Why this exists</h2>
        <p className={l.lede}>Reading images is a skill of looking, and it is taught less than it is needed.</p>
        <ul className={`${l.three} ${l.facts}`}>
          {FACTS.map((f) => (
            <li key={f.lead} className={l.fact}>
              <p className={l.factLead}>{f.lead}</p>
              <p className={l.factText}>{f.text}</p>
              <p className={l.factSource}>Source: <a href={f.url} target="_blank" rel="noreferrer">{f.source}</a></p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

const STEPS = [
  {
    title: 'Mark what you see',
    glyph: <GlyphMark />,
    text: 'Pick a finding, click where it is, and say how sure you are. Zoom, pan and use the magnifier as on a workstation. Finding nothing is a real answer.',
  },
  {
    title: 'See how you looked',
    glyph: <GlyphLooked />,
    text: 'Your cursor, magnifier and zoom are replayed over the film, and each miss is named: never looked there, looked past it, or looked and judged it normal.',
    caveat: PROXY_CAVEAT,
  },
  {
    title: 'Learn from the expert read',
    glyph: <GlyphExpert />,
    text: 'Radiologist outlines appear on the film with a short, fact-checked explanation, and a reading log shows your blind spots over time.',
  },
];

export function HowSection() {
  return (
    <section className={l.band} aria-labelledby="how-h" data-testid="how-it-works">
      <div className={l.inner}>
        <h2 id="how-h" className={l.h2}>How it works</h2>
        <p className={l.lede}>One film takes about two minutes, and every one of them ends with the expert read.</p>
        <ol className={`${l.three} ${l.steps}`}>
          {STEPS.map((s, i) => (
            <li key={s.title} className={l.step}>
              <div className={l.glyph}>{s.glyph}</div>
              <h3 className={l.stepTitle}><span className={l.stepNum}>{i + 1}</span>{s.title}</h3>
              <p className={l.stepText}>{s.text}</p>
              {s.caveat && <p className={l.caveat} data-testid="proxy-caveat">{s.caveat}</p>}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

export function FeedbackBand() {
  return (
    <section className={l.feedback} aria-labelledby="feedback-h" data-testid="feedback-band">
      <div className={l.inner}>
        <div className={l.feedbackGrid}>
          <div>
            <h2 id="feedback-h" className={l.h2}>Tell us what you think</h2>
            <p className={l.feedbackText}>
              Blindspot is an early build. If you&rsquo;re a radiologist, resident or student, two minutes of feedback shapes what we build next.
            </p>
            <div className={l.ctaRow}>
              <a href={FEEDBACK_URL} className={l.ctaInk} data-testid="give-feedback">Give feedback</a>
              <span className={l.ctaOr}>or reply to the email that brought you here</span>
            </div>
          </div>
          <ul className={l.moreLinks} aria-label="More" data-testid="landing-links">
            <li><Link to="/reference">Finding library</Link><span className={l.linkNote}>The findings you can mark, with example films.</span></li>
            <li><Link to="/about">How it&rsquo;s built</Link><span className={l.linkNote}>Data sources, scoring, the tutor and its limits.</span></li>
          </ul>
        </div>
      </div>
    </section>
  );
}

export function LandingFooter() {
  return (
    <footer className={l.foot} data-testid="disclaimer">
      <div className={l.inner}>
        <p className={l.footText}>{DISCLAIMER} Images are de-identified research radiographs and scans with expert annotations.</p>
        <p className={l.footLinks}><Link to="/about">About</Link> · <Link to="/progress">Reading log</Link></p>
      </div>
    </footer>
  );
}
