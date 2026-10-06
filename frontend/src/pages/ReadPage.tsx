// /read — the reading room (SPEC §1.3, §5, §14). One case at a time; ReadingRoom is keyed by attempt id.
// Round 3: pathology-first marking, required confidence, magnifier off by default, reference drawer, first-run
// tutorial, search trace with a legend and "not visited" rings, and a header that says "Case 3 of 10".
import { useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, Navigate, useSearchParams } from 'react-router-dom';
import { api, ApiError, assetUrl, isSubmitResult } from '../api/client';
import { labelDisplay, modeDisplay, zoneDisplay } from '../api/labels';
import { canSubmit, confidenceTarget, initialRead, readReducer, toHintMarks, toSubmitMarks, toSubmitPatterns } from '../read/readState';
import { ReadRail } from '../rail/ReadRail';
import { ResultSummary } from '../rail/ResultSummary';
import { DebriefPanel } from '../rail/DebriefPanel';
import { AskTutor } from '../rail/AskTutor';
import { isAssessment, useSession, type SessionInfo } from '../state/session';
import type { AssessmentRecorded, AttemptSubmit, Confidence, HintResponse, NextCase, SubmitResult } from '../types/contracts';
import { Viewer } from '../viewer/Viewer';
import type { RevealView } from '../viewer/RevealLayer';
import { colorizeServerHeatmap, densityFromTelemetry, densityToDataUrl } from '../viewer/heatmap';
import { TelemetryBuffer } from '../viewer/telemetry';
import { Footer, Nav, SyntheticBadge } from '../app/Shell';
import { track } from '../analytics';
import { TutorNotice } from '../tutor/TutorNotice';
import { SessionSummaryView } from './SessionSummaryView';
import { KeysHelp } from '../read/KeysHelp';
import { caseLabel } from '../read/keys';
import { useTitle } from '../app/useTitle';
import { guardAnatomy, unvisitedRings } from '../viewer/anatomy';
import { ReferenceDrawer } from '../reference/ReferenceDrawer';
import { useReference } from '../reference/store';
import { BOOT_TUTORIAL_FLAG, hasTutorialFlag, shouldOpenTutorial, Tutorial, tutorialDone } from '../tutorial';
import shell from '../app/Shell.module.css';
import rail from '../rail/Rail.module.css';
import room from '../read/Room.module.css';

