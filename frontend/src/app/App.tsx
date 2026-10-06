import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { lazy, Suspense, type ReactNode } from 'react';
import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom';
import { BASE, isGateError } from '../api/client';
import { routerBasename } from '../api/base';
import { OnboardingPage } from '../pages/OnboardingPage';
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

// A 401 asking for a code is not worth retrying: the gate takes over instead.
const qc = new QueryClient({
  defaultOptions: { queries: { retry: (n, e) => !isGateError(e) && n < 1, refetchOnWindowFocus: false } },
});

// Pages that still make sense on a phone: the landing (it explains, then asks for a computer) and the About report.
const NARROW_OK = new Set(['/', '/about']);

function NarrowGuard({ children }: { children: ReactNode }) {
  const narrow = useNarrow();
  const { pathname } = useLocation();
  if (narrow && !NARROW_OK.has(pathname.replace(/\/+$/, '') || '/')) return <SmallScreenNote />;
  return <>{children}</>;
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
                <Route path="/read" element={<ReadPage />} />
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
