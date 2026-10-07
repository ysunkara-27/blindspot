import type { ReactNode } from 'react';
import { Link, NavLink } from 'react-router-dom';
import { apiMode } from '../api/client';
import { useSession } from '../state/session';
import { BrandMark } from '../brand/mark';
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
    <span className={s.synthetic} title={`Synthetic cases (${m.reason}): drawn shapes, not radiographs.`} data-testid="synthetic-badge">
      {short ? 'Synthetic' : 'Synthetic cases'}
    </span>
  );
}

/** The learner's pages: Read · Reading log · Reference · About. `compact` is the reading-room header, where Read is
 *  where you already are. Cohort and expert review are not learner pages: they are reached by URL or from About. */
export function Nav({ compact = false }: { compact?: boolean }) {
  // "Read" goes back to the open set if there is one, otherwise to the start screen.
  const inSet = useSession((st) => !!st.session);
  return (
    <nav className={s.nav} aria-label="Main">
      {!compact && <NavLink to={inSet ? '/read' : '/start'} data-testid="nav-read">Read</NavLink>}
      <NavLink to="/progress">Reading log</NavLink>
      <NavLink to="/reference">Reference</NavLink>
      <NavLink to="/about">About</NavLink>
    </nav>
  );
}

/** Paper page: header, optional full-bleed hero, single report column, disclaimer footer. */
export function PageShell({ children, wide = false, width, hero }: { children: ReactNode; wide?: boolean; width?: number; hero?: ReactNode }) {
  const w = width ?? (wide ? 1100 : undefined);
  return (
    <div className={s.page}>
      <header className={s.pageHeader}>
        <Link to="/" className={s.brand}><BrandMark size={20} tone="light" className={s.brandMark} />Blindspot</Link>
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
