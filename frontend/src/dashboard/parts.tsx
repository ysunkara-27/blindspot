// Shared dashboard pieces: ruled section, table twin, stat rows, legend, tooltip shell.
import type { ReactNode } from 'react';
import s from './Dashboard.module.css';

export function Section({ title, n, caption, children, testid }: {
  title: string; n?: ReactNode; caption?: ReactNode; children: ReactNode; testid?: string;
}) {
  return (
    <section className={s.section} data-testid={testid} aria-label={title}>
      <div className={s.sectionHead}>
        <h2 className={s.sectionTitle}>{title}</h2>
        {n != null && <span className={s.n} data-testid={testid ? `${testid}-n` : undefined}>{n}</span>}
      </div>
      {caption && <p className={s.caption}>{caption}</p>}
      {children}
    </section>
  );
}

export function TableView({ caption, head, rows }: { caption: string; head: string[]; rows: ReactNode[][] }) {
  return (
    <details className={s.tableView}>
      <summary>Show as table</summary>
      <table className={s.dataTable}>
        <caption className="sr-only">{caption}</caption>
        <thead><tr>{head.map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => (j === 0 ? <th key={j} scope="row">{c}</th> : <td key={j}>{c}</td>))}</tr>)}</tbody>
      </table>
    </details>
  );
}

export type StatRow = { label: string; value: string; basis: string; explain?: string; term?: string; testid?: string };

/** Ruled rows: a plain label, one line saying what it means, the basis (n), and the figure. `term` is the technical
 *  name, kept in a tooltip (dotted underline) rather than in the label. */
export function StatRows({ rows }: { rows: StatRow[] }) {
  return (
    <table className={s.statRows}>
      <tbody>
        {rows.map((r) => (
          <tr key={r.label} data-testid={r.testid}>
            <th scope="row">
              {r.term ? <abbr className={s.term} title={r.term} tabIndex={0}>{r.label}</abbr> : r.label}
              {r.explain && <span className={s.statExplain}>{r.explain}</span>}
              <span className={s.statBasis}>{r.basis}</span>
            </th>
            <td><span className={s.statValue}>{r.value}</span></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

type LegendShape = 'rect' | 'dot' | 'ring' | 'line' | 'wash';

export function Legend({ items }: { items: { key: string; color: string; text: ReactNode; shape?: LegendShape }[] }) {
  return (
    <ul className={s.legend}>
      {items.map((it) => (
        <li key={it.key}>
          {it.shape === 'dot' ? <span className={s.dotSwatch} style={{ background: it.color }} />
            : it.shape === 'ring' ? <span className={s.ringSwatch} style={{ borderColor: it.color }} />
            : it.shape === 'line' ? <span style={{ width: 16, height: 2, background: it.color }} />
            : it.shape === 'wash' ? <span className={s.washSwatch} style={{ background: it.color }} />
            : <span className={s.swatch} style={{ background: it.color }} />}
          <span>{it.text}</span>
        </li>
      ))}
    </ul>
  );
}

export function Tip({ children }: { children: ReactNode }) {
  return <div className={s.tip}>{children}</div>;
}

export function Empty({ children, testid }: { children: ReactNode; testid?: string }) {
  return <p className={s.empty} data-testid={testid}>{children}</p>;
}

/** Minimal tooltip props (Recharts passes more; we read only these). */
export type TipProps = { active?: boolean; payload?: ReadonlyArray<{ payload?: unknown }> };
