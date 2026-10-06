// Tutor status banner and per-debrief tutor lines. Author: frontend-engineer (qa-reviewer owns this directory).
// Always the real API (?mock=0): /api/health is mocked per mode with page.route (page.route only sees real network
// calls), everything else reaches the throwaway API. Also checks that nothing analytics-shaped leaves an automated
// browser (navigator.webdriver is set under Playwright).
import { expect, test, type Page, type Route } from '@playwright/test';

const SHOTS = 'tests/e2e/__screenshots__';
const shot = (page: Page, name: string) =>
  page.screenshot({ path: `${process.cwd().endsWith('frontend') ? '../' : ''}${SHOTS}/live-tutor-${name}.png` });

test.use({ viewport: { width: 1280, height: 800 } });

const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

type Tutor = { mode: string; reason?: string | null; resume_at?: string | null; spend_usd?: Record<string, number> | null };

/** Serve /api/health with the given tutor block; everything else passes through to the real API. */
async function mockHealth(page: Page, tutor: Tutor | null, extra: Record<string, unknown> = {}) {
  await page.route((url) => url.pathname.endsWith('/api/health'), (route) =>
    json(route, 200, { ok: true, offline: tutor?.mode !== 'live', cases: 3000, version: 'e2e', tutor, ...extra }));
}

async function filmReady(page: Page) {
  await expect(page.getByTestId('film')).toBeVisible();
  await page.waitForFunction(() => {
    const img = document.querySelector<HTMLImageElement>('[data-testid=film]');
    return !!img && img.complete && img.naturalWidth > 0;
  });
}

async function startPractice(page: Page) {
  await page.goto('/start?mock=0');
  await page.getByTestId('name').fill('E2E tutor status (test)');
  await page.getByTestId('start').click();
  await filmReady(page);
}

async function submitNormal(page: Page) {
  await page.mouse.move(2, 400);
  await page.keyboard.press('n');
  await page.keyboard.press('3');
  await page.getByTestId('submit').click();
  await expect(page.getByTestId('outcomes')).toBeVisible();
}

const MODES: { mode: string; text: string; resume_at?: string }[] = [
  { mode: 'offline', text: 'The AI tutor is off. You still get the built-in explanation after every film.' },
  { mode: 'paused_credits', text: 'The AI tutor is paused (account credits ran out). Built-in explanations continue.' },
  { mode: 'paused_budget', text: 'The AI tutor has reached its spending limit for now. Built-in explanations continue.' },
  { mode: 'paused_rate', text: 'The AI tutor is busy; trying again shortly.' },
  { mode: 'paused_error', text: 'The AI tutor is unavailable right now. Built-in explanations continue.' },
];

for (const m of MODES) {
  test(`start page banner: ${m.mode}`, async ({ page }) => {
    await mockHealth(page, { mode: m.mode, reason: 'e2e' });
    await page.goto('/start?mock=0');
    const notice = page.getByTestId('tutor-notice');
    await expect(notice).toHaveText(m.text);
    await expect(notice).toHaveAttribute('data-mode', m.mode);
    // Not a reviewer: no spend line, and the raw mode never shows as text.
    await expect(page.getByTestId('tutor-spend')).toHaveCount(0);
    await expect(notice).not.toContainText(m.mode);
    // The start button is still usable: the banner blocks nothing.
    await expect(page.getByTestId('start')).toBeEnabled();
    if (m.mode === 'paused_credits') await shot(page, 'start-paused-credits');
  });
}

test('live: no banner anywhere; the library line stays', async ({ page }) => {
  await mockHealth(page, { mode: 'live' });
  await page.goto('/start?mock=0');
  await expect(page.getByTestId('health')).toContainText('Library: 3,000 chest films');
  await expect(page.getByTestId('tutor-notice')).toHaveCount(0);
  await page.getByTestId('name').fill('E2E tutor live (test)');
  await page.getByTestId('start').click();
  await filmReady(page);
  await expect(page.getByTestId('tutor-notice')).toHaveCount(0);
});

test('a health without a tutor block falls back to the offline flag', async ({ page }) => {
  await mockHealth(page, null, { offline: true });
  await page.goto('/start?mock=0');
  await expect(page.getByTestId('tutor-notice')).toHaveText('The AI tutor is off. You still get the built-in explanation after every film.');
});

test('paused_budget says when it is back, in local time', async ({ page }) => {
  const resume = new Date(Date.now() + 90 * 60_000);
  await mockHealth(page, { mode: 'paused_budget', resume_at: resume.toISOString() });
  await page.goto('/start?mock=0');
  const expected = await page.evaluate((iso) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }), resume.toISOString());
  await expect(page.getByTestId('tutor-notice')).toHaveText(
    `The AI tutor has reached its spending limit for now. Built-in explanations continue. Back around ${expected}.`,
  );
});

