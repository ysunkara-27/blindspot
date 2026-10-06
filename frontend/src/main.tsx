import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import { App } from './app/App';

if (new URLSearchParams(location.search).get('projector') === '1') {
  document.documentElement.dataset.projector = '1';
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
