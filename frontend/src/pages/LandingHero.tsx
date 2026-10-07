// The dark hero band shared by the landing and the access gate: the name, one sentence of purpose, one supporting
// line, and the drawn key to the colour logic. The caller supplies the actions under the copy (the landing's buttons;
// nothing on the gate, whose code form sits below).
import type { ReactNode } from 'react';
import { BrandMark } from '../brand/mark';
import { HeroFilm } from './HeroFilm';
import l from './Landing.module.css';

export const PURPOSE = 'Learn to see what you keep missing on medical images.';
export const SUPPORT = 'Read real radiographs and scans outlined by radiologists. Blindspot replays where you looked and explains each miss.';

export function LandingHero({ children, headingId = 'landing-h' }: { children?: ReactNode; headingId?: string }) {
  return (
    <section className={l.hero} aria-labelledby={headingId}>
      <div className={l.heroInner}>
        <div className={l.heroCopy}>
          <p className={l.name}><BrandMark size={18} className={l.nameMark} />Blindspot</p>
          <h1 id={headingId} className={l.title} data-testid="hero-purpose">{PURPOSE}</h1>
          <p className={l.support} data-testid="hero-support">{SUPPORT}</p>
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
