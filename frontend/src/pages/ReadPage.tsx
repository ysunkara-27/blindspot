// /read — the reading room (SPEC §1.3, §5, §14). One case at a time; ReadingRoom is keyed by attempt id.
import { useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, Navigate } from 'react-router-dom';
import { api, ApiError, isSubmitResult } from '../api/client';
import { labelDisplay, modeDisplay } from '../api/labels';
import { canSubmit, initialRead, readReducer, toSubmitMarks, toSubmitPatterns } from '../read/readState';
import { ReadRail } from '../rail/ReadRail';
import { OutcomeList } from '../rail/OutcomeList';
import { FactsCard } from '../rail/FactsCard';
import { DebriefPanel } from '../rail/DebriefPanel';
import { AskTutor } from '../rail/AskTutor';
import { isAssessment, useSession, type SessionInfo } from '../state/session';
import type { AssessmentRecorded, AttemptSubmit, HintResponse, NextCase, SubmitResult } from '../types/contracts';
import { Viewer } from '../viewer/Viewer';
import type { RevealView } from '../viewer/RevealLayer';
import { colorizeServerHeatmap, densityFromTelemetry, densityToDataUrl } from '../viewer/heatmap';
import { TelemetryBuffer } from '../viewer/telemetry';
import { Footer, Nav, SyntheticBadge } from '../app/Shell';
import { AssessmentSummaryView } from './AssessmentSummaryView';
import shell from '../app/Shell.module.css';
import rail from '../rail/Rail.module.css';

export function ReadPage() {
  const session = useSession((s) => s.session);
  if (!session) return <Navigate to="/" replace />;
  return <ReadSession session={session} />;
}

function preload(url: string) {
  const img = new Image();
  img.src = url;
}

function ReadSession({ session }: { session: SessionInfo }) {
  const qc = useQueryClient();
  const [seq, setSeq] = useState(0);
  const [loupe, setLoupe] = useState(() => !isAssessment(session.mode));
  const sid = session.sessionId;
  const next = useQuery({ queryKey: ['next', sid, seq], queryFn: () => api.next(sid), staleTime: Infinity, gcTime: Infinity, retry: false });

  // After a submit, fetch the next case and warm its image so "Next case" is instant (SPEC §5.1).
  const prefetchNext = useCallback(() => {
    const key = ['next', sid, seq + 1];
    qc.prefetchQuery({ queryKey: key, queryFn: () => api.next(sid), staleTime: Infinity, gcTime: Infinity })
      .then(() => {
        const n = qc.getQueryData<NextCase>(key);
        if (n && !n.done && n.case.image_url) preload(n.case.image_url);
      })
      .catch(() => { /* the Next button will retry */ });
  }, [qc, sid, seq]);

  const header = (n?: NextCase) => (
    <RoomHeader session={session} next={n} loupe={loupe} setLoupe={setLoupe} />
  );

  if (next.isPending || next.isError) {
    return (
      <div className={shell.room}>
        <div className={shell.viewerCol}>
          {header()}
          <div className={shell.viewerWrap} style={{ display: 'grid', placeItems: 'center', color: '#c9d1d8' }}>
            {next.isError ? (
              <div style={{ textAlign: 'center' }}>
                <p>Could not load the next case. {next.error instanceof ApiError && next.error.status === 404 ? 'This session has ended.' : 'The API did not answer.'}</p>
                <button type="button" className={shell.toggle} onClick={() => next.refetch()}>Try again</button>{' '}
                <Link to="/" style={{ color: '#c9d1d8' }}>Start a new session</Link>
              </div>
            ) : 'Loading case…'}
          </div>
        </div>
        <aside className={shell.rail}><div className={shell.railBody} /><Footer /></aside>
      </div>
    );
  }
  if (next.data.done) {
    return isAssessment(session.mode) ? <AssessmentSummaryView session={session} /> : (
      <div className={shell.page}>
        <main className={shell.pageMain}>
          <h1>You have read every case in this set.</h1>
          <p><Link to="/">Start a new session</Link> or open your <Link to="/progress">reading log</Link>.</p>
        </main>
        <Footer className={shell.pageFooter} />
      </div>
    );
  }
  return (
    <ReadingRoom
      key={next.data.attempt_id}
      session={session}
      next={next.data}
      header={header(next.data)}
      loupe={loupe}
      setLoupe={setLoupe}
      onNext={() => setSeq((n) => n + 1)}
      prefetchNext={prefetchNext}
    />
  );
}

