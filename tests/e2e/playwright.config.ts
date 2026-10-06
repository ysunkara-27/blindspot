import { defineConfig, devices } from '@playwright/test';

// Run from frontend/: npx playwright test --config ../tests/e2e/playwright.config.ts
export default defineConfig({
  testDir: '.',
  testMatch: /.*\.spec\.ts/,
  timeout: 60_000,
  retries: 0,
  outputDir: './test-results',
  snapshotDir: './__screenshots__',
  use: { baseURL: 'http://127.0.0.1:5173', viewport: { width: 1280, height: 800 }, ...devices['Desktop Chrome'] },
  webServer: [
    {
      command: 'cd .. && BLINDSPOT_OFFLINE=1 uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8000',
      url: 'http://127.0.0.1:8000/api/health',
      reuseExistingServer: true,
      timeout: 60_000,
    },
    { command: 'npm run dev -- --host 127.0.0.1 --port 5173', url: 'http://127.0.0.1:5173', reuseExistingServer: true, timeout: 60_000 },
  ],
});
