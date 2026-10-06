// Calibration (SPEC §10.1): accuracy by stated confidence 1–5, plus confident misses. One series, the learner's amber.
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { calibrationRows, calibrationSplit, pct, type CalibrationRow } from '../helpers';
import { AXIS_TICK, C } from '../palette';
import type { Calibration as Cal } from '../types';
import { Empty, Section, TableView, Tip, type TipProps } from '../parts';
import s from '../Dashboard.module.css';

function CalTip({ active, payload }: TipProps) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload as CalibrationRow;
  return (
    <Tip>
      <div className={s.tipValue}>{r.pct == null ? 'No calls' : `${Math.round(r.pct)}% right`}</div>
      <div>Confidence {r.confidence} · {r.word}</div>
      <div className={s.tipMuted}>{r.correct} of {r.n} calls</div>
    </Tip>
  );
}

function Tick({ x, y, payload, rows }: { x?: number | string; y?: number | string; payload?: { value: number }; rows: CalibrationRow[] }) {
  const r = rows.find((q) => q.confidence === payload?.value);
  return (
    <g transform={`translate(${x},${y})`}>
      <text dy={14} textAnchor="middle" fill={C.ink} fontSize={14}>{payload?.value} · {r?.word}</text>
      <text dy={31} textAnchor="middle" fill={C.muted} fontSize={13}>n = {r?.n ?? 0}</text>
    </g>
  );
}

export function Calibration({ cal }: { cal: Cal | null }) {
  const rows = calibrationRows(cal);
  const split = calibrationSplit(cal);
  const n = cal?.n ?? 0;
  const data = rows.map((r) => ({ ...r, bar: r.pct ?? 0 }));
  return (
    <Section title="How well your confidence matched reality" testid="calibration" n={`n = ${n} calls · ${cal?.confident_misses ?? 0} confident misses`}
      caption="How often a mark or a normal call was right at each confidence you gave it. If the bars climb from left to right, your confidence means something (this is called calibration).">
      {n === 0 ? <Empty>No confidence-rated calls yet.</Empty> : (
        <>
          <p className={s.caption} data-testid="calibration-split">
            When sure (4–5): <strong>{pct(split.sure.acc)}</strong> right, n = {split.sure.n}.{' '}
            When unsure (1–2): <strong>{pct(split.unsure.acc)}</strong> right, n = {split.unsure.n}.{' '}
            Confident misses (wrong at 4–5): <strong data-testid="confident-misses">{cal?.confident_misses ?? 0}</strong>.
          </p>
          <div className={s.chart} role="img" aria-label="Accuracy by confidence level">
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={data} margin={{ top: 20, right: 8, bottom: 12, left: 0 }} barCategoryGap="35%">
                <CartesianGrid vertical={false} stroke={C.grid} />
                <XAxis dataKey="confidence" tickLine={false} axisLine={{ stroke: C.axis }} height={42} interval={0} tick={(p) => <Tick {...p} rows={rows} />} />
                <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={(v: number) => `${v}%`} tick={AXIS_TICK} tickLine={false} axisLine={false} width={48} />
                <Tooltip content={(p) => <CalTip {...p} />} cursor={{ fill: 'rgba(29,35,41,0.05)' }} isAnimationActive={false} />
                <Bar dataKey="bar" fill={C.learner} maxBarSize={28} radius={[4, 4, 0, 0]} isAnimationActive={false}>
                  <LabelList dataKey="pct" position="top" fill={C.ink} fontSize={13}
                    formatter={(v: unknown) => (typeof v === 'number' ? `${Math.round(v)}%` : '')} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <TableView caption="Accuracy by confidence" head={['Confidence', 'Calls', 'Right', 'Accuracy']}
            rows={rows.map((r) => [`${r.confidence} · ${r.word}`, r.n, r.correct, r.pct == null ? '—' : `${Math.round(r.pct)}%`])} />
        </>
      )}
    </Section>
  );
}