function RoomHeader({ session, next, loupe, setLoupe }: { session: SessionInfo; next?: NextCase; loupe: boolean; setLoupe: (v: boolean) => void }) {
  const projector = useSession((s) => s.projector);
  const setProjector = useSession((s) => s.setProjector);
  return (
    <header className={shell.header}>
      <Link to="/" className={shell.brand}>Blindspot</Link>
      <span className={shell.mode} data-testid="mode">
        {modeDisplay(session.mode)}{session.mode === 'drill' && session.drillLabel ? ` · ${labelDisplay(session.drillLabel)}` : ''}
      </span>
      {next && (
        <span className={shell.caseIdx} data-testid="case-index">Case {next.index}{next.total ? ` of ${next.total}` : ''}</span>
      )}
      <SyntheticBadge />
      <span className={shell.spacer} />
      <button type="button" className={`${shell.toggle} ${loupe ? shell.toggleOn : ''}`} aria-pressed={loupe} onClick={() => setLoupe(!loupe)} data-testid="loupe-toggle" title="Loupe (L)">
        <span className={shell.dot} />Loupe
      </button>
      <button type="button" className={`${shell.toggle} ${projector ? shell.toggleOn : ''}`} aria-pressed={projector} onClick={() => setProjector(!projector)} data-testid="projector-toggle" title="Projector mode: brighter film, thicker lines, larger type">
        <span className={shell.dot} />Projector
      </button>
      <Nav />
    </header>
  );
}

const isTyping = (t: EventTarget | null) => {
  const el = t as HTMLElement | null;
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable);
};

