// Cohort per-label difficulty (SPEC §10.2): empirical localization success vs mean case difficulty b.
import { pct } from '../helpers';
import type { LabelDifficulty as LD } from '../types';
import { C } from '../palette';
import { Empty, Section } from '../parts';
import s from '../Dashboard.module.css';

export function LabelDifficulty({ rows }: { rows: LD[] }) {
  const sorted = [...rows].sort((a, b) => a.empirical_success - b.empirical_success || b.n - a.n);
  const n = rows.reduce((a, r) => a + r.n, 0);
  return (
    <Section title="Which findings the cohort finds" testid="label-difficulty" n={`n = ${n} findings · ${rows.length} labels`}
      caption="Localized or correctly called, per finding shown. Mean b is the adaptive engine's case difficulty (Elo scale; higher is harder). Hardest first.">
      {!rows.length ? <Empty>No findings read yet.</Empty> : (
        <table className={`${s.dataTable} ${s.difficulty}`} style={{ width: '100%' }}>
          <thead><tr><th scope="col">Finding</th><th scope="col">Shown</th><th scope="col">Found</th><th scope="col">Mean b</th></tr></thead>
          <tbody>
            {sorted.map((r) => (
              <tr key={r.label} data-testid={`difficulty-${r.label}`}>
                <th scope="row" style={{ fontWeight: 400 }}>{r.display}</th>
                <td>{r.n}</td>
                <td><span className={s.inlineBar} style={{ width: `${Math.round(r.empirical_success * 80)}px`, background: C.truth }} />{pct(r.empirical_success)}</td>
                <td>{r.mean_b.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Section>
  );
}
