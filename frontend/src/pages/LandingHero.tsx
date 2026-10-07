// The dark hero band shared by the landing and the access gate: what Blindspot is, the three-line promise, and the
// drawn key to the colour logic. The caller supplies the actions under the promise.
import type { ReactNode } from 'react';
import { apiMode } from '../api/client';
import { availableModalities } from '../api/sessionOptions';
import { useHealth } from '../tutor/health';
import { HeroFilm } from './HeroFilm';
import l from './Landing.module.css';

export const WHAT = 'A chest X-ray perception trainer for medical students and anyone curious about how films are read. '
  + 'You read real radiographs that radiologists outlined, then see your own search replayed over the film.';

export function ThreeLines() {
  return (
    <div className={l.lines} data-testid="three-lines">
      <p>Mark what you see. We'll show you how you looked.</p>
      <p>Each chest film has expert outlines behind it. After you submit, your search appears over the film.</p>
      <p>Miss types are based on your cursor, magnifier and zoom — a proxy for where you looked.</p>
      <ScanTypesLine />
    </div>
  );
}

/** One more line once the library holds volumes too. Nothing is shown while the library is chest films only. */
function ScanTypesLine() {
  const health = useHealth();
  if (apiMode().mode === 'mock') return null;
  const have = availableModalities(health.data);
  if (!have.includes('ct') && !have.includes('mr')) return null;
  const parts = ['Chest X-ray', have.includes('ct') ? 'abdominal CT' : '', have.includes('mr') ? 'brain MRI' : ''].filter(Boolean);
  const text = parts.length === 3 ? `${parts[0]}, ${parts[1]} and ${parts[2]}.` : `${parts[0]} and ${parts[1]}.`;
  return <p data-testid="scan-types-line">{text}</p>;
}

export function LandingHero({ children, headingId = 'landing-h' }: { children?: ReactNode; headingId?: string }) {
  return (
    <section className={l.hero} aria-labelledby={headingId}>
      <div className={l.heroInner}>
        <div>
          <h1 id={headingId} className={l.title}>Blindspot</h1>
          <p className={l.what}>{WHAT}</p>
          <ThreeLines />
          {children}
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
}
