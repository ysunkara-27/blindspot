// /cohort — instructor view (SPEC §10.2): the learner metrics aggregated across learners, per-label difficulty,
// cohort blind-spot map. Filters (level, mode, date) are query params sent to the API and mirrored in the URL.
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTitle } from '../app/useTitle';
import { Link, useSearchParams } from 'react-router-dom';
import { api, apiMode, isGateError } from '../api/client';
import { ReviewerGate } from '../app/Gate';
import { LEVELS, MODES } from '../api/labels';
import { PageShell } from '../app/Shell';
import { BlindSpotMap } from '../dashboard/charts/BlindSpotMap';
import { Calibration } from '../dashboard/charts/Calibration';
import { Froc } from '../dashboard/charts/Froc';
import { LabelDifficulty } from '../dashboard/charts/LabelDifficulty';
import { MissTypeMix } from '../dashboard/charts/MissTypeMix';
import { ReviewAreaHabit } from '../dashboard/charts/ReviewAreaHabit';
import { SummaryStats } from '../dashboard/charts/SummaryStats';
import { cohortQuery, pct } from '../dashboard/helpers';
import { Section } from '../dashboard/parts';
import { guardCohortDashboard } from '../dashboard/types';
import d from '../dashboard/Dashboard.module.css';
import s from './Pages.module.css';

const FILTERS = ['level', 'mode', 'from', 'to'] as const;

export function CohortPage() {
  useTitle('Cohort');
  const [params, setParams] = useSearchParams();
  const qs = cohortQuery(params);
  const mock = apiMode().mode === 'mock';
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ['cohort-dashboard', qs],
    queryFn: async () => guardCohortDashboard(await api.cohortDashboard(qs)),
    enabled: !mock,
    placeholderData: keepPreviousData,
  });
  const set = (k: (typeof FILTERS)[number], v: string) => {
    // Start from the live URL: two quick changes must not overwrite each other with a render-time copy of the params
    // (React Router's functional form also hands back the render-time copy).
    const next = new URLSearchParams(window.location.search);
    if (v) next.set(k, v); else next.delete(k);
    setParams(next, { replace: true });
  };
  const anyFilter = FILTERS.some((k) => params.get(k));
  const data = q.data;

  return (
    <PageShell>
      <header className={d.header}>
        <h1 className={s.h1}>Cohort</h1>
        <p className={d.scope}>All learners' submitted reads, including assessment sets unless you filter by mode. For instructors.</p>
      </header>

      <div className={d.filters} role="group" aria-label="Filters">
        <label className={d.control}>Level
          <select className={d.select} value={params.get('level') ?? ''} onChange={(e) => set('level', e.target.value)} data-testid="filter-level">
            <option value="">All levels</option>
            {LEVELS.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </label>
        <label className={d.control}>Mode
          <select className={d.select} value={params.get('mode') ?? ''} onChange={(e) => set('mode', e.target.value)} data-testid="filter-mode">
            <option value="">All modes</option>
            {MODES.map((m) => <option key={m.id} value={m.id}>{m.display}</option>)}
          </select>
        </label>
        <label className={d.control}>From
          <input type="date" className={d.select} value={params.get('from') ?? ''} onChange={(e) => set('from', e.target.value)} data-testid="filter-from" />
        </label>
        <label className={d.control}>To
          <input type="date" className={d.select} value={params.get('to') ?? ''} onChange={(e) => set('to', e.target.value)} data-testid="filter-to" />
        </label>
        {anyFilter && <button type="button" className={d.linkBtn} onClick={() => setParams(new URLSearchParams(), { replace: true })}>Clear filters</button>}
      </div>

      {mock ? (
        <p className={s.notice} data-testid="dashboard-mock">The synthetic demo has no cohort: dashboards only show real reads. Start the API to see the cohort.</p>
      ) : q.isPending ? (
        <p className={s.muted}>Loading the cohort…</p>
      ) : isGateError(q.error, 'reviewer') ? (
        <ReviewerGate what="cohort" onDone={() => qc.resetQueries({ queryKey: ['cohort-dashboard'] })} />
      ) : q.isError ? (
        <p className={s.notice}>The cohort could not be loaded. Check that the API is running, then reload.</p>
      ) : (
        <div className={q.isFetching && q.isPlaceholderData ? d.refetching : undefined} data-testid="cohort-dashboard">
          <p className={d.scope} data-testid="cohort-n">
            n = {data!.n_attempts} case{data!.n_attempts === 1 ? '' : 's'} from {data!.n_learners} learner{data!.n_learners === 1 ? '' : 's'}{anyFilter ? ' (filtered)' : ''}.
          </p>
          {data!.n_attempts === 0 ? (
            <p className={s.lede} data-testid="cohort-empty">No reads match these filters yet.</p>
          ) : (
            <>
              <SummaryStats st={data!.summary} title="The cohort at a glance" />
              <MissTypeMix mix={data!.miss_type_mix} title="How the cohort's misses happen" />
              <LabelDifficulty rows={data!.label_difficulty} />
              <BlindSpotMap map={data!.blindspot_map} title="Cohort blind-spot map" who="the cohort" />
              <ReviewAreaHabit habit={data!.review_area_habit} />
              <Calibration cal={data!.calibration} />
              <Froc froc={data!.froc} />
              <Section title="Learners" testid="cohort-learners" n={`n = ${data!.learners.length} learners`}
                caption="One row per learner, by anonymous id. Sensitivity and specificity are case-level.">
                <table className={d.dataTable} style={{ width: '100%' }}>
                  <thead><tr><th scope="col">Learner</th><th scope="col">Cases</th><th scope="col">Sensitivity</th><th scope="col">Specificity</th><th scope="col">Mean score</th></tr></thead>
                  <tbody>
                    {[...data!.learners].sort((a, b) => b.n - a.n).map((l) => (
                      <tr key={l.learner_id}>
                        <th scope="row" style={{ fontWeight: 400 }}><Link to={`/progress?learner=${encodeURIComponent(l.learner_id)}`}>{l.learner_id.slice(0, 8)}</Link></th>
                        <td>{l.n}</td><td>{pct(l.sensitivity)}</td><td>{pct(l.specificity)}</td><td>{Math.round(l.score_mean)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>
            </>
          )}
        </div>
      )}
    </PageShell>
  );
}
