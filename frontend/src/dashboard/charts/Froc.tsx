// FROC (SPEC §6.4, §10.1): lesion localization fraction vs false marks per film, sweeping the confidence threshold.
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { frocRows, type FrocRow } from '../helpers';
import { AXIS_TICK, C } from '../palette';
import type { Froc as F } from '../types';
import { Empty, Section, TableView, Tip, type TipProps } from '../parts';
import s from '../Dashboard.module.css';

const thr = (t: number) => (t > 5 ? 'no marks' : t === 1 ? 'all marks' : `confidence ≥ ${t}`);

function FrocTip({ active, payload }: TipProps) {
  if (!active || !payload?.length) return null;
  const r = payload[0].payload as FrocRow;
  return (
    <Tip>
      <div className={s.tipValue}>{Math.round(r.llf * 100)}% of findings</div>
      <div>{r.nlf.toFixed(2)} false marks per film</div>
      <div className={s.tipMuted}>Counting {thr(r.threshold)} · {r.n_ll} hits, {r.n_nl} false marks</div>
    </Tip>
  );
}

export function Froc({ froc }: { froc: F | null }) {
  const rows = frocRows(froc);
  const maxX = Math.max(0.5, ...rows.map((r) => r.nlf));
  return (
    <Section title="Hits against false marks (FROC)" testid="froc"
      n={`n = ${froc?.n_images ?? 0} films · ${froc?.n_lesions ?? 0} findings · ${froc?.n_marks ?? 0} marks`}
      caption="Each point counts only the marks at or above a confidence level, from certain (left) to all marks (right). Higher and further left is better.">
      {!froc || froc.n_marks === 0 || rows.length < 2 ? <Empty>No marks placed yet.</Empty> : (
        <>
          <div className={s.chart} role="img" aria-label="FROC curve">
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={rows} margin={{ top: 12, right: 72, bottom: 22, left: 0 }}>
                <CartesianGrid stroke={C.grid} />
                <XAxis dataKey="nlf" type="number" domain={[0, Math.ceil(maxX * 4) / 4]} tick={AXIS_TICK} tickLine={false} axisLine={{ stroke: C.axis }}
                  tickFormatter={(v: number) => v.toFixed(2)}
                  label={{ value: 'False marks per film', position: 'insideBottom', offset: -14, fill: C.muted, fontSize: 13 }} />
                <YAxis dataKey="llf" domain={[0, 1]} ticks={[0, 0.25, 0.5, 0.75, 1]} tickFormatter={(v: number) => `${Math.round(v * 100)}%`} tick={AXIS_TICK} tickLine={false} axisLine={false} width={48} />
                <Tooltip content={(p) => <FrocTip {...p} />} cursor={{ stroke: C.axis, strokeWidth: 1 }} isAnimationActive={false} />
                <Line type="linear" dataKey="llf" stroke={C.learner} strokeWidth={2} isAnimationActive={false}
                  dot={{ r: 4, fill: C.learner, stroke: C.paper, strokeWidth: 2 }} activeDot={{ r: 6, fill: C.learner, stroke: C.paper, strokeWidth: 2 }}
                  label={(p: { x?: number | string; y?: number | string; index?: number }) =>
                    p.index === rows.length - 1 ? (
                      <text x={Number(p.x) + 8} y={Number(p.y) + 4} fill={C.ink} fontSize={13}>all marks</text>
                    ) : <g />} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <TableView caption="FROC operating points" head={['Counting', 'Findings localized', 'False marks per film', 'Hits', 'False marks']}
            rows={rows.filter((r) => r.threshold <= 5).map((r) => [thr(r.threshold), `${Math.round(r.llf * 100)}%`, r.nlf.toFixed(2), r.n_ll, r.n_nl])} />
        </>
      )}
    </Section>
  );
}
