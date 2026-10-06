import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { lazy, Suspense, useState, type ReactNode } from 'react';
import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom';
import { BASE, isGateError } from '../api/client';
import { routerBasename } from '../api/base';
import { OnboardingPage } from '../pages/OnboardingPage';
import { StartPage } from '../pages/StartPage';
// The end-of-set summary is already in the main chunk (the reading room shows it), so its URL route is not lazy.
import { SetSummaryPage } from '../pages/SessionSummaryView';
import { ReadPage } from '../pages/ReadPage';
import { AboutPage } from '../pages/AboutPage';
import { DevCasePage } from '../pages/DevCasePage';
import { NotFoundPage } from '../pages/NotFoundPage';
import { AccessGate } from './Gate';
import { SmallScreenNote } from './SmallScreen';
import { useNarrow } from './useMediaQuery';
import { PageShell } from './Shell';

// Dashboards and review pull in Recharts; load them on demand so the reading room starts fast (SPEC §17 cold start).
const ProgressPage = lazy(() => import('../pages/ProgressPage').then((m) => ({ default: m.ProgressPage })));
const CohortPage = lazy(() => import('../pages/CohortPage').then((m) => ({ default: m.CohortPage })));
const ReviewPage = lazy(() => import('../pages/ReviewPage').then((m) => ({ default: m.ReviewPage })));
const ReferencePage = lazy(() => import('../pages/ReferencePage').then((m) => ({ default: m.ReferencePage })));
const CaseReviewPage = lazy(() => import('../pages/CaseReviewPage').then((m) => ({ default: m.CaseReviewPage })));

// A 401 asking for a code is not worth retrying: the gate takes over instead.
const qc = new QueryClient({
  defaultOptions: { queries: { retry: (n, e) => !isGateError(e) && n < 1, refetchOnWindowFocus: false } },
});

// Pages that still make sense on a phone: the landing (it explains, then asks for a computer), the About report and
// the finding library (text first; its example films scale down).
const NARROW_OK = new Set(['/', '/about', '/reference']);

// A page that was already open stays mounted (hidden, inert) when the window narrows, so shrinking a window or a
// transient resize never throws away marks, a half-written review or the card being edited. A page opened narrow
// never mounts.
function NarrowGuard({ children }: { children: ReactNode }) {
  const narrow = useNarrow();
  const { pathname } = useLocation();
  const blocked = narrow && !NARROW_OK.has(pathname.replace(/\/+$/, '') || '/');
  const [mounted, setMounted] = useState(!blocked);
  if (!blocked && !mounted) setMounted(true);
  // The wrapper is always there (display: contents when wide) so the page keeps its place in the tree.
  return (
    <>
      {blocked && <SmallScreenNote />}
      <div style={{ display: blocked ? 'none' : 'contents' }} inert={blocked} data-testid="page-root">
        {(mounted || !blocked) && children}
      </div>
    </>
  );
}

export function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter basename={routerBasename(BASE)}>
        <AccessGate>
          <NarrowGuard>
            {/* The fallback is the paper shell, so the disclaimer footer shows even while a page chunk loads. */}
            <Suspense fallback={<PageShell><span /></PageShell>}>
              <Routes>
                <Route path="/" element={<OnboardingPage />} />
                <Route path="/start" element={<StartPage />} />
                <Route path="/read" element={<ReadPage />} />
                <Route path="/set/:sessionId" element={<SetSummaryPage />} />
                <Route path="/review-case/:attemptId" element={<CaseReviewPage />} />
                <Route path="/reference" element={<ReferencePage />} />
                <Route path="/progress" element={<ProgressPage />} />
                <Route path="/cohort" element={<CohortPage />} />
                <Route path="/review" element={<ReviewPage />} />
                <Route path="/about" element={<AboutPage />} />
                <Route path="/dev/case/:id" element={<DevCasePage />} />
                <Route path="*" element={<NotFoundPage />} />
              </Routes>
            </Suspense>
          </NarrowGuard>
        </AccessGate>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
