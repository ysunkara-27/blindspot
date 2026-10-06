// The end of a set, for every mode (SPEC §1.4, §9.3; round 3): what you read, what you found, how the misses
// happened, and one row per film that opens its review. A practice or one-finding set shows counts (a set is too short
// for percentages); the 20-film test also shows the rates, each with its n, and offers the feedback form.
import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import { markTestDone } from '../api/sessionOptions';
import { PageShell } from '../app/Shell';
import { useTitle } from '../app/useTitle';
import { track } from '../analytics';
import { MissBreakdown } from '../dashboard/charts/MissBreakdown';
import { SummaryStats } from '../dashboard/charts/SummaryStats';
import { MISS_NAME } from '../dashboard/palette';
import { Section } from '../dashboard/parts';
import { MISS_BUCKETS } from '../dashboard/types';
import d from '../dashboard/Dashboard.module.css';
import { FeedbackForm } from '../pilot/FeedbackForm';
import { isAssessment, useSession, type SessionInfo } from '../state/session';
import { PROXY_NOTE } from './copy';
import { commonMiss, guardSetSummary, headline, rowLine, type SummaryRow } from './summaryModel';
import p from './Pages.module.css';
import s from './Summary.module.css';

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`;

function FilmRow({ r, sid }: { r: SummaryRow; sid: string }) {
  const line = rowLine(r, (b) => MISS_NAME[b].plain);
  const body = (
    <>
      <span className={s.filmNo}>Film {r.index}</span>
      <span className={s.filmWhat}>{line.what}<span className={s.filmOutcome}>{line.outcome}</span></span>
      <span className={s.filmScore}><strong>{r.score}</strong> / 100</span>
      <span className={s.filmGo}>{r.attemptId ? 'Review' : ''}</span>
    </>
  );
  return (
    <li className={s.film} data-testid="case-row">
      {r.attemptId
        ? <Link className={s.filmLink} to={`/review-case/${encodeURIComponent(r.attemptId)}?set=${encodeURIComponent(sid)}`} data-testid="case-review-link" aria-label={`Review film ${r.index}: ${line.what}. ${line.outcome}`}>{body}</Link>
        : <div className={s.filmStatic}>{body}</div>}
    </li>
  );
}

export function SessionSummaryView({ session }: { session: SessionInfo }) {
  const sid = session.sessionId;
  const q = useQuery({ queryKey: ['summary', sid], queryFn: async () => guardSetSummary(await api.summary(sid)) });
  const sm = q.data;
  const mode = sm?.mode ?? session.mode;
  const test = isAssessment(mode as SessionInfo['mode']);
  useTitle(test ? 'Test results' : sm && !sm.complete ? 'Set in progress' : 'Set complete');
  // The end-of-set page opened (counted once per set, not per render).
  useEffect(() => { track('set_complete'); }, [sid]);
  // A finished test set moves this learner on to the other set next time.
  useEffect(() => {
    if (sm && test && sm.complete && session.learnerId) markTestDone(session.learnerId, mode);
  }, [sm, test, mode, session.learnerId]);

  const h = sm ? headline(sm.rows) : null;
  const nMiss = sm ? MISS_BUCKETS.reduce((a, b) => a + sm.mix[b], 0) : 0;
  const common = sm ? commonMiss(sm.mix) : null;
  const inProgress = !!sm && !sm.complete && !test;

  return (
    <PageShell>
      <h1 className={p.h1} data-testid="summary-title">{test ? 'Test complete' : inProgress ? 'Set in progress' : 'Set complete'}</h1>
      {q.isPending && <p className={p.muted}>Adding up your reads…</p>}
      {q.isError && (
        <p className={p.notice} data-testid="summary-error">
          {q.error instanceof ApiError && q.error.status === 409
            ? 'Some films in this test are not submitted yet. Go back to the reading room and finish them to see the results.'
            : q.error instanceof ApiError && q.error.status === 404
              ? 'This set could not be found. It may have been started in another browser. Start a new set to keep reading.'
              : 'The summary did not load. Your reads are saved; reload this page to try again.'}
          {' '}<Link to={q.error instanceof ApiError && q.error.status === 409 ? '/read' : '/start'}>{q.error instanceof ApiError && q.error.status === 409 ? 'Back to the reading room' : 'Start a new set'}</Link>
        </p>
      )}
      {sm && h && common && (
        <div data-testid={test ? 'assessment-summary' : 'session-summary'}>
          <p className={p.lede} data-testid="summary-lede">
            {inProgress
              ? `You have read ${h.films} of ${sm.total ?? '?'} films so far. This is where the set stands.`
              : test ? `You read all ${plural(h.films, 'film')} with no hints. Here is how the whole set went.`
              : `You read ${plural(h.films, 'film')}. Here is how the set went.`}
          </p>

          {test ? (
            <SummaryStats st={sm.stats} title="Your results" />
          ) : (
            <Section title="Your results" testid="summary-counts" n={`n = ${plural(h.films, 'film')}`}>
              <table className={s.counts}>
                <tbody>
                  <tr data-testid="count-films"><th scope="row">Films read</th><td>{h.films}</td></tr>
                  <tr data-testid="count-found">
                    <th scope="row">Findings found<span className={s.basis}>Located on the film, or called for a whole-film finding such as an enlarged heart.</span></th>
                    <td>{h.findings ? <>{h.found} <span className={s.of}>of {h.findings}</span></> : <span className={s.of}>No findings in this set</span>}</td>
                  </tr>
                  <tr data-testid="count-normal">
                    <th scope="row">Normal films correctly called normal</th>
                    <td>{h.normals ? <>{h.normalsRight} <span className={s.of}>of {h.normals}</span></> : <span className={s.of}>No normal films in this set</span>}</td>
                  </tr>
                  <tr data-testid="count-false">
                    <th scope="row">False alarms<span className={s.basis}>Marks with no finding behind them.</span></th>
                    <td>{h.falseAlarms}</td>
                  </tr>
                </tbody>
              </table>
            </Section>
          )}

          <Section title="How the misses happened" testid="summary-miss-mix" n={`n = ${nMiss} ${nMiss === 1 ? 'miss' : 'misses'} over ${plural(h.films, 'film')}`} caption={PROXY_NOTE}>
            <p className={s.common} data-testid="common-miss">
              {common.text}
              {common.bucket && <span className={s.commonNote}>{common.n} of {nMiss} misses and false alarms in this set.</span>}
            </p>
            {nMiss > 0 && <MissBreakdown mix={sm.mix} />}
          </Section>

          {sm.rows.length > 0 && (
            <Section title="Film by film" testid="summary-cases" n={`n = ${plural(sm.rows.length, 'film')}`}
              caption="Open a film to see the expert outlines over it, your marks and the debrief.">
              <ol className={s.films}>{sm.rows.map((r) => <FilmRow key={r.attemptId ?? r.index} r={r} sid={sid} />)}</ol>
            </Section>
          )}

          <div className={s.actions}>
            {inProgress
              ? <Link to="/read" className={s.primary} data-testid="back-to-set">Back to the reading room</Link>
              : <Link to="/start" className={s.primary} data-testid="read-another">Read another set</Link>}
            <Link to="/progress" className={s.secondary} data-testid="open-log">Open my reading log</Link>
          </div>
          {test && <p className={d.caption}>Test sets are kept apart from your reading log, so practice and test results never mix.</p>}
          {test && session.learnerId && <FeedbackForm learnerId={session.learnerId} />}
        </div>
      )}
    </PageShell>
  );
}

/** /set/:sessionId — the same summary by URL (a bookmark, or the way back from a film review). */
export function SetSummaryPage() {
  const { sessionId = '' } = useParams();
  const current = useSession((st) => st.session);
  const session: SessionInfo = current && current.sessionId === sessionId
    ? current
    : { sessionId, learnerId: '', displayName: '', level: 'other', mode: 'practice' };
  return <SessionSummaryView key={sessionId} session={session} />;
}