const SEARCH_KEY = 'blindspot.showSearch';

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
  // The magnifier is off until the learner asks for it, in every mode.
  const [loupe, setLoupe] = useState(false);
  const [showSearch, setShowSearch] = useState(() => { try { return localStorage.getItem(SEARCH_KEY) !== '0'; } catch { return true; } });
  const toggleSearch = useCallback(() => setShowSearch((v) => {
    try { localStorage.setItem(SEARCH_KEY, v ? '0' : '1'); } catch { /* storage blocked: the choice lasts this visit */ }
    return !v;
  }), []);
  const sid = session.sessionId;
  const next = useQuery({ queryKey: ['next', sid, seq], queryFn: () => api.next(sid), staleTime: Infinity, gcTime: Infinity, retry: false });
  const [help, setHelp] = useState(false);
  const closeHelp = useCallback(() => setHelp(false), []);
  const [params, setParams] = useSearchParams();
  const [tour, setTour] = useState(false);
  // The tutorial opens by itself once, on the first case of a first session (see tutorial/steps.ts for the rule),
  // as soon as that film is on screen: by then every control it points at exists.
  const tourDecided = useRef(false);
  const urlFlag = hasTutorialFlag(params.toString());
  const onFilmShown = useCallback((index: number) => {
    if (tourDecided.current) return;
    tourDecided.current = true;
    const open = shouldOpenTutorial({
      webdriver: !!navigator.webdriver, bootFlag: BOOT_TUTORIAL_FLAG, urlFlag, done: tutorialDone(), firstCase: index === 1,
    });
    if (open) setTour(true);
  }, [urlFlag]);
  const closeTour = useCallback(() => {
    setTour(false);
    setParams((p) => { const n = new URLSearchParams(p); n.delete('tutorial'); return n; }, { replace: true });
  }, [setParams]);
  const openTour = useCallback(() => { setHelp(false); setTour(true); }, []);

  useTitle(!next.data ? 'Reading room' : next.data.done ? (isAssessment(session.mode) ? 'Assessment results' : 'Set complete') : `Case ${next.data.index} · Reading room`);
  // "?" opens the key list from anywhere in the reading room (the open dialog handles its own keys).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '?' && !e.metaKey && !e.ctrlKey && !e.altKey && !isTyping(e.target)) { e.preventDefault(); setHelp(true); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  const layers = (
    <>
      {help ? <KeysHelp onClose={closeHelp} /> : null}
      {tour && !help ? <Tutorial onClose={closeTour} /> : null}
    </>
  );

  // After a submit, fetch the next case and warm its image so "Next case" is instant (SPEC §5.1).
  const prefetchNext = useCallback(() => {
    const key = ['next', sid, seq + 1];
    qc.prefetchQuery({ queryKey: key, queryFn: () => api.next(sid), staleTime: Infinity, gcTime: Infinity })
      .then(() => {
        const n = qc.getQueryData<NextCase>(key);
        if (n && !n.done && n.case.image_url) preload(assetUrl(n.case.image_url));
      })
      .catch(() => { /* the Next button will retry */ });
  }, [qc, sid, seq]);

  const header = (n?: NextCase) => (
    <RoomHeader session={session} next={n} onHelp={() => setHelp(true)} onTour={openTour} />
  );

  if (next.isPending || next.isError) {
    return (
      <div className={`${shell.room} ${room.root}`}>
        <div className={shell.viewerCol}>
          {header()}
          <div className={`${shell.viewerWrap} ${room.center}`}>
            {next.isError ? (
              <div>
                <p>Could not load the next case. {next.error instanceof ApiError && next.error.status === 404 ? 'This session has ended.' : 'The API did not answer.'}</p>
                <button type="button" className={room.btn} onClick={() => next.refetch()}>Try again</button>{' '}
                <Link to="/">Start a new session</Link>
              </div>
            ) : 'Loading case…'}
          </div>
        </div>
        <aside className={shell.rail}><div className={shell.railBody} /><Footer /></aside>
        {help ? <KeysHelp onClose={closeHelp} /> : null}
      </div>
    );
  }
  // The set is over (practice, drill or test set): the pages side owns the end-of-set summary.
  if (next.data.done) return <SessionSummaryView session={session} />;
  return (
    <>
      {layers}
      <ReadingRoom
        key={next.data.attempt_id}
        session={session}
        next={next.data}
        header={header(next.data)}
        loupe={loupe}
        setLoupe={setLoupe}
        showSearch={showSearch}
        toggleSearch={toggleSearch}
        onFilmShown={onFilmShown}
        onNext={() => setSeq((n) => n + 1)}
        prefetchNext={prefetchNext}
      />
    </>
  );
}

/** Header "View" menu: display options that are not part of reading a film. */
function ViewMenu() {
  const projector = useSession((s) => s.projector);
  const setProjector = useSession((s) => s.setProjector);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const open = !!pos;
  const toggle = () => {
    if (open) { setPos(null); return; }
    const r = btn.current?.getBoundingClientRect();
    if (r) setPos({ left: Math.max(8, Math.min(r.left, window.innerWidth - 270)), top: r.bottom + 6 });
  };
  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLButtonElement>('button')?.focus({ preventScroll: true });
    const away = (e: Event) => {
      const t = e.target as Node | null;
      if (t && (menu.current?.contains(t) || btn.current?.contains(t))) return;
      setPos(null);
    };
    const close = () => setPos(null);
    window.addEventListener('pointerdown', away, true);
    window.addEventListener('resize', close);
    return () => { window.removeEventListener('pointerdown', away, true); window.removeEventListener('resize', close); };
  }, [open]);
  return (
    <>
      <button ref={btn} type="button" className={`${room.btn} ${open ? room.btnOn : ''}`} aria-haspopup="true" aria-expanded={open}
        onClick={toggle} data-testid="view-menu" title="Display options">
        View <span className={room.caret} aria-hidden="true">▾</span>
      </button>
      {pos && (
        <div ref={menu} className={room.menu} style={pos} role="group" aria-label="View options" data-testid="view-menu-list"
          onKeyDown={(e) => {
            if (e.key === 'Escape') { e.preventDefault(); setPos(null); btn.current?.focus(); }
            if (e.key !== 'Tab') e.stopPropagation();
          }}>
          <button type="button" className={room.menuItem} aria-pressed={projector} onClick={() => setProjector(!projector)} data-testid="projector-toggle">
            <span>Large-screen mode: {projector ? 'on' : 'off'}</span>
            <span className={room.menuNote}>For a projector: brighter film, thicker lines, larger type.</span>
          </button>
        </div>
      )}
    </>
  );
}

