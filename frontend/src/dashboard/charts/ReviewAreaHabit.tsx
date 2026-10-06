// Review-area habit (SPEC §10.1): % of cases in which each review area was visited (cursor, loupe or zoom proxy).
import type { ReviewAreaHabit as RAH } from '../types';
import { Empty, Section, TableView } from '../parts';
import s from '../Dashboard.module.css';

const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

export function ReviewAreaHabit({ habit }: { habit: RAH | null }) {
  const n = habit?.n ?? 0;
  const areas = habit?.areas ?? [];
  return (
    <Section title="Review areas you check" testid="review-areas" n={`n = ${n} cases`}
      caption="Share of cases in which your cursor, loupe or zoom reached each classic hiding place.">
      {n === 0 || !areas.length ? <Empty>No cases read yet.</Empty> : (
        <>
          <ul className={s.habit}>
            {areas.map((a) => (
              <li key={a.area} data-testid={`area-${a.area}`}>
                <span className={s.habitName}>{cap(a.human)}</span>
                <span className={s.track} aria-hidden="true"><span className={s.fill} style={{ display: 'block', width: `${a.visited_pct ?? 0}%` }} /></span>
                <span className={s.habitPct}>{a.visited_pct == null ? '—' : `${Math.round(a.visited_pct)}%`}</span>
              </li>
            ))}
          </ul>
          <TableView caption="Review areas visited" head={['Area', 'Cases visited']} rows={areas.map((a) => [cap(a.human), a.visited_pct == null ? '—' : `${a.visited_pct}%`])} />
        </>
      )}
    </Section>
  );
}
