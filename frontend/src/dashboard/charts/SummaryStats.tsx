// Case-level stats as ruled rows (not tiles), each with the n it rests on.
import { pct } from '../helpers';
import type { CaseStats } from '../types';
import { Empty, Section, StatRows } from '../parts';

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`;

export function SummaryStats({ st, title = 'Where you stand' }: { st: CaseStats | null; title?: string }) {
  return (
    <Section title={title} testid="summary-stats" n={st ? `n = ${plural(st.n, 'case')}` : undefined}>
      {!st || st.n === 0 ? <Empty>No cases read yet.</Empty> : (
        <StatRows rows={[
          { label: 'Abnormal films you marked correctly (sensitivity)', value: pct(st.sensitivity), basis: `of ${plural(st.n_abnormal, 'abnormal film')}`, testid: 'stat-sensitivity' },
          { label: 'Normal films left clean (specificity)', value: pct(st.specificity), basis: `of ${plural(st.n_normal, 'normal film')}`, testid: 'stat-specificity' },
          { label: 'Findings localized', value: pct(st.localization_fraction), basis: `of ${plural(st.n_focal_findings, 'focal finding')}`, testid: 'stat-localization' },
          { label: 'False marks per film', value: st.false_positives_per_image.toFixed(2), basis: `over ${plural(st.n, 'film')}`, testid: 'stat-fp' },
          { label: 'Mean case score', value: `${Math.round(st.score_mean)}`, basis: `out of 100, over ${plural(st.n, 'case')}`, testid: 'stat-score' },
        ]} />
      )}
    </Section>
  );
}