function RoomHeader({ session, next, onHelp, onTour }: {
  session: SessionInfo; next?: NextCase; onHelp: () => void; onTour: () => void;
}) {
  const done = next ? Math.max(0, next.index - 1) : 0;
  return (
    <header className={room.header}>
      <Link to="/" className={shell.brand}>Blindspot</Link>
      <span className={shell.mode} data-testid="mode">
        {modeDisplay(session.mode)}{session.mode === 'drill' && session.drillLabel ? ` · ${labelDisplay(session.drillLabel)}` : ''}
      </span>
      {next && (
        <span className={room.caseBlock}>
          <span className={room.caseText} data-testid="case-index">{caseLabel(next.index, next.total)}</span>
          {next.total ? (
            <span className={room.progress} role="progressbar" aria-label="Cases read" aria-valuemin={0} aria-valuemax={next.total} aria-valuenow={done}
              aria-valuetext={`${done} of ${next.total} read`} data-testid="case-progress">
              <span style={{ width: `${(100 * done) / next.total}%` }} />
            </span>
          ) : null}
        </span>
      )}
      <SyntheticBadge short />
      <span className={room.spacer} />
      <ViewMenu />
      <button type="button" className={room.btn} onClick={onTour} data-testid="tutorial-button" title="Walk through the reading room, step by step">
        How to read here
      </button>
      <button type="button" className={room.btn} onClick={onHelp} data-testid="keys-button" title="Keyboard and mouse shortcuts (?)">
        Keys <kbd className={room.kbd}>?</kbd>
      </button>
      <span className={room.navWrap}><Nav compact /></span>
    </header>
  );
}

const isTyping = (t: EventTarget | null) => {
  const el = t as HTMLElement | null;
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable);
};
/** A field that uses the keyboard itself (text, sliders). Checkboxes do not count: after ticking a whole-film finding
 *  the shortcuts (1–5, H, Enter…) keep working. */
const isTextEntry = (t: EventTarget | null) => {
  const el = t as HTMLInputElement | null;
  if (!isTyping(el)) return false;
  return !(el!.tagName === 'INPUT' && ['checkbox', 'radio', 'button'].includes(el!.type));
};

