// Learning curve (SPEC §10.1): rolling accuracy (window 10) vs attempt number, overall or per label.
import { useState } from 'react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { labelDisplay } from '../../api/labels';
import { curveLabels, curveRows, type CurveRow } from '../helpers';
import { AXIS_TICK, C } from '../palette';
import type { LearningCurve as LC } from '../types';
import { Empty, Section, TableView, Tip, type TipProps } from '../parts';
import s from '../Dashboard.module.css';

export const EMPTY_CURVE = 'Read 5 cases to see your first learning curve.';
const MIN_CASES = 5;

const seriesName = (key: string) => (key === 'overall' ? 'All cases' : key === 'normal' ? 'Normal films' : labelDisplay(key));

function CurveTip({ active, payload, perLabel }: TipProps & { perLabel: boolean }) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload as CurveRow;
  return (
    <Tip>
      <div className={s.tipValue}>{Math.round(r.pct)}%</div>
      <div>{perLabel ? `Film ${r.attempt} with this finding` : `Case ${r.attempt}`}</div>
      <div className={s.tipMuted}>Mean of the last {r.window_n}</div>
    </Tip>
  );
}

export function LearningCurve({ lc, nCases }: { lc: LC | null; nCases: number }) {
  const [key, setKey] = useState('overall');
  const labels = curveLabels(lc);
  const rows = curveRows(lc, key);
  const perLabel = key !== 'overall';
  const last = rows[rows.length - 1];
  const window = lc?.window ?? 10;

  return (
    <Section
      title="Learning curve"
      testid="learning-curve"
      n={`n = ${nCases} case${nCases === 1 ? '' : 's'}`}
      caption={perLabel
        ? `Share of ${seriesName(key).toLowerCase()} you localized or called correctly, averaged over the last ${window} films that had it.`
        : `Share of cases read correctly, averaged over your last ${window} cases.`}
    >
      {nCases < MIN_CASES || !lc ? <Empty testid="curve-empty">{EMPTY_CURVE}</Empty> : (
        <>
          <div className={s.controls}>
            <label className={s.control}>
              Show
              <select className={s.select} value={key} onChange={(e) => setKey(e.target.value)} data-testid="curve-series">
                <option value="overall">All cases ({lc.overall.length})</option>
                {labels.map((l) => <option key={l.id} value={l.id}>{seriesName(l.id)} ({l.n})</option>)}
              </select>
            </label>
          </div>
          <div className={s.chart} role="img" aria-label={`Learning curve, ${seriesName(key)}: latest ${last ? Math.round(last.pct) : 0}% over ${rows.length} points`}>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={rows} margin={{ top: 12, right: 48, bottom: 22, left: 0 }}>
                <CartesianGrid vertical={false} stroke={C.grid} />
                <XAxis dataKey="attempt" type="number" domain={[1, Math.max(2, rows.length)]} allowDecimals={false}
                  tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: C.axis }}
                  label={{ value: perLabel ? 'Films with this finding' : 'Case number', position: 'insideBottom', offset: -14, fill: C.muted, fontSize: 13 }} />
                <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={(v: number) => `${v}%`} tick={AXIS_TICK} tickLine={false} axisLine={false} width={48} />
                <Tooltip content={(p) => <CurveTip {...p} perLabel={perLabel} />} cursor={{ stroke: C.axis, strokeWidth: 1 }} isAnimationActive={false} />
                <Line type="linear" dataKey="pct" stroke={C.learner} strokeWidth={2} isAnimationActive={false}
                  dot={false} activeDot={{ r: 5, fill: C.learner, stroke: C.paper, strokeWidth: 2 }}
                  label={(p: { x?: number | string; y?: number | string; index?: number }) =>
                    p.index === rows.length - 1 && last ? (
                      <text x={Number(p.x) + 8} y={Number(p.y) + 4} fill={C.ink} fontSize={14} fontWeight={700}>{Math.round(last.pct)}%</text>
                    ) : <g />} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <TableView caption="Learning curve values" head={[perLabel ? 'Film' : 'Case', 'Rolling accuracy', 'Window n']}
            rows={rows.map((r) => [r.attempt, `${Math.round(r.pct)}%`, r.window_n])} />
        </>
      )}
    </Section>
  );
}
