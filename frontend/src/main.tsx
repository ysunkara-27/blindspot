import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import { App } from './app/App';
import { initApiMode } from './api/client';
import { initAnalytics } from './analytics';

if (new URLSearchParams(location.search).get('projector') === '1') {
  document.documentElement.dataset.projector = '1';
}

// Anonymous page-view and click counts (off on localhost and under automation; see analytics.ts).
initAnalytics();

// Decide real API vs synthetic mock before the first request (never throws).
initApiMode().finally(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
