// How the misses happened, as one labelled bar per miss type. Every bar wears the learner's amber: the types are told
// apart by their row and label, never by shade (see palette.ts). Counts are written at the end of each bar.
import { MISS_NAME } from '../palette';
import { MISS_BUCKETS, type MissMix } from '../types';
import s from '../Dashboard.module.css';

export function MissBreakdown({ mix, testid = 'miss-breakdown' }: { mix: MissMix; testid?: string }) {
  const max = Math.max(1, ...MISS_BUCKETS.map((b) => mix[b]));
  return (
    <ul className={s.missBars} data-testid={testid}>
      {MISS_BUCKETS.map((b) => (
        <li key={b} data-testid={`miss-${b}`}>
          <span className={s.missLabel}>
            <abbr className={s.term} title={`Kundel's term: ${MISS_NAME[b].term} error`} tabIndex={0}>{MISS_NAME[b].plain}</abbr>
            <span className={s.missExplain}>{MISS_NAME[b].explain}</span>
          </span>
          <span className={s.missTrack} aria-hidden="true">
            {mix[b] > 0 && <span className={s.missFill} style={{ width: `${(100 * mix[b]) / max}%` }} />}
          </span>
          <span className={s.missCount}>{mix[b]}</span>
        </li>
      ))}
    </ul>
  );
}
