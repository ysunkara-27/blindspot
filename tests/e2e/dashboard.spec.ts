// M6 dashboards + test-set summary/feedback e2e (SPEC §10, §15.2 M6/M7). Author: frontend-engineer.
// Round 3: no headline numbers before the fifth film; plain labels with the technical term in a tooltip.
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
  await expect(page.getByTestId('dashboard-n')).toContainText(`n = ${api.n_attempts} films`);
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
  await expect(page.getByTestId('summary-stats-n')).toHaveText(`n = ${api.summary.n} films`);
  // Plain labels; the technical term is one hover away, not in the label.
  const sens = page.getByTestId('stat-sensitivity');
  await expect(sens).toContainText('Abnormal films you caught');
  await expect(sens.locator('abbr')).toHaveAttribute('title', /Sensitivity/);
  await expect(page.getByTestId('stat-specificity')).toContainText('Normal films you correctly called normal');
  await expect(page.getByTestId('stat-specificity').locator('abbr')).toHaveAttribute('title', /Specificity/);
  await expect(page.getByTestId('froc')).toContainText('Marks vs false alarms (FROC)');
  await expect(page.getByTestId('calibration')).toContainText('How well your confidence matched reality');
  // Miss types are labelled rows in one colour, not a legend of shades.
  const bars = page.getByTestId('miss-breakdown');
  if (await bars.count()) {
    for (const t of ['Never looked there', 'Looked past it', 'Looked, judged it normal', 'Found it, named it wrong', "Called something that isn't there"]) await expect(bars).toContainText(t);
  }
  // The blind-spot map says its colour logic in words: cyan = found, amber = missed.
  await expect(page.getByTestId('blindspot-legend')).toContainText(/Cyan dot: found by you/);
  await expect(page.getByTestId('blindspot-legend')).toContainText(/Amber ring: missed/);
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
  await expect(page.getByTestId('dashboard-no-session')).toContainText('Your reading log starts with your first film.');
  await expect(page.getByTestId('early-count')).toHaveText('0 of 5 films');
  const { learnerId } = await seed(request, 0);
  await page.goto(`/progress?learner=${learnerId}`);
  await expect(page.getByTestId('dashboard-empty')).toContainText('Read 5 more to see your first numbers.');
  await page.getByTestId('early-read').click();
  await expect(page).toHaveURL(/\/start$/);
});

test('reading log: fewer than 5 films shows encouragement and no percentages at all', async ({ page, request }) => {
  const { learnerId } = await seed(request, 2);
  await page.goto(`/progress?learner=${learnerId}&mock=0`);
  const few = page.getByTestId('dashboard-few');
  await expect(few).toContainText('Good start: 2 films read.');
  await expect(few).toContainText('Read 3 more to see your first numbers.');
  await expect(page.getByTestId('early-count')).toHaveText('2 of 5 films');
  await expect(page.getByTestId('dashboard-n')).toContainText('n = 2 films');
  // n is too small: no stats, no charts, not a single percentage on the page.
  for (const id of ['learner-dashboard', 'summary-stats', 'learning-curve', 'miss-mix', 'calibration', 'froc']) await expect(page.getByTestId(id)).toHaveCount(0);
  expect(await page.locator('main').innerText()).not.toMatch(/\d\s?%/);
  await page.screenshot({ path: `${SHOTS}/progress-few.png`, fullPage: true });
});

test('reading log: the fifth film turns the numbers on, each with its n', async ({ page, request }) => {
  const { learnerId } = await seed(request, 5);
  await page.goto(`/progress?learner=${learnerId}&mock=0`);
  await expect(page.getByTestId('learner-dashboard')).toBeVisible();
  await expect(page.getByTestId('dashboard-few')).toHaveCount(0);
  await expect(page.getByTestId('summary-stats-n')).toHaveText('n = 5 films');
  await expect(page.getByTestId('stat-sensitivity')).toContainText(/of \d abnormal films?/);
});

test('reading log survives a malformed payload', async ({ page }) => {
  const errors = await noConsoleErrors(page);
  await page.route('**/api/learners/*/dashboard', (r) => r.fulfill({ json: { n_attempts: 9, summary: { n: 'x' }, learning_curve: 'oops', calibration: { bins: [{}] } } }));
  await page.goto('/progress?learner=fake&mock=0');
  await expect(page.getByTestId('learner-dashboard')).toBeVisible();
  await expect(page.getByTestId('summary-stats')).toContainText('No films read yet.');
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
  await expect(page.getByTestId('cohort-n')).toContainText(`n = ${api.n_attempts} films from ${api.n_learners} learners`);
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

test('test-set summary shows n, and the optional feedback form posts a score', async ({ page, request }) => {
  const { sessionId, learnerId } = await seed(request, 25, 'assess_A');
  await page.goto('/?mock=0');
  await page.evaluate(([sid, lid]) => sessionStorage.setItem('blindspot.session', JSON.stringify({
    state: { session: { sessionId: sid, learnerId: lid, displayName: 'E2E dashboard (test)', level: 'other', mode: 'assess_A' }, projector: false }, version: 0,
  })), [sessionId, learnerId]);
  await page.goto('/read');
  await expect(page.getByTestId('assessment-summary')).toBeVisible();
  await expect(page.getByTestId('summary-title')).toHaveText('Test complete');
  await expect(page.getByTestId('summary-stats-n')).toHaveText('n = 20 films');
  await expect(page.getByTestId('summary-miss-mix-n')).toContainText('over 20 films');
  await expect(page.getByTestId('common-miss')).toContainText(/You most often|No misses/);
  // No jargon on the way in: the button says what it does.
  await expect(page.getByTestId('feedback-open')).toHaveText('Give feedback');
  await expect(page.getByTestId('assessment-summary')).not.toContainText(/\bSUS\b|System Usability Scale|survey/i);
  await page.getByTestId('feedback-open').click();
  await expect(page.getByTestId('feedback-submit')).toBeDisabled();
  // All "agree" on positive items (odd) and "disagree" on negative items (even) → 100.
  for (let i = 0; i < 10; i++) await page.getByTestId(`feedback-${i}-${i % 2 === 0 ? 5 : 1}`).check({ force: true });
  const res = page.waitForResponse((r) => r.url().endsWith('/api/sus') && r.request().method() === 'POST');
  await page.getByTestId('feedback-submit').click();
  expect((await res).ok()).toBeTruthy();
  await expect(page.getByTestId('feedback-score')).toHaveText('100.0');
  await page.screenshot({ path: `${SHOTS}/assessment-summary.png`, fullPage: true });
});
