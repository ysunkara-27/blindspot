// Case-level stats as ruled rows (not tiles), each with the n it rests on. Plain labels; the technical term is a tooltip.
import { pct } from '../helpers';
import type { CaseStats } from '../types';
import { Empty, Section, StatRows } from '../parts';

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`;

/** `voice` picks the wording: the learner's own log ("you") or a group of learners. */
export function SummaryStats({ st, title = 'Where you stand', voice = 'you' }: { st: CaseStats | null; title?: string; voice?: 'you' | 'cohort' }) {
  const you = voice === 'you';
  return (
    <Section title={title} testid="summary-stats" n={st ? `n = ${plural(st.n, 'film')}` : undefined}>
      {!st || st.n === 0 ? <Empty>No films read yet.</Empty> : (
        <StatRows rows={[
          {
            label: you ? 'Abnormal films you caught' : 'Abnormal films caught', term: 'Sensitivity (per film)',
            explain: 'A film with a finding counts as caught when at least one finding on it was located or called.',
            value: pct(st.sensitivity), basis: `of ${plural(st.n_abnormal, 'abnormal film')}`, testid: 'stat-sensitivity',
          },
          {
            label: you ? 'Normal films you correctly called normal' : 'Normal films correctly called normal', term: 'Specificity (per film)',
            explain: 'A normal film counts when it was left with no mark and no call.',
            value: pct(st.specificity), basis: `of ${plural(st.n_normal, 'normal film')}`, testid: 'stat-specificity',
          },
          {
            label: you ? 'Findings you pinpointed' : 'Findings pinpointed', term: 'Lesion localization fraction',
            explain: 'Findings with an outline where a mark landed on the outline or just beside it.',
            value: pct(st.localization_fraction), basis: `of ${plural(st.n_focal_findings, 'outlined finding')}`, testid: 'stat-localization',
          },
          {
            label: 'False alarms per film', term: 'False positives per image',
            explain: 'Marks with no finding behind them, averaged over every film read.',
            value: st.false_positives_per_image.toFixed(2), basis: `over ${plural(st.n, 'film')}`, testid: 'stat-fp',
          },
          {
            label: 'Average score', explain: 'Each film is scored out of 100 for what was found, named and left alone.',
            value: `${Math.round(st.score_mean)}`, basis: `out of 100, over ${plural(st.n, 'film')}`, testid: 'stat-score',
          },
        ]} />
      )}
    </Section>
  );
}
