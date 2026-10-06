import { defineConfig, devices } from '@playwright/test';

// The DB is created before uvicorn starts: concurrent first connections on a fresh file can hit
// 'database is locked' at PRAGMA journal_mode=WAL (backend/app/db.py).
// Same specs as ../tests/e2e/playwright.config.ts, on an isolated stack so a run never touches a dev API that may be
// live (real Anthropic calls) or its database: an OFFLINE API on :8011 with a throwaway DB, and Vite on :5181.
// Run from frontend/: E2E_REAL=1 npx playwright test --config playwright.local.config.ts
// Hosting env from the repo .env (access/review codes, base path) is blanked; pass extras through E2E_API_ENV="A=1 B=2".
const API = 8011;
const WEB = 5181;
// Specs that seed through the API directly read these (default :8000 / :5173).
process.env.E2E_API = `http://127.0.0.1:${API}/api`;
process.env.E2E_WEB = `http://127.0.0.1:${WEB}`;
export default defineConfig({
  testDir: '../tests/e2e',
  testMatch: /.*\.spec\.ts/,
  timeout: 60_000,
  retries: 0,
  outputDir: '../tests/e2e/test-results',
  snapshotDir: '../tests/e2e/__screenshots__',
  use: { ...devices['Desktop Chrome'], baseURL: `http://127.0.0.1:${WEB}`, viewport: { width: 1280, height: 800 } },
  webServer: [
    {
      command: `cd .. && rm -f ./data/e2e-local.sqlite ./data/e2e-local.sqlite-wal ./data/e2e-local.sqlite-shm && BLINDSPOT_ACCESS_CODE= BLINDSPOT_REVIEW_CODE= BLINDSPOT_BASE_PATH= BLINDSPOT_SERVE_FRONTEND=0 ${process.env.E2E_API_ENV ?? ''} BLINDSPOT_OFFLINE=1 ANTHROPIC_API_KEY= BLINDSPOT_DB_PATH=./data/e2e-local.sqlite sh -c 'uv run python -c "from backend.app.db import connect; connect().close()" && exec uv run python -m uvicorn backend.app.main:app --host 127.0.0.1 --port ${API}'`,
      url: `http://127.0.0.1:${API}/api/health`,
      reuseExistingServer: false,
      timeout: 90_000,
    },
    {
      command: `VITE_API_PROXY=http://127.0.0.1:${API} npx vite --host 127.0.0.1 --port ${WEB} --strictPort`,
      url: `http://127.0.0.1:${WEB}`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