test('reading room: the banner sits at the top of the rail, before and after submit; reviewers see the spend', async ({ page }) => {
  await mockHealth(page, { mode: 'paused_budget', reason: 'day budget', spend_usd: { hour: 0.12, day: 1.5, total: 9.87 }, budget_usd: { day: 1.5 } });
  await page.route((url) => url.pathname.endsWith('/api/access') && !url.pathname.includes('review'), (route) =>
    route.request().method() === 'GET'
      ? json(route, 200, { access_required: false, access_granted: true, review_required: true, review_granted: true, base_path: '' })
      : route.fallback());
  await startPractice(page);
  const rail = page.getByRole('complementary', { name: 'Your read and feedback' });
  const notice = rail.getByTestId('tutor-notice');
  await expect(notice).toContainText('The AI tutor has reached its spending limit for now. Built-in explanations continue.');
  await expect(notice.getByTestId('tutor-spend')).toHaveText('Spend today $1.50');
  // Above "Your read": the first thing in the rail body.
  const order = await rail.evaluate((el) => {
    const n = el.querySelector('[data-testid=tutor-notice]')!;
    const h = el.querySelector('h2')!;
    return n.compareDocumentPosition(h) & Node.DOCUMENT_POSITION_FOLLOWING ? 'notice-first' : 'heading-first';
  });
  expect(order).toBe('notice-first');
  await shot(page, 'reading-room-paused-budget');
  await submitNormal(page);
  await expect(rail.getByTestId('tutor-notice')).toBeVisible();
  await expect(rail.getByRole('heading', { name: 'The expert read' })).toBeVisible();
});

test('reading room: no spend line without the review cookie', async ({ page }) => {
  await mockHealth(page, { mode: 'paused_error', spend_usd: { day: 2 } });
  await startPractice(page);
  await expect(page.getByTestId('tutor-notice')).toHaveText('The AI tutor is unavailable right now. Built-in explanations continue.');
  await expect(page.getByTestId('tutor-spend')).toHaveCount(0);
});

const DEBRIEF = {
  headline: 'You called this film normal.', verdict: 'correct_normal', findings: [], overcalls: [],
  search_coaching: 'Check both apices before you call a film normal.', calibration_note: '', next_step: 'Keep reading.', fact_ids: [],
};

const DEBRIEF_LINES: [string, string][] = [
  ['credits_depleted', 'The AI tutor is paused (account credits ran out). Showing the built-in explanation instead.'],
  ['budget_exceeded', 'The AI tutor has reached its spending limit for now. Showing the built-in explanation instead.'],
  ['offline', 'The AI tutor is off. Showing the built-in explanation instead.'],
  ['timeout', 'The AI tutor took too long. Showing the built-in explanation instead.'],
  ['auth', 'The AI tutor could not sign in to its service. Showing the built-in explanation instead.'],
  ['validator_failed', "The AI tutor's draft did not pass our checks. Showing the built-in explanation instead."],
];

for (const [code, line] of DEBRIEF_LINES) {
  test(`debrief line: ${code}`, async ({ page }) => {
    let healthCalls = 0;
    await page.route((url) => url.pathname.endsWith('/api/health'), (route) => {
      healthCalls += 1;
      return json(route, 200, { ok: true, offline: false, cases: 3000, tutor: { mode: 'live' } });
    });
    await page.route('**/api/attempts/*/debrief', (route) =>
      json(route, 200, { status: 'ready', source: 'template', provenance: 'ai_draft', error: code, debrief: DEBRIEF }));
    await startPractice(page);
    const before = healthCalls;
    await submitNormal(page);
    const panel = page.getByTestId('debrief');
    await expect(panel.getByTestId('debrief-busy')).toHaveText(line);
    await expect(panel.getByTestId('debrief-source')).toHaveText('Built-in');
    await expect(panel).toContainText('Check both apices');
    await expect(panel).not.toContainText(code);
    // A debrief that ended in a tutor problem re-checks the tutor status right away.
    await expect.poll(() => healthCalls).toBeGreaterThan(before);
    if (code === 'credits_depleted') {
      await page.waitForTimeout(1400); // let the reveal settle so the rail is in the shot
      await panel.scrollIntoViewIfNeeded();
      await shot(page, 'debrief-credits-depleted');
    }
  });
}

test('an unknown error code never reaches the screen', async ({ page }) => {
  await page.route('**/api/attempts/*/debrief', (route) =>
    json(route, 200, { status: 'ready', source: 'template', provenance: 'ai_draft', error: 'SomeNewInternalCode', debrief: DEBRIEF }));
  await startPractice(page);
  await submitNormal(page);
  const panel = page.getByTestId('debrief');
  await expect(panel.getByTestId('debrief-busy')).toHaveText('The AI tutor is unavailable right now. Showing the built-in explanation instead.');
  await expect(panel).not.toContainText('SomeNewInternalCode');
});

test('analytics: nothing leaves an automated browser, and About says what is counted', async ({ page }) => {
  const hits: string[] = [];
  page.on('request', (r) => { if (r.url().includes('/analytics/')) hits.push(r.url()); });
  await startPractice(page);
  await page.goto('/about?mock=0');
  await expect(page.getByTestId('about-analytics')).toHaveText('We count page views and clicks with an anonymous browser id. No names, marks or answers are sent.');
  expect(hits).toEqual([]);
  expect(await page.evaluate(() => localStorage.getItem('ys-analytics-id'))).toBeNull();
});
