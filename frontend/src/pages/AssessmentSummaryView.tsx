// End-of-assessment summary (SPEC §1.4, §9.3): the only feedback an assessment gives, shown after the last case.
// Every figure carries its n. Then the pilot's SUS survey.
import { useQuery } from '@tanstack/react-query';
import { useTitle } from '../app/useTitle';
import { Link } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import { modeDisplay, OUTCOME_COPY } from '../api/labels';
import { PageShell } from '../app/Shell';
import { SummaryStats } from '../dashboard/charts/SummaryStats';
import { MISS_COLOR, MISS_NAME } from '../dashboard/palette';
import { Section, TableView } from '../dashboard/parts';
import { guardStats, MISS_BUCKETS } from '../dashboard/types';
import d from '../dashboard/Dashboard.module.css';
import { SusForm } from '../pilot/SusForm';
import type { SessionInfo } from '../state/session';
import type { AssessmentSummary, OutcomeResult } from '../types/contracts';
import s from './Pages.module.css';

type SummaryCase = { case_id?: string; score?: number; is_normal?: boolean | null; outcomes?: { target: string; result: string }[]; findings?: { finding_id: string; kind: string; display: string }[] };

function statsFrom(sm: AssessmentSummary) {
  const cases = (sm.cases ?? []) as SummaryCase[];
  return guardStats({
    n: sm.n_cases,
    n_abnormal: cases.filter((c) => c.is_normal === false).length,
    n_normal: cases.filter((c) => c.is_normal === true).length,
    n_focal_findings: cases.reduce((a, c) => a + (c.findings ?? []).filter((f) => f.kind === 'focal').length, 0),
    sensitivity: sm.sensitivity,
    specificity: sm.specificity,
    localization_fraction: sm.localization_fraction,
    false_positives_per_image: sm.false_positives_per_image,
    miss_type_mix: sm.miss_type_mix,
    score_mean: sm.score_mean,
  });
}

function caseLine(c: SummaryCase): string {
  if (c.is_normal) {
    const fp = (c.outcomes ?? []).filter((o) => o.result === 'false_positive' || o.result === 'pattern_false').length;
    return fp ? `Normal film · ${fp} false mark${fp === 1 ? '' : 's'}` : 'Normal film · left clean';
  }
  const res = new Map((c.outcomes ?? []).map((o) => [o.target, o.result]));
  return (c.findings ?? []).map((f) => `${f.display}: ${OUTCOME_COPY[res.get(f.finding_id) as OutcomeResult]?.text ?? '—'}`).join(' · ');
}

export function AssessmentSummaryView({ session }: { session: SessionInfo }) {
  useTitle('Assessment results');
  const q = useQuery({ queryKey: ['summary', session.sessionId], queryFn: () => api.summary(session.sessionId) });
  const st = q.data ? statsFrom(q.data) : null;
  const mix = st?.miss_type_mix;
  const nMiss = mix ? MISS_BUCKETS.reduce((a, b) => a + mix[b], 0) : 0;
  const cases = (q.data?.cases ?? []) as SummaryCase[];
  const next = session.mode === 'assess_A' ? 'Start practice' : 'Back to the start';

  return (
    <PageShell>
      <h1 className={s.h1}>{modeDisplay(session.mode)} complete</h1>
      {q.isPending && <p className={s.muted}>Scoring your reads…</p>}
      {q.isError && (
        <p className={s.notice}>
          {q.error instanceof ApiError && q.error.status === 409
            ? 'Some cases in this set are not submitted yet. Go back and finish them to see the summary.'
            : 'The summary could not be loaded. Your reads are saved; reload this page to try again.'}
        </p>
      )}
      {q.data && (
        <div data-testid="assessment-summary">
          <p className={s.lede}>{q.data.n_cases} cases read. Here is how you did across the whole set.</p>
          <SummaryStats st={st} title="Your results" />
          <Section title="How the misses happened" testid="summary-miss-mix" n={`n = ${nMiss} misses over ${q.data.n_cases} cases`}
            caption="Based on your cursor, loupe and zoom — a proxy for where you looked.">
            {nMiss === 0 || !mix ? <p className={d.empty}>No misses or overcalls in this set.</p> : (
              <table className={d.statRows}>
                <tbody>
                  {MISS_BUCKETS.map((b) => (
                    <tr key={b} data-testid={`miss-${b}`}>
                      <th scope="row"><span className={d.swatch} style={{ background: MISS_COLOR[b], display: 'inline-block', marginRight: 10, verticalAlign: 'middle' }} />{MISS_NAME[b].plain}<span className={d.statBasis}>{MISS_NAME[b].term}</span></th>
                      <td><span className={d.statValue}>{mix[b]}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
          {cases.length > 0 && (
            <Section title="Case by case" n={`n = ${cases.length} cases`}>
              <TableView caption="Each case in the set" head={['Case', 'Score', 'What happened']}
                rows={cases.map((c, i) => [i + 1, Math.round(c.score ?? 0), caseLine(c)])} />
            </Section>
          )}
          <p><Link to="/" className={s.primaryLink}>{next}</Link></p>
          <SusForm learnerId={session.learnerId} />
        </div>
      )}
    </PageShell>
  );
}
