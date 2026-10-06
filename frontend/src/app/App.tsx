import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { OnboardingPage } from '../pages/OnboardingPage';
import { ReadPage } from '../pages/ReadPage';
import { ProgressPage } from '../pages/ProgressPage';
import { CohortPage } from '../pages/CohortPage';
import { ReviewPage } from '../pages/ReviewPage';
import { AboutPage } from '../pages/AboutPage';
import { DevCasePage } from '../pages/DevCasePage';

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

export function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<OnboardingPage />} />
          <Route path="/read" element={<ReadPage />} />
          <Route path="/progress" element={<ProgressPage />} />
          <Route path="/cohort" element={<CohortPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/dev/case/:id" element={<DevCasePage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