function ReadingRoom({ session, next, header, loupe, setLoupe, showSearch, toggleSearch, onFilmShown, onNext, prefetchNext }: {
  session: SessionInfo; next: NextCase; header: React.ReactNode; loupe: boolean; setLoupe: (v: boolean) => void;
  showSearch: boolean; toggleSearch: () => void; onFilmShown: (index: number) => void; onNext: () => void; prefetchNext: () => void;
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
  const [anatomyOn, setAnatomyOn] = useState(false);

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
    onFilmShown(next.index);
  }, [telemetry, onFilmShown, next.index]);

  const hintM = useMutation({
    mutationFn: () => api.hint(aid, { marks: toHintMarks(read), telemetry: telemetry.snapshot() }),
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
      track('film_submitted');
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
    if (hintsEnabled && hintsLeft > 0 && !hintM.isPending && !result) { track('hint'); hintM.mutate(); }
  }, [hintsEnabled, hintsLeft, hintM, result]);

  const callNormal = useCallback(() => {
    if (result || read.declaredNormal) return;
    if (read.marks.length || Object.keys(read.patterns).length) setConfirmNormal(true);
    else dispatch({ type: 'callNormal' });
  }, [result, read]);

  // Keyboard shortcuts (SPEC §5.1).
  const conflict = submitM.error instanceof ApiError && submitM.error.status === 409;
  const canAnatomy = !!result && isSubmitResult(result);
  const keys = useRef({ submit, askHint, callNormal, read, result, onNext, loupe, setLoupe, conflict, canAnatomy });
  useLayoutEffect(() => {
    keys.current = { submit, askHint, callNormal, read, result, onNext, loupe, setLoupe, conflict, canAnatomy };
  });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const k = keys.current;
      // Ctrl/Cmd + Enter submits from anywhere (the film and buttons use plain Enter for themselves).
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !e.altKey) {
        e.preventDefault();
        if (!k.result) k.submit();
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey || isTextEntry(e.target)) return;
      const sel = k.read.selectedId;
      const onButton = (e.target as HTMLElement | null)?.tagName === 'BUTTON';
      switch (e.key) {
        case 'm': case 'M': case 'l': case 'L': k.setLoupe(!k.loupe); break;
        case 'n': case 'N': k.callNormal(); break;
        case 'h': case 'H': k.askHint(); break;
        case 'a': case 'A': if (k.canAnatomy) setAnatomyOn((v) => !v); break;
        case '1': case '2': case '3': case '4': case '5': {
          // The selected mark, or the normal call when it is active.
          const t = k.result ? null : confidenceTarget(k.read);
          const c = Number(e.key) as Confidence;
          if (t?.kind === 'mark') dispatch({ type: 'confidence', id: t.id, confidence: c });
          else if (t?.kind === 'normal') dispatch({ type: 'normalConfidence', confidence: c });
          break;
        }
        case 'Backspace': case 'Delete':
          if (sel && !k.result) { e.preventDefault(); dispatch({ type: 'delete', id: sel }); }
          break;
        case 'Escape':
          if (useReference.getState().label) { useReference.getState().close(); break; }
          if (k.read.armed) dispatch({ type: 'disarm' });
          else dispatch({ type: 'select', id: null });
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
  const unvisitedIds = submitResult?.reveal.search.unvisited_review_areas;
  // Zone outlines come from the server only after this attempt is submitted (never before: no ground truth leaks).
  // They draw "Show anatomy" and place the "not visited" rings of the search trace.
  const anatomyQ = useQuery({
    queryKey: ['anatomy', aid],
    queryFn: async () => guardAnatomy(await api.anatomy(aid)),
    enabled: !!submitResult && (anatomyOn || !!unvisitedIds?.length),
    staleTime: Infinity,
    retry: false,
  });
  const toggleAnatomy = useCallback(() => setAnatomyOn((v) => !v), []);
  // Rings are markers at each area's centre: between 2.5% and 8% of the film width.
  const located = useMemo(
    () => unvisitedRings(anatomyQ.data, unvisitedIds ?? [], 0.025 * next.case.width, 0.08 * next.case.width),
    [anatomyQ.data, unvisitedIds, next.case.width],
  );
  const reveal: RevealView | null = submitResult
    ? { findings: submitResult.reveal.findings, marks: submitResult.reveal.marks, arrows: submitResult.reveal.arrows, heatmapUrl, showTrace: showSearch, unvisited: located.rings }
    : null;
  const unvisitedNames = (unvisitedIds ?? []).map((id) => (located.rings.find((r) => r.id === id)?.name ?? zoneDisplay(id)).toLowerCase());

  return (
    <div className={`${shell.room} ${room.root}`} data-testid="reading-room" data-attempt={aid}>
      <div className={shell.viewerCol}>
        {header}
        <div className={shell.viewerWrap}>
          <Viewer
            caseId={next.case.case_id}
            imageUrl={assetUrl(next.case.image_url)}
            width={next.case.width}
            height={next.case.height}
            marks={read.marks}
            selectedId={read.selectedId}
            popoverId={read.popoverId}
            popoverMode={read.popoverMode}
            armed={read.armed}
            dispatch={dispatch}
            canMark={!result && !read.declaredNormal}
            markBlockedReason={read.declaredNormal ? 'You called this film normal. Undo the normal call in the rail to add marks.' : undefined}
            loupe={loupe}
            onToggleLoupe={() => setLoupe(!loupe)}
            projector={projector}
            telemetry={telemetry}
            reveal={reveal}
            onShown={onShown}
            anatomy={{ on: anatomyOn, status: anatomyQ.status, data: anatomyQ.data ?? null }}
            onToggleAnatomy={toggleAnatomy}
            search={submitResult ? { on: showSearch, onToggle: toggleSearch, unvisited: unvisitedNames, located: located.rings.length > 0 && located.missing.length === 0 } : undefined}
          />
        </div>
      </div>
      <aside className={shell.rail} aria-label="Your read and feedback">
        <div className={shell.railBody}>
          <TutorNotice className={rail.tutorNotice} />
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
              <ResultSummary result={submitResult} />
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
      <ReferenceDrawer />
    </div>
  );
}
