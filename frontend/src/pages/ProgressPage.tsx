// /progress — the Reading log (SPEC §10.1). Real attempts only (practice, drill, review; assessments excluded by the API).
// Every section states its n. In mock mode the log is not shown: synthetic data never appears on a dashboard (§10.3).
import { useQuery } from '@tanstack/react-query';
import { useTitle } from '../app/useTitle';
import { Link, useSearchParams } from 'react-router-dom';
import { api, apiMode, ApiError } from '../api/client';
import { PageShell } from '../app/Shell';
import { BlindSpotMap } from '../dashboard/charts/BlindSpotMap';
import { Calibration } from '../dashboard/charts/Calibration';
import { Froc } from '../dashboard/charts/Froc';
import { EMPTY_CURVE, LearningCurve } from '../dashboard/charts/LearningCurve';
import { MissTypeMix } from '../dashboard/charts/MissTypeMix';
import { ReviewAreaHabit } from '../dashboard/charts/ReviewAreaHabit';
import { SummaryStats } from '../dashboard/charts/SummaryStats';
import { guardLearnerDashboard } from '../dashboard/types';
import { useSession } from '../state/session';
import d from '../dashboard/Dashboard.module.css';
import s from './Pages.module.css';

export function ProgressPage() {
  useTitle('Reading log');
  const session = useSession((st) => st.session);
  const [params] = useSearchParams();
  // ?learner=<id> lets an instructor (or a test) open a specific learner's log; otherwise the current session's learner.
  const lid = params.get('learner') ?? session?.learnerId ?? null;
  const mock = apiMode().mode === 'mock';

  const q = useQuery({
    queryKey: ['learner-dashboard', lid],
    queryFn: async () => guardLearnerDashboard(await api.learnerDashboard(lid!)),
    enabled: !!lid && !mock,
  });

  return (
    <PageShell>
      <header className={d.header}>
        <h1 className={s.h1}>Reading log</h1>
        {q.data?.learner && <p className={d.who} data-testid="learner-name">{q.data.learner.display_name} · {q.data.learner.level}</p>}
        {q.data && (
          <p className={d.scope} data-testid="dashboard-n">
            n = {q.data.n_attempts} case{q.data.n_attempts === 1 ? '' : 's'} from practice, drill and review. Assessment sets are scored separately.
          </p>
        )}
      </header>

      {mock ? (
        <p className={s.notice} data-testid="dashboard-mock">
          The synthetic demo does not keep a reading log: dashboards only show real reads. Start the API to see yours.
        </p>
      ) : !lid ? (
        <div data-testid="dashboard-no-session">
          <p className={s.lede}>Start a session to begin your reading log. {EMPTY_CURVE}</p>
          <Link to="/" className={s.primaryLink}>Start reading</Link>
        </div>
      ) : q.isPending ? (
        <p className={s.muted}>Loading your reading log…</p>
      ) : q.isError ? (
        <p className={s.notice}>
          {q.error instanceof ApiError && q.error.status === 404
            ? 'No reading log for this learner. Start a session from the first page.'
            : 'The reading log could not be loaded. Check that the API is running, then reload.'}
        </p>
      ) : q.data.n_attempts === 0 ? (
        <div data-testid="dashboard-empty">
          <p className={s.lede}>{EMPTY_CURVE}</p>
          <Link to="/read" className={s.primaryLink}>Read a case</Link>
        </div>
      ) : (
        <div data-testid="learner-dashboard">
          <SummaryStats st={q.data.summary} />
          <LearningCurve lc={q.data.learning_curve} nCases={q.data.n_attempts} />
          <MissTypeMix mix={q.data.miss_type_mix} />
          <BlindSpotMap map={q.data.blindspot_map} />
          <ReviewAreaHabit habit={q.data.review_area_habit} />
          <Calibration cal={q.data.calibration} />
          <Froc froc={q.data.froc} />
        </div>
      )}
    </PageShell>
  );
}
