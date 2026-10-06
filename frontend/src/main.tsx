import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import { App } from './app/App';
import { initApiMode } from './api/client';

if (new URLSearchParams(location.search).get('projector') === '1') {
  document.documentElement.dataset.projector = '1';
}

// Decide real API vs synthetic mock before the first request (never throws).
initApiMode().finally(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
