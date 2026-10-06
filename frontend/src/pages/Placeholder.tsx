import { PageShell } from '../app/Shell';
import s from './Pages.module.css';

export function Placeholder({ title, empty, note }: { title: string; empty: string; note?: string }) {
  return (
    <PageShell>
      <h1 className={s.h1}>{title}</h1>
      <p className={s.lede}>{empty}</p>
      {note && <p className={s.mutedSmall}>{note}</p>}
    </PageShell>
  );
}
