import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { apiMode } from '../api/client';
import s from './Shell.module.css';

export const DISCLAIMER = 'For education. Not for clinical use.';

export function Footer({ className }: { className?: string }) {
  return (
    <footer className={className ?? s.footer} data-testid="disclaimer">
      {DISCLAIMER} Images are de-identified research radiographs with expert annotations.
    </footer>
  );
}

export function SyntheticBadge() {
  const m = apiMode();
  if (m.mode !== 'mock') return null;
  return (
    <span className={s.synthetic} title={`Mock API: ${m.reason}. Cases are drawn shapes, not radiographs.`} data-testid="synthetic-badge">
      Synthetic demo cases
    </span>
  );
}

export function Nav() {
  return (
    <nav className={s.nav} aria-label="Main">
      <Link to="/read">Read</Link>
      <Link to="/progress">Reading log</Link>
      <Link to="/cohort">Cohort</Link>
      <Link to="/review">Review</Link>
      <Link to="/about">About</Link>
    </nav>
  );
}

/** Paper page: header, single report column, disclaimer footer. */
export function PageShell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className={s.page}>
      <header className={s.pageHeader}>
        <Link to="/" className={s.brand}>Blindspot</Link>
        <SyntheticBadge />
        <span className={s.spacer} />
        <Nav />
      </header>
      <main className={s.pageMain} style={wide ? { maxWidth: 1100 } : undefined}>{children}</main>
      <Footer className={s.pageFooter} />
    </div>
  );
}
