// /review-case/:attemptId — one read, reviewed after the fact: the film with the expert outlines, the learner's marks
// and the search trace, then what was there, the search summary and the debrief. Opened from a row of the end-of-set
// summary (`?set=<session id>` brings the film's place in the set and previous/next links).
// Data: GET /attempts/{aid}/result (the stored SubmitResult; a test-set read answers only once the test is finished)
// and GET /attempts/{aid}/debrief. Ground truth is only ever shown for a submitted read.
// The film, the outcome list and the debrief are the reading room's own components (read/CaseReview, rail/*), so a
// reviewed film looks exactly like the reveal the learner saw; this page adds the loading, the errors and the pager.
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { api, ApiError, assetUrl } from '../api/client';
import { fetchAttemptResult, type AttemptReview } from '../api/sessionOptions';
import { PageShell } from '../app/Shell';
import { useTitle } from '../app/useTitle';
import { DebriefPanel } from '../rail/DebriefPanel';
import { ResultSummary } from '../rail/ResultSummary';
import { CaseReview } from '../read/CaseReview';
import { ReferenceDrawer } from '../reference';
import { guardSetSummary } from './summaryModel';
import c from './CaseReview.module.css';
import p from './Pages.module.css';

/** The film's pixel size: taken from the server when it says, otherwise from the image itself. */
function useImageSize(url: string | null, known: { w: number | null; h: number | null }) {
  const [size, setSize] = useState<{ url: string; w: number; h: number } | null>(null);
  const need = !!url && !(known.w && known.h);
  useEffect(() => {
    if (!need || !url) return;
    let live = true;
    const img = new Image();
    img.onload = () => { if (live && img.naturalWidth > 0) setSize({ url, w: img.naturalWidth, h: img.naturalHeight }); };
    img.src = url;
    return () => { live = false; };
  }, [url, need]);
  if (known.w && known.h) return { w: known.w, h: known.h };
  return size && size.url === url ? { w: size.w, h: size.h } : null;
}

function Film({ review, caseId }: { review: AttemptReview; caseId: string | null }) {
  const id = review.film?.case_id ?? caseId;
  const url = review.film?.image_url ? assetUrl(review.film.image_url) : id ? api.imageUrl(id) : null;
  const size = useImageSize(url, { w: review.film?.width ?? null, h: review.film?.height ?? null });
  const normal = review.result.reveal.findings.length === 0;
  // The result always lists the marks it scored; with none listed, "no marks" is known even without coordinates.
  const marks = review.marks ?? (review.result.reveal.marks.length === 0 ? [] : null);
  if (!url) {
    return <p className={c.notice} data-testid="case-no-film">The film for this read could not be identified from this link. Open the review from the set summary to see it. The outcomes and the debrief are shown here.</p>;
  }
  return (
    <div data-testid="case-film-block">
      <div className={c.surround}>
        {size
          ? <CaseReview result={review.result} imageUrl={url} width={size.w} height={size.h} marks={marks ?? []} />
          : <p className={c.loading}>Loading the film…</p>}
      </div>
      {normal && <p className={c.note}>This film is normal, so there is nothing to outline.</p>}
      {marks == null && (
        <p className={c.note} data-testid="case-no-marks">
          Where you placed your {review.result.reveal.marks.length === 1 ? 'mark' : `${review.result.reveal.marks.length} marks`} is not available for
          this read, so the film shows the expert outlines only. The list beside it says how each mark was scored.
        </p>
      )}
      {marks != null && marks.length === 0 && <p className={c.note} data-testid="case-zero-marks">You placed no marks on this film.</p>}
    </div>
  );
}

export function CaseReviewPage() {
  const { attemptId = '' } = useParams();
  const [params] = useSearchParams();
  const setId = params.get('set');
  const q = useQuery({ queryKey: ['attempt-result', attemptId], queryFn: () => fetchAttemptResult(attemptId), retry: false, staleTime: Infinity });
  // The set summary says which film this was and what comes before and after it.
  const sq = useQuery({ queryKey: ['summary', setId], queryFn: async () => guardSetSummary(await api.summary(setId!)), enabled: !!setId, retry: false });
  const rows = sq.data?.rows ?? [];
  const at = rows.findIndex((r) => r.attemptId === attemptId);
  const row = at >= 0 ? rows[at] : null;
  const prev = at > 0 ? rows[at - 1] : null;
  const next = at >= 0 && at < rows.length - 1 ? rows[at + 1] : null;
  const to = (aid: string | null) => `/review-case/${encodeURIComponent(aid ?? '')}?set=${encodeURIComponent(setId ?? '')}`;
  useTitle(row ? `Film ${row.index} review` : 'Film review');
  const status = q.error instanceof ApiError ? q.error.status : 0;
  const back = setId ? <Link to={`/set/${encodeURIComponent(setId)}`} data-testid="back-to-summary">Back to the set summary</Link> : <Link to="/progress">Open my reading log</Link>;

  return (
    <PageShell wide>
      <div className={c.head}>
        <div>
          <h1 className={c.h1} data-testid="case-review-title">{row ? `Film ${row.index}${rows.length ? ` of ${rows.length}` : ''}` : 'Film review'}</h1>
          <p className={c.sub}>Your read, with the expert outlines over it.</p>
        </div>
        <nav className={c.pager} aria-label="Films in this set">
          {setId && (prev?.attemptId ? <Link to={to(prev.attemptId)} data-testid="prev-film">Previous film</Link> : <span>Previous film</span>)}
          {setId && (next?.attemptId ? <Link to={to(next.attemptId)} data-testid="next-film">Next film</Link> : <span>Next film</span>)}
          {back}
        </nav>
      </div>

      {q.isPending ? <p className={p.muted}>Loading your read…</p> : q.isError ? (
        <p className={c.notice} data-testid="case-review-error">
          {status === 409 ? 'This review is not open yet. A film can be reviewed once it is submitted, and a test film once the whole test is finished.'
            : status === 404 ? 'No read was found for this link. It may belong to another browser or to a set that is no longer stored.'
            : 'The review did not load. Check your connection, then reload the page.'}
          {' '}{back}
        </p>
      ) : (
        <div className={c.layout} data-testid="case-review-page">
          <div className={c.left}><Film key={attemptId} review={q.data} caseId={row?.caseId || null} /></div>
          <div className={c.right}>
            <ResultSummary result={q.data.result} settle={false} />
            <DebriefPanel key={attemptId} attemptId={attemptId} findings={q.data.result.reveal.findings} disabled={false} />
            <p className={c.actions}>
              <Link to="/start">Read another set</Link>
              <Link to="/reference">Open the finding library</Link>
            </p>
          </div>
          {/* The "i" beside each finding opens the same reference drawer as in the reading room. */}
          <ReferenceDrawer />
        </div>
      )}
    </PageShell>
  );
}
