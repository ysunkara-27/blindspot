import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { apiMode } from '../api/client';
import { BrandMark } from './BrandMark';
import s from './Shell.module.css';

export const DISCLAIMER = 'For education. Not for clinical use.';

export function Footer({ className }: { className?: string }) {
  return (
    <footer className={className ?? s.footer} data-testid="disclaimer">
      {DISCLAIMER} Images are de-identified research radiographs with expert annotations.
    </footer>
  );
}

/** `short` is for the reading-room header, where width is tight; the title carries the full explanation. */
export function SyntheticBadge({ short = false }: { short?: boolean }) {
  const m = apiMode();
  if (m.mode !== 'mock') return null;
  return (
    <span className={s.synthetic} title={`Synthetic demo cases (${m.reason}): drawn shapes, not radiographs.`} data-testid="synthetic-badge">
      {short ? 'Synthetic' : 'Synthetic demo cases'}
    </span>
  );
}

/** `compact` is the reading-room header: the learner's own pages only (Read is where they are; Cohort and Review
 *  are instructor pages, one click away from the landing). */
export function Nav({ compact = false }: { compact?: boolean }) {
  return (
    <nav className={s.nav} aria-label="Main">
      {!compact && <Link to="/read">Read</Link>}
      <Link to="/progress">Reading log</Link>
      {!compact && <Link to="/cohort">Cohort</Link>}
      {!compact && <Link to="/review">Review</Link>}
      <Link to="/about">About</Link>
    </nav>
  );
}

/** Paper page: header, optional full-bleed hero, single report column, disclaimer footer. */
export function PageShell({ children, wide = false, width, hero }: { children: ReactNode; wide?: boolean; width?: number; hero?: ReactNode }) {
  const w = width ?? (wide ? 1100 : undefined);
  return (
    <div className={s.page}>
      <header className={s.pageHeader}>
        <Link to="/" className={s.brand}><BrandMark size={22} className={s.brandMark} />Blindspot</Link>
        <SyntheticBadge />
        <span className={s.spacer} />
        <Nav />
      </header>
      {hero}
      <main className={s.pageMain} style={w ? { maxWidth: w } : undefined}>{children}</main>
      <div className={s.pageFooterWrap} style={w ? { maxWidth: w } : undefined}><Footer className={s.pageFooter} /></div>
    </div>
  );
}
