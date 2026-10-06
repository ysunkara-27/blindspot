import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { lazy, Suspense } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { OnboardingPage } from '../pages/OnboardingPage';
import { ReadPage } from '../pages/ReadPage';
import { AboutPage } from '../pages/AboutPage';
import { DevCasePage } from '../pages/DevCasePage';
import { NotFoundPage } from '../pages/NotFoundPage';
import { PageShell } from './Shell';

// Dashboards and review pull in Recharts; load them on demand so the reading room starts fast (SPEC §17 cold start).
const ProgressPage = lazy(() => import('../pages/ProgressPage').then((m) => ({ default: m.ProgressPage })));
const CohortPage = lazy(() => import('../pages/CohortPage').then((m) => ({ default: m.CohortPage })));
const ReviewPage = lazy(() => import('../pages/ReviewPage').then((m) => ({ default: m.ReviewPage })));

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

export function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
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
      </BrowserRouter>
    </QueryClientProvider>
  );
}
