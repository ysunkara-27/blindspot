// M6 dashboards + assessment summary/SUS e2e (SPEC §10, §15.2 M6/M7). Author: frontend-engineer.
// Runs against the REAL API (BLINDSPOT_OFFLINE=1). Seeds its own attempts through the API as a learner named
// "E2E dashboard (test)" — test data, never demo data (`make db-reset` clears it). Dashboard shots show no films.
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const API = process.env.E2E_API ?? 'http://127.0.0.1:8000/api';
const SHOTS = `${process.cwd().endsWith('frontend') ? '../' : ''}tests/e2e/__screenshots__`;

test.use({ viewport: { width: 1280, height: 800 } });

function telemetry(w: number, h: number, focus: [number, number] | null) {
  const ev: Record<string, unknown>[] = [];
  let t = 0;
  for (let row = 1; row < 6; row++) {
    for (let k = 0; k < 30; k++) {
      ev.push({ t, kind: 'move', x: w * (0.1 + (0.8 * k) / 29), y: (h * row) / 6, zoom: 1, vp: [0, 0, w, h], loupe: true });
      t += 33;
    }
  }
  if (focus) for (let k = 0; k < 36; k++) { ev.push({ t, kind: 'move', x: focus[0] + (k % 2 ? 2 : -2), y: focus[1], zoom: 2, vp: [0, 0, w, h], loupe: true }); t += 33; }
  ev.push({ t, kind: 'leave', x: null, y: null, zoom: 1, vp: [0, 0, w, h], loupe: true });
  return ev;
}

/** Create a session and submit `n` reads with varied marks and confidence. Returns ids. */
async function seed(request: APIRequestContext, n: number, mode = 'practice') {
  const s = await (await request.post(`${API}/sessions`, { data: { display_name: 'E2E dashboard (test)', level: 'MS3', mode } })).json();
  for (let i = 0; i < n; i++) {
    const next = await (await request.get(`${API}/sessions/${s.session_id}/next`)).json();
    if (next.done) break;
    const { width: w, height: h } = next.case;
    const pos: [number, number] = [w * (0.25 + 0.5 * ((i * 37) % 10) / 10), h * (0.3 + 0.4 * ((i * 53) % 10) / 10)];
    const marks = i % 3 === 2 ? [] : [{ mark_id: 'M1', x: pos[0], y: pos[1], label: i % 2 ? 'effusion' : 'consolidation', confidence: (i % 5) + 1 }];
    const res = await request.post(`${API}/attempts/${next.attempt_id}/submit`, {
      data: {
        marks, patterns: [], declared_normal: marks.length === 0, normal_confidence: marks.length ? null : 3,
        telemetry: telemetry(w, h, marks.length ? pos : null), hints_used: 0,
        client_timing: { shown_at: new Date(Date.now() - 20_000).toISOString(), submitted_at: new Date().toISOString() },
      },
    });
    expect(res.ok()).toBeTruthy();
  }
  return { sessionId: s.session_id as string, learnerId: s.learner_id as string };
}

async function noConsoleErrors(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  return errors;
}

