// End-of-assessment summary (SPEC §1.4, §9.3): the only feedback an assessment gives, shown after the last case.
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { modeDisplay } from '../api/labels';
import { PageShell } from '../app/Shell';
import type { SessionInfo } from '../state/session';
import s from './Pages.module.css';

const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 100)}%`);
const MISS: Record<string, string> = {
  search: 'Never looked there', recognition: 'Looked past it', decision: 'Looked, judged it normal',
  interpretation: 'Found it, named it wrong', overcall: "Called something that isn't there",
};

export function AssessmentSummaryView({ session }: { session: SessionInfo }) {
  const q = useQuery({ queryKey: ['summary', session.sessionId], queryFn: () => api.summary(session.sessionId) });
  return (
    <PageShell>
      <h1 className={s.h1}>{modeDisplay(session.mode)} complete</h1>
      {q.isPending && <p className={s.muted}>Scoring your reads…</p>}
      {q.isError && <p className={s.notice}>The summary could not be loaded. Your reads are saved; reload this page to try again.</p>}
      {q.data && (
        <div data-testid="assessment-summary">
          <p className={s.lede}>{q.data.n_cases} cases read. Here is how you did, across the whole set.</p>
          <table className={s.stats}>
            <tbody>
              <tr><th>Mean score</th><td>{Math.round(q.data.score_mean)}</td></tr>
              <tr><th>Abnormal films you marked correctly (sensitivity)</th><td>{pct(q.data.sensitivity)}</td></tr>
              <tr><th>Normal films left clean (specificity)</th><td>{pct(q.data.specificity)}</td></tr>
              <tr><th>Findings localized</th><td>{pct(q.data.localization_fraction)}</td></tr>
              <tr><th>False marks per film</th><td>{q.data.false_positives_per_image.toFixed(2)}</td></tr>
            </tbody>
          </table>
          <h2 className={s.h2}>How the misses happened</h2>
          {Object.keys(q.data.miss_type_mix).length === 0 ? <p className={s.muted}>No misses.</p> : (
            <table className={s.stats}>
              <tbody>
                {Object.entries(q.data.miss_type_mix).map(([k, n]) => (
                  <tr key={k}><th>{MISS[k] ?? k}</th><td>{n}</td></tr>
                ))}
              </tbody>
            </table>
          )}
          <p className={s.mutedSmall}>Miss types are based on your cursor, loupe and zoom — a proxy for where you looked. n = {q.data.n_cases} cases.</p>
          <p><Link to="/" className={s.primaryLink}>Start practice</Link></p>
        </div>
      )}
    </PageShell>
  );
}
