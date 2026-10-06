// Miss-type mix (SPEC §10.1): stacked bars over windows of 10 cases. Plotted per case so a short last window compares fairly.
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { missRows, niceTicks, type MissRow } from '../helpers';
import { AXIS_TICK, C, MISS_COLOR, MISS_NAME } from '../palette';
import { MISS_BUCKETS, type MissTypeMix as MTM } from '../types';
import { Empty, Legend, Section, TableView, Tip, type TipProps } from '../parts';
import s from '../Dashboard.module.css';

type Row = MissRow & Record<`${(typeof MISS_BUCKETS)[number]}_rate`, number>;

function MixTip({ active, payload }: TipProps) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload as Row;
  return (
    <Tip>
      <div><strong>Cases {r.name}</strong> <span className={s.tipMuted}>· n = {r.n}</span></div>
      {[...MISS_BUCKETS].reverse().map((b) => (
        <div key={b} className={s.tipRow}>
          <span className={s.tipKey} style={{ background: MISS_COLOR[b], height: 8, width: 8, borderRadius: 2 }} />
          <strong>{r[b]}</strong> <span>{MISS_NAME[b].plain}</span>
        </div>
      ))}
    </Tip>
  );
}

export function MissTypeMix({ mix, title = 'How your misses happen' }: { mix: MTM | null; title?: string }) {
  const rows: Row[] = missRows(mix).map((r) => ({
    ...r,
    ...Object.fromEntries(MISS_BUCKETS.map((b) => [`${b}_rate`, r.n ? Math.round((r[b] / r.n) * 100) / 100 : 0])),
  })) as Row[];
  const totals = Object.fromEntries(MISS_BUCKETS.map((b) => [b, rows.reduce((s2, r) => s2 + r[b], 0)])) as Record<(typeof MISS_BUCKETS)[number], number>;
  const nMiss = MISS_BUCKETS.reduce((a, b) => a + totals[b], 0);
  const n = mix?.n ?? 0;
  const maxRate = Math.max(0, ...rows.map((r) => MISS_BUCKETS.reduce((a, b) => a + r[`${b}_rate`], 0)));
  const ticks = niceTicks(maxRate);
  const top = [...MISS_BUCKETS].reverse().find((b) => rows.some((r) => r[b] > 0));

  return (
    <Section title={title} testid="miss-mix" n={`n = ${n} cases · ${nMiss} misses`}
      caption={`Misses per case (bar height) in each block of ${mix?.window ?? 10} cases. Based on your cursor, loupe and zoom — a proxy for where you looked. Search misses should shrink first.`}>
      {!rows.length ? <Empty>No cases read yet.</Empty> : nMiss === 0 ? <Empty>No misses or overcalls so far.</Empty> : (
        <>
          <Legend items={MISS_BUCKETS.map((b) => ({ key: b, color: MISS_COLOR[b], text: <>{MISS_NAME[b].plain} <span className={s.legendTerm}>({MISS_NAME[b].term}, {totals[b]})</span></> }))} />
          <div className={s.chart} role="img" aria-label={`Misses per case across ${rows.length} blocks of cases`}>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 22, left: 0 }} barCategoryGap="30%">
                <CartesianGrid vertical={false} stroke={C.grid} />
                <XAxis dataKey="name" tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: C.axis }}
                  label={{ value: 'Cases', position: 'insideBottom', offset: -14, fill: C.muted, fontSize: 13 }} />
                <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={48} domain={[0, ticks[ticks.length - 1]]} ticks={ticks} />
                <Tooltip content={(p) => <MixTip {...p} />} cursor={{ fill: 'rgba(29,35,41,0.05)' }} isAnimationActive={false} />
                {MISS_BUCKETS.map((b) => (
                  <Bar key={b} dataKey={`${b}_rate`} stackId="m" fill={MISS_COLOR[b]} stroke={C.paper} strokeWidth={1}
                    maxBarSize={28} isAnimationActive={false} radius={b === top ? [4, 4, 0, 0] : 0} name={MISS_NAME[b].plain} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
          <TableView caption="Miss types by block of cases" head={['Cases', 'n', ...MISS_BUCKETS.map((b) => MISS_NAME[b].term)]}
            rows={rows.map((r) => [r.name, r.n, ...MISS_BUCKETS.map((b) => r[b])])} />
        </>
      )}
    </Section>
  );
}
