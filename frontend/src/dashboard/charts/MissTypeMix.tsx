// Miss types (SPEC §10.1). Two views of the same counts:
//  1. totals: one labelled bar per miss type (MissBreakdown);
//  2. over time: small multiples, one row per miss type across blocks of 10 films, so "search misses shrink first" can
//     be read along a row. Bar height is misses per film, so a short last block compares fairly; the number is the count.
// Identity is the row and its label, never a shade: every bar is the learner's amber (palette.ts).
import { useState } from 'react';
import { missRows } from '../helpers';
import { MISS_NAME } from '../palette';
import { MISS_BUCKETS, type MissBucket, type MissMix, type MissTypeMix as MTM } from '../types';
import { Empty, Section, TableView } from '../parts';
import { MissBreakdown } from './MissBreakdown';
import s from '../Dashboard.module.css';

const BAR_MAX = 30; // px

export function MissTypeMix({ mix, title = 'How your misses happen' }: { mix: MTM | null; title?: string }) {
  const rows = missRows(mix);
  const totals = Object.fromEntries(MISS_BUCKETS.map((b) => [b, rows.reduce((a, r) => a + r[b], 0)])) as MissMix;
  const nMiss = MISS_BUCKETS.reduce((a, b) => a + totals[b], 0);
  const n = mix?.n ?? 0;
  const window = mix?.window ?? 10;
  const rate = (count: number, films: number) => (films > 0 ? count / films : 0);
  const maxRate = Math.max(0, ...rows.flatMap((r) => MISS_BUCKETS.map((b) => rate(r[b], r.n))));
  const [at, setAt] = useState<{ row: number; b: MissBucket } | null>(null);
  const cur = at ? rows[at.row] : null;

  return (
    <Section title={title} testid="miss-mix" n={`n = ${n} films · ${nMiss} misses`}
      caption="Each row is one way a finding gets missed or a false alarm gets made. Miss types come from your cursor, magnifier and zoom — a stand-in for where you looked.">
      {!rows.length ? <Empty>No films read yet.</Empty> : nMiss === 0 ? <Empty>No misses or false alarms so far.</Empty> : (
        <>
          <MissBreakdown mix={totals} />
          {rows.length < 2 ? (
            <p className={s.caption} data-testid="miss-trend-later">A trend by block of {window} films appears once you have read more than {window}.</p>
          ) : (
            <>
              <h3 className={s.subTitle}>Over time</h3>
              <p className={s.caption}>
                Misses in each block of {window} films. Bar height is misses per film, so a short last block compares fairly; the number is the count.
                Never-looked misses usually shrink first.
              </p>
              <div className={s.trendWrap}>
                <table className={s.trend} data-testid="miss-trend" onMouseLeave={() => setAt(null)}>
                  <thead>
                    <tr>
                      <td />
                      {rows.map((r) => <th key={r.name} scope="col">Films {r.name}{r.n < window ? <span className={s.trendN}> (n = {r.n})</span> : null}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {MISS_BUCKETS.map((b) => (
                      <tr key={b}>
                        <th scope="row">{MISS_NAME[b].plain}</th>
                        {rows.map((r, i) => {
                          const v = r[b];
                          const h = maxRate > 0 ? Math.max(v > 0 ? 3 : 0, Math.round((rate(v, r.n) / maxRate) * BAR_MAX)) : 0;
                          const on = at?.row === i && at.b === b;
                          return (
                            <td key={r.name} className={on ? s.trendOn : undefined} tabIndex={0}
                              onMouseEnter={() => setAt({ row: i, b })} onFocus={() => setAt({ row: i, b })} onBlur={() => setAt(null)}
                              aria-label={`${MISS_NAME[b].plain}, films ${r.name}: ${v} in ${r.n} films`}>
                              <span className={s.trendCell}>
                                <span className={v ? s.trendCount : s.trendZero}>{v}</span>
                                <span className={s.trendBar} style={{ height: h }} />
                              </span>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className={s.readout} data-testid="miss-readout" aria-hidden="true">
                {cur && at
                  ? <><strong>Films {cur.name}</strong> · {MISS_NAME[at.b].plain.toLowerCase()}: <strong>{cur[at.b]}</strong> in {cur.n} films ({rate(cur[at.b], cur.n).toFixed(2)} per film)</>
                  : 'Point at a bar to read it.'}
              </p>
            </>
          )}
          <TableView caption="Miss types by block of films" head={['Films', 'n', ...MISS_BUCKETS.map((b) => MISS_NAME[b].plain)]}
            rows={rows.map((r) => [r.name, r.n, ...MISS_BUCKETS.map((b) => r[b])])} />
        </>
      )}
    </Section>
  );
}