function ReadingRoom({ session, next, header, loupe, setLoupe, onNext, prefetchNext }: {
  session: SessionInfo; next: NextCase; header: React.ReactNode; loupe: boolean; setLoupe: (v: boolean) => void;
  onNext: () => void; prefetchNext: () => void;
}) {
  const projector = useSession((s) => s.projector);
  const aid = next.attempt_id;
  const assessment = isAssessment(session.mode);
  const [read, dispatch] = useReducer(readReducer, initialRead);
  const telemetry = useMemo(() => new TelemetryBuffer(), []);
  const shownAt = useRef('');
  const submittedTelemetry = useRef<AttemptSubmit['telemetry']>([]);
  const [confirmNormal, setConfirmNormal] = useState(false);
  const [hints, setHints] = useState<HintResponse[]>([]);
  const [hintsLeft, setHintsLeft] = useState(3);
  const [hintError, setHintError] = useState<string | null>(null);
  const [result, setResult] = useState<SubmitResult | AssessmentRecorded | null>(null);
  const [heatmapUrl, setHeatmapUrl] = useState<string | null>(null);
  const hintsEnabled = !assessment && next.hints_enabled !== false;

  // Dev/e2e only: lets Playwright count telemetry events (SPEC §15.2 M4). Never in production builds.
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    const w = window as unknown as { __bsTelemetry?: TelemetryBuffer };
    w.__bsTelemetry = telemetry;
    return () => { if (w.__bsTelemetry === telemetry) delete w.__bsTelemetry; };
  }, [telemetry]);

  const onShown = useCallback(() => {
    shownAt.current = new Date().toISOString();
    telemetry.start();
  }, [telemetry]);

  const hintM = useMutation({
    mutationFn: () => api.hint(aid, { marks: toSubmitMarks(read), telemetry: telemetry.snapshot() }),
    onSuccess: (h) => { setHints((l) => [...l, h]); setHintsLeft(h.remaining); setHintError(null); },
    onError: (e) => setHintError(e instanceof ApiError && e.status === 409 ? 'No hints left for this case.' : 'Hints are unavailable right now.'),
  });

  const submitM = useMutation({
    mutationFn: (body: AttemptSubmit) => api.submit(aid, body),
    onSuccess: async (r) => {
      if (isSubmitResult(r)) {
        // Build the search trace before revealing so the sequence starts with it.
        let url: string | null = null;
        try {
          const b64 = r.reveal.search.heatmap_png_b64;
          url = b64 ? await colorizeServerHeatmap(b64) : densityToDataUrl(densityFromTelemetry(submittedTelemetry.current, next.case.width, next.case.height));
        } catch {
          url = densityToDataUrl(densityFromTelemetry(submittedTelemetry.current, next.case.width, next.case.height));
        }
        setHeatmapUrl(url);
      }
      setResult(r);
      prefetchNext();
    },
  });

  const submit = useCallback(() => {
    if (!canSubmit(read) || submitM.isPending || result) return;
    const tel = telemetry.snapshot();
    submittedTelemetry.current = tel;
    dispatch({ type: 'closePopover' });
    submitM.mutate({
      marks: toSubmitMarks(read),
      patterns: toSubmitPatterns(read),
      declared_normal: read.declaredNormal,
      normal_confidence: read.declaredNormal ? read.normalConfidence : null,
      telemetry: tel,
      hints_used: hints.length,
      client_timing: { shown_at: shownAt.current || new Date().toISOString(), submitted_at: new Date().toISOString() },
    });
  }, [read, submitM, result, telemetry, hints.length]);

  const askHint = useCallback(() => {
    if (hintsEnabled && hintsLeft > 0 && !hintM.isPending && !result) hintM.mutate();
  }, [hintsEnabled, hintsLeft, hintM, result]);

  const callNormal = useCallback(() => {
    if (result || read.declaredNormal) return;
    if (read.marks.length || Object.keys(read.patterns).length) setConfirmNormal(true);
    else dispatch({ type: 'callNormal' });
  }, [result, read]);

  // Keyboard shortcuts (SPEC §5.1).
  const conflict = submitM.error instanceof ApiError && submitM.error.status === 409;
  const keys = useRef({ submit, askHint, callNormal, read, result, onNext, loupe, setLoupe, conflict });
  useLayoutEffect(() => {
    keys.current = { submit, askHint, callNormal, read, result, onNext, loupe, setLoupe, conflict };
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e.target)) return;
      const k = keys.current;
      const sel = k.read.selectedId;
      const onButton = (e.target as HTMLElement | null)?.tagName === 'BUTTON';
      switch (e.key) {
        case 'l': case 'L': k.setLoupe(!k.loupe); break;
        case 'n': case 'N': k.callNormal(); break;
        case 'h': case 'H': k.askHint(); break;
        case '1': case '2': case '3': case '4': case '5':
          if (sel && !k.result) dispatch({ type: 'confidence', id: sel, confidence: Number(e.key) as 1 | 2 | 3 | 4 | 5 });
          break;
        case 'Backspace': case 'Delete':
          if (sel && !k.result) { e.preventDefault(); dispatch({ type: 'delete', id: sel }); }
          break;
        case 'Escape':
          dispatch({ type: 'select', id: null });
          break;
        case 'Enter':
          if (onButton) return;
          e.preventDefault();
          if (!k.result) k.submit();
          else k.onNext();
          break;
        case 'ArrowRight':
          if (k.result || k.conflict) { e.preventDefault(); k.onNext(); }
          break;
        default:
          return;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const submitResult = result && isSubmitResult(result) ? result : null;
  const reveal: RevealView | null = submitResult
    ? { findings: submitResult.reveal.findings, marks: submitResult.reveal.marks, arrows: submitResult.reveal.arrows, heatmapUrl, showTrace: true }
    : null;

  return (
    <div className={shell.room} data-testid="reading-room" data-attempt={aid}>
      <div className={shell.viewerCol}>
        {header}
        <div className={shell.viewerWrap}>
          <Viewer
            caseId={next.case.case_id}
            imageUrl={next.case.image_url}
            width={next.case.width}
            height={next.case.height}
            marks={read.marks}
            selectedId={read.selectedId}
            popoverId={read.popoverId}
            dispatch={dispatch}
            canMark={!result && !read.declaredNormal}
            markBlockedReason={read.declaredNormal ? 'You called this film normal. Undo the call in the rail to add marks.' : undefined}
            loupe={loupe}
            projector={projector}
            telemetry={telemetry}
            reveal={reveal}
            onShown={onShown}
          />
        </div>
      </div>
      <aside className={shell.rail} aria-label="Your read and feedback">
        <div className={shell.railBody}>
          {!result ? (
            <ReadRail
              read={read}
              dispatch={dispatch}
              hints={{ enabled: hintsEnabled, remaining: hintsLeft, list: hints, pending: hintM.isPending, error: hintError, onHint: askHint }}
              confirmNormal={confirmNormal}
              setConfirmNormal={setConfirmNormal}
              onSubmit={submit}
              submitting={submitM.isPending}
              submitError={submitM.isError
                ? submitM.error instanceof ApiError && submitM.error.status === 409
                  ? 'This case was already recorded. Press → for the next case.'
                  : 'Your read was not saved. Check the connection and press Submit read again.'
                : null}
              alreadyRecorded={submitM.error instanceof ApiError && submitM.error.status === 409}
              onNext={onNext}
            />
          ) : submitResult ? (
            <div className={rail.result}>
              <h2 className={rail.h2}>The expert read</h2>
              <OutcomeList result={submitResult} />
              <FactsCard card={submitResult.facts_card} />
              <DebriefPanel attemptId={aid} findings={submitResult.reveal.findings} disabled={submitResult.debrief_status === 'disabled'} />
              {submitResult.debrief_status !== 'disabled' && <AskTutor attemptId={aid} />}
              <div className={rail.nextBar}>
                <button type="button" className={rail.primary} onClick={onNext} data-testid="next-case">
                  Next case <kbd className={rail.kbdLight}>→</kbd>
                </button>
              </div>
            </div>
          ) : (
            <div className={rail.result} data-testid="recorded">
              <h2 className={rail.h2}>Recorded.</h2>
              <p className={rail.p}>Feedback for this assessment comes at the end{next.total ? `, after case ${next.total}` : ''}.</p>
              <div className={rail.nextBar}>
                <button type="button" className={rail.primary} onClick={onNext} data-testid="next-case">
                  Next case <kbd className={rail.kbdLight}>→</kbd>
                </button>
              </div>
            </div>
          )}
        </div>
        <Footer />
      </aside>
    </div>
  );
}
