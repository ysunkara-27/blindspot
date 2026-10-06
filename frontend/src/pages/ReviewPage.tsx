// /review — expert review (SPEC §11.1): Debriefs | Teaching cards. Reviewer identity persists in localStorage.
import { useRef } from 'react';
import { useTitle } from '../app/useTitle';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { api, apiMode, isGateError } from '../api/client';
import { ReviewerGate } from '../app/Gate';
import { PageShell } from '../app/Shell';
import { CardReview } from '../review/CardReview';
import { DebriefReview } from '../review/DebriefReview';
import { useReviewer } from '../review/reviewer';
import { guardCardItems, guardDebriefItems, ROLES } from '../review/types';
import r from '../review/Review.module.css';
import s from './Pages.module.css';

type Tab = 'debrief' | 'card';

export function ReviewPage() {
  useTitle('Expert review');
  const [params, setParams] = useSearchParams();
  const tab: Tab = params.get('tab') === 'cards' ? 'card' : 'debrief';
  const [reviewer, setReviewer] = useReviewer();
  const nameRef = useRef<HTMLInputElement>(null);
  const mock = apiMode().mode === 'mock';

  const dq = useQuery({ queryKey: ['review-items', 'debrief'], queryFn: async () => guardDebriefItems(await api.reviewItems('debrief')), enabled: !mock && tab === 'debrief' });
  const cq = useQuery({ queryKey: ['review-items', 'card'], queryFn: async () => guardCardItems(await api.reviewItems('card')), enabled: !mock && tab === 'card' });
  const qc = useQueryClient();
  const gated = isGateError(dq.error, 'reviewer') || isGateError(cq.error, 'reviewer');
  const setTab = (t: Tab) => setParams(t === 'card' ? { tab: 'cards' } : {}, { replace: true });
  const needReviewer = () => nameRef.current?.focus();

  return (
    <PageShell wide>
      {gated ? (
        <>
          <h1 className={s.h1}>Expert review</h1>
          <ReviewerGate what="review" onDone={() => qc.resetQueries({ queryKey: ['review-items'] })} />
        </>
      ) : (<>
      <header className={r.pageHead}>
        <h1 className={s.h1}>Expert review</h1>
        <div className={r.identity}>
          <label className={r.idField}>Your name
            <input ref={nameRef} className={r.input} value={reviewer.name} onChange={(e) => setReviewer({ ...reviewer, name: e.target.value })}
              placeholder="e.g. Dr A. Rao" data-testid="reviewer-name" />
          </label>
          <label className={r.idField}>Role
            <select className={r.input} value={reviewer.role} onChange={(e) => setReviewer({ ...reviewer, role: e.target.value })} data-testid="reviewer-role">
              {ROLES.map((x) => <option key={x}>{x}</option>)}
            </select>
          </label>
          <a className={r.export} href={api.reviewExportUrl} download data-testid="export-csv">Download ratings (CSV)</a>
        </div>
      </header>

      <div className={r.tabs} role="tablist" aria-label="Review queue">
        <button type="button" role="tab" aria-selected={tab === 'debrief'} className={`${r.tab} ${tab === 'debrief' ? r.tabOn : ''}`} onClick={() => setTab('debrief')} data-testid="tab-debriefs">
          Debriefs{dq.data ? ` (${dq.data.length})` : ''}
        </button>
        <button type="button" role="tab" aria-selected={tab === 'card'} className={`${r.tab} ${tab === 'card' ? r.tabOn : ''}`} onClick={() => setTab('card')} data-testid="tab-cards">
          Teaching cards{cq.data ? ` (${cq.data.length})` : ''}
        </button>
      </div>

      {mock ? (
        <p className={s.notice}>Review needs the real API: the synthetic demo has no review queue.</p>
      ) : tab === 'debrief' ? (
        dq.isPending ? <p className={s.muted}>Loading the queue…</p>
          : dq.isError ? <p className={s.notice}>The review queue could not be loaded. Check that the API is running, then reload.</p>
          : dq.data.length === 0 ? (
            <div className={r.emptyQueue} data-testid="queue-empty">
              <p className={s.lede}>The debrief queue is empty.</p>
              <p className={s.muted}>
                Items come from two places: the curated set written by <code>eval/faithfulness.py</code> to <code>eval/samples/review_queue.jsonl</code>,
                and live debriefs from the reading room (learner flags from “This seems wrong” come first). Read a case, or run the faithfulness eval, then reload.
              </p>
            </div>
          ) : <DebriefReview items={dq.data} reviewer={reviewer} onNeedReviewer={needReviewer} />
      ) : (
        cq.isPending ? <p className={s.muted}>Loading the cards…</p>
          : cq.isError ? <p className={s.notice}>The teaching cards could not be loaded. Check that the API is running, then reload.</p>
          : cq.data.length === 0 ? <p className={s.lede} data-testid="cards-empty">No teaching cards found in content/teaching_cards/.</p>
          : <CardReview items={cq.data} reviewer={reviewer} onNeedReviewer={needReviewer} />
      )}
      </>)}
    </PageShell>
  );
}
