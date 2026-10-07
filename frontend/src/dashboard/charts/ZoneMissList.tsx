// CT / MR reading log (round 4): the blind-spot map is a chest schematic, so volumes get a plain list instead —
// where the misses happened, by zone (an organ or slab region), with n on every row.
import type { ZoneMisses } from '../types';
import { Empty, Section, TableView } from '../parts';
import s from '../Dashboard.module.css';

const cap = (t: string) => t.charAt(0).toUpperCase() + t.slice(1);

export function ZoneMissList({ zones, scan }: { zones: ZoneMisses[]; scan: string }) {
  const n = zones.reduce((a, z) => a + z.n, 0);
  const missed = zones.reduce((a, z) => a + z.n_missed, 0);
  return (
    <Section title="Where misses happened" testid="zone-misses" n={`n = ${n} findings · ${missed} missed`}
      caption={`Every segmented finding on the ${scan} studies you read, by the zone it sits in. The bar is the share of that zone's findings you missed.`}>
      {!zones.length ? <Empty>No segmented findings read yet.</Empty> : (
        <>
          <ul className={s.habit}>
            {zones.map((z) => (
              <li key={z.zone} data-testid={`zone-${z.zone}`}>
                <span className={s.habitName}>{cap(z.human)}</span>
                <span className={s.track} aria-hidden="true"><span className={s.fill} style={{ display: 'block', width: `${z.n ? (100 * z.n_missed) / z.n : 0}%` }} /></span>
                <span className={s.habitPct}>{z.n_missed} of {z.n} missed</span>
              </li>
            ))}
          </ul>
          <TableView caption="Misses by zone" head={['Zone', 'Findings', 'Missed']} rows={zones.map((z) => [cap(z.human), z.n, z.n_missed])} />
        </>
      )}
    </Section>
  );
}
