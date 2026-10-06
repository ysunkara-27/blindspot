// Catch-all route: a short "Page not found" inside the paper shell, so the disclaimer footer is on every page.
import { Link, useLocation } from 'react-router-dom';
import { PageShell } from '../app/Shell';
import s from './Pages.module.css';

export function NotFoundPage() {
  const { pathname } = useLocation();
  return (
    <PageShell>
      <h1 className={s.h1} data-testid="not-found">Page not found</h1>
      <p className={s.lede}>There is no page at <code>{pathname}</code>.</p>
      <p><Link to="/" className={s.primaryLink}>Go to the start</Link></p>
    </PageShell>
  );
}
