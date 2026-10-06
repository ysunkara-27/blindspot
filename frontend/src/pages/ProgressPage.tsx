// /progress — the Reading log (SPEC §10.1). Real reads only (practice sets; test sets are excluded by the API).
// Before the fifth film there are no headline numbers at all: with n that small a percentage misleads. From five on,
// every section states its n. In mock mode the log is not shown: synthetic data never appears on a dashboard (§10.3).
import { useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { api, apiMode, ApiError } from '../api/client';
import { isSampleName, learnerLabel, loadRemembered } from '../api/sessionOptions';
import { PageShell } from '../app/Shell';
import { useTitle } from '../app/useTitle';
import { BlindSpotMap } from '../dashboard/charts/BlindSpotMap';
import { Calibration } from '../dashboard/charts/Calibration';
import { Froc } from '../dashboard/charts/Froc';
import { LearningCurve } from '../dashboard/charts/LearningCurve';
import { MissTypeMix } from '../dashboard/charts/MissTypeMix';
import { ReviewAreaHabit } from '../dashboard/charts/ReviewAreaHabit';
import { SummaryStats } from '../dashboard/charts/SummaryStats';
import { enoughReads, MIN_READS, readsToGo } from '../dashboard/helpers';
import { guardLearnerDashboard } from '../dashboard/types';
import { useSession } from '../state/session';
import d from '../dashboard/Dashboard.module.css';
import s from './Pages.module.css';

const films = (n: number) => `${n} film${n === 1 ? '' : 's'}`;

/** Fewer than five films: progress toward the first numbers, and what will appear. No percentages. */
function EarlyLog({ n }: { n: number }) {
  const left = readsToGo(n);
  return (
    <div className={d.early} data-testid="dashboard-early">
      <p className={d.earlyLede}>{n === 0 ? 'Your reading log starts with your first film.' : `Good start: ${films(n)} read.`}</p>
      <p className={d.earlyText}>
        Read {left} more to see your first numbers. With fewer than {MIN_READS} films a percentage says more about luck than about you, so none is shown yet.
      </p>
      <ol className={d.pips} aria-hidden="true">
        {Array.from({ length: MIN_READS }, (_, i) => <li key={i} className={`${d.pip} ${i < n ? d.pipOn : ''}`} />)}
      </ol>
      <p className={d.pipText} data-testid="early-count">{n} of {MIN_READS} films</p>
      <Link to="/start" className={s.primaryLink} style={{ marginTop: 0 }} data-testid="early-read">{n === 0 ? 'Start reading' : 'Read more films'}</Link>
      <p className={d.comingUpHead}>What your log will show</p>
      <ul className={d.comingUp}>
        <li>How many abnormal films you catch, and how many normal films you correctly call normal</li>
        <li>Your learning curve, film by film</li>
        <li>How your misses happen: never looked, looked past it, judged it normal, or named it wrong</li>
        <li>A map of where on the chest you miss things</li>
      </ul>
    </div>
  );
}

export function ProgressPage() {
  useTitle('Reading log');
  const session = useSession((st) => st.session);
  const [params] = useSearchParams();
  // ?learner=<id> opens a specific learner's log (the cohort table links here); otherwise the learner of the open set,
  // otherwise the learner this browser remembers.
  const lid = params.get('learner') ?? session?.learnerId ?? loadRemembered()?.learnerId ?? null;
  const mock = apiMode().mode === 'mock';

  const q = useQuery({
    queryKey: ['learner-dashboard', lid],
    queryFn: async () => guardLearnerDashboard(await api.learnerDashboard(lid!)),
    enabled: !!lid && !mock,
  });
  const n = q.data?.n_attempts ?? 0;
  const sample = isSampleName(q.data?.learner?.display_name);

  return (
    <PageShell>
      <header className={d.header}>
        <h1 className={s.h1}>Reading log</h1>
        {q.data?.learner && <p className={d.who} data-testid="learner-name">{learnerLabel(q.data.learner.display_name)}</p>}
        {q.data && (
          <p className={d.scope} data-testid="dashboard-n">
            n = {films(n)} from practice sets. Test sets are scored separately.
            {sample && ' The sample set is shared by everyone who tries it; start your own set to keep a personal log.'}
          </p>
        )}
      </header>

      {mock ? (
        <p className={s.notice} data-testid="dashboard-mock">
          The film library is not reachable, so these are synthetic practice shapes and no reading log is kept. Reload the page once you are back online.
        </p>
      ) : !lid ? (
        <div data-testid="dashboard-no-session"><EarlyLog n={0} /></div>
      ) : q.isPending ? (
        <p className={s.muted}>Loading your reading log…</p>
      ) : q.isError ? (
        <p className={s.notice} data-testid="dashboard-error">
          {q.error instanceof ApiError && q.error.status === 404
            ? <>No reading log was found for this reader. It may belong to another browser. <Link to="/start">Start a set</Link> to begin a new one.</>
            : 'The reading log did not load. Check your connection, then reload the page.'}
        </p>
      ) : !enoughReads(n) ? (
        <div data-testid={n === 0 ? 'dashboard-empty' : 'dashboard-few'}><EarlyLog n={n} /></div>
      ) : (
        <div data-testid="learner-dashboard">
          <SummaryStats st={q.data.summary} />
          <LearningCurve lc={q.data.learning_curve} nCases={n} />
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