test('reading log renders real attempts with n on every section', async ({ page, request }) => {
  const errors = await noConsoleErrors(page);
  const { learnerId } = await seed(request, 7);
  const api = await (await request.get(`${API}/learners/${learnerId}/dashboard`)).json();

  await page.goto(`/progress?learner=${learnerId}&mock=0`);
  await expect(page.getByTestId('learner-dashboard')).toBeVisible();
  await expect(page.getByTestId('dashboard-n')).toContainText(`n = ${api.n_attempts} cases`);
  for (const id of ['summary-stats', 'learning-curve', 'miss-mix', 'blindspot-map', 'review-areas', 'calibration', 'froc']) {
    await expect(page.getByTestId(id)).toBeVisible();
    await expect(page.getByTestId(`${id}-n`)).toContainText('n = ');
  }
  // Learning curve: 7 cases ≥ 5, so a chart (not the empty state); per-label toggle works.
  await expect(page.getByTestId('curve-empty')).toHaveCount(0);
  await expect(page.getByTestId('learning-curve').locator('svg.recharts-surface')).toBeVisible();
  const opts = await page.getByTestId('curve-series').locator('option').count();
  expect(opts).toBeGreaterThan(1);
  await page.getByTestId('curve-series').selectOption({ index: 1 });
  await expect(page.getByTestId('learning-curve')).toContainText('averaged over the last');
  // Numbers agree with the API.
  await expect(page.getByTestId('summary-stats-n')).toHaveText(`n = ${api.summary.n} cases`);
  await expect(page.getByTestId('blindspot-map-n')).toHaveText(`n = ${api.blindspot_map.n} findings · ${api.blindspot_map.n_missed} missed`);
  await expect(page.getByTestId('bs-missed')).toHaveCount(api.blindspot_map.n_missed);
  await expect(page.getByTestId('confident-misses')).toHaveText(String(api.calibration.confident_misses));
  // Table twins open.
  await page.getByTestId('calibration').getByText('Show as table').click();
  await expect(page.getByTestId('calibration').locator('table')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/progress.png`, fullPage: true });
  expect(errors).toEqual([]);
});

test('reading log empty states: no session, and a learner with no reads', async ({ page, request }) => {
  await page.goto('/progress?mock=0');
  await expect(page.getByTestId('dashboard-no-session')).toContainText('Read 5 cases to see your first learning curve.');
  const { learnerId } = await seed(request, 0);
  await page.goto(`/progress?learner=${learnerId}`);
  await expect(page.getByTestId('dashboard-empty')).toContainText('Read 5 cases to see your first learning curve.');
});

test('reading log: fewer than 5 cases shows stats but not the curve', async ({ page, request }) => {
  const { learnerId } = await seed(request, 2);
  await page.goto(`/progress?learner=${learnerId}`);
  await expect(page.getByTestId('curve-empty')).toHaveText('Read 5 cases to see your first learning curve.');
  await expect(page.getByTestId('summary-stats-n')).toHaveText('n = 2 cases');
});

test('reading log survives a malformed payload', async ({ page }) => {
  const errors = await noConsoleErrors(page);
  await page.route('**/api/learners/*/dashboard', (r) => r.fulfill({ json: { n_attempts: 9, summary: { n: 'x' }, learning_curve: 'oops', calibration: { bins: [{}] } } }));
  await page.goto('/progress?learner=fake&mock=0');
  await expect(page.getByTestId('learner-dashboard')).toBeVisible();
  await expect(page.getByTestId('summary-stats')).toContainText('No cases read yet.');
  await expect(page.getByTestId('curve-empty')).toBeVisible();
  await expect(page.getByTestId('calibration')).toContainText('No confidence-rated calls yet.');
  expect(errors).toEqual([]);
});

test('cohort dashboard: aggregates, difficulty table, filters as query params', async ({ page, request }) => {
  await seed(request, 3);
  // Compare with the exact payload the page received (other specs may add attempts in between).
  const resp = page.waitForResponse((r) => r.url().includes('/api/cohort/dashboard'));
  await page.goto('/cohort?mock=0');
  const api = await (await resp).json();
  await expect(page.getByTestId('cohort-dashboard')).toBeVisible();
  await expect(page.getByTestId('cohort-n')).toContainText(`n = ${api.n_attempts} cases from ${api.n_learners} learners`);
  for (const id of ['summary-stats', 'miss-mix', 'label-difficulty', 'blindspot-map', 'review-areas', 'calibration', 'froc', 'cohort-learners']) {
    await expect(page.getByTestId(`${id}-n`)).toContainText('n = ');
  }
  await expect(page.getByTestId('label-difficulty').locator('tbody tr')).toHaveCount(api.label_difficulty.length);
  await page.screenshot({ path: `${SHOTS}/cohort.png`, fullPage: true });

  const req = page.waitForRequest((r) => r.url().includes('/api/cohort/dashboard') && r.url().includes('mode=practice') && r.url().includes('level=MS3'));
  await page.getByTestId('filter-mode').selectOption('practice');
  await page.getByTestId('filter-level').selectOption('MS3');
  await req;
  await expect(page).toHaveURL(/mode=practice/);
  await expect(page.getByTestId('cohort-n')).toContainText('(filtered)');
  await expect(page.getByTestId('filter-mode')).toHaveValue('practice');
  await expect(page.getByTestId('filter-level')).toHaveValue('MS3');
  // A date range in the far past matches nothing.
  await page.getByTestId('filter-to').fill('2000-01-01');
  await expect(page.getByTestId('cohort-empty')).toBeVisible();
});

test('assessment summary shows n and the SUS survey posts a score', async ({ page, request }) => {
  const { sessionId, learnerId } = await seed(request, 25, 'assess_A');
  await page.goto('/?mock=0');
  await page.evaluate(([sid, lid]) => sessionStorage.setItem('blindspot.session', JSON.stringify({
    state: { session: { sessionId: sid, learnerId: lid, displayName: 'E2E dashboard (test)', level: 'MS3', mode: 'assess_A' }, projector: false }, version: 0,
  })), [sessionId, learnerId]);
  await page.goto('/read');
  await expect(page.getByTestId('assessment-summary')).toBeVisible();
  await expect(page.getByTestId('summary-stats-n')).toHaveText('n = 20 cases');
  await expect(page.getByTestId('summary-miss-mix-n')).toContainText('over 20 cases');
  await page.getByTestId('sus-open').click();
  await expect(page.getByTestId('sus-submit')).toBeDisabled();
  // All "agree" on positive items (odd) and "disagree" on negative items (even) → 100.
  for (let i = 0; i < 10; i++) await page.getByTestId(`sus-${i}-${i % 2 === 0 ? 5 : 1}`).check({ force: true });
  const res = page.waitForResponse((r) => r.url().endsWith('/api/sus') && r.request().method() === 'POST');
  await page.getByTestId('sus-submit').click();
  expect((await res).ok()).toBeTruthy();
  await expect(page.getByTestId('sus-score')).toHaveText('100.0');
  await page.screenshot({ path: `${SHOTS}/assessment-summary.png`, fullPage: true });
});
