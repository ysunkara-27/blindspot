// General-use / hosting e2e. Author: frontend-engineer (qa-reviewer owns this directory).
// Landing, "Try the demo", the access and reviewer gates (401s mocked with page.route), the small-screen note,
// the key help overlay, empty-state nudges, debrief source/provenance tags and "Show anatomy".
// Gate and debrief-tag tests always use the real API (?mock=0): the webServer starts one, and page.route can only
// intercept real network calls. E2E_REAL=1 also runs the reading-room checks on real films (shots named live-*.png).
import { expect, test, type Page, type Route } from '@playwright/test';

const REAL = process.env.E2E_REAL === '1';
const ROOT = REAL ? '/?mock=0' : '/?mock=1';
const SHOTS = 'tests/e2e/__screenshots__';
const shot = (page: Page, name: string, films = false) =>
  page.screenshot({ path: `${process.cwd().endsWith('frontend') ? '../' : ''}${SHOTS}/${films && REAL ? 'live-' : ''}general-${name}.png` });

test.use({ viewport: { width: 1280, height: 800 } });

async function filmReady(page: Page) {
  await expect(page.getByTestId('film')).toBeVisible();
  await page.waitForFunction(() => {
    const img = document.querySelector<HTMLImageElement>('[data-testid=film]');
    return !!img && img.complete && img.naturalWidth > 0;
  });
}

async function startPractice(page: Page, root = ROOT) {
  await page.goto(root);
  await page.getByTestId('name').fill('E2E general (test)');
  await page.getByLabel(/^Practice/).check();
  await page.getByTestId('start').click();
  await filmReady(page);
}

/** Submit by calling the film normal: needs no knowledge of the case. */
async function submitNormal(page: Page) {
  await page.mouse.move(2, 400);
  await page.keyboard.press('n');
  const conf = page.getByRole('radio', { name: /Confidence 3 of 5/ }).first();
  if (await conf.isVisible().catch(() => false)) await conf.click();
  await page.getByTestId('submit').click();
  await expect(page.getByTestId('outcomes')).toBeVisible();
}

const json = (route: Route, status: number, body: unknown) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

test('landing explains Blindspot and offers the demo, the form and the links', async ({ page }) => {
  await page.goto(ROOT);
  await expect(page).toHaveTitle(/Blindspot/);
  await expect(page.getByRole('heading', { level: 1, name: 'Blindspot' })).toBeVisible();
  await expect(page.getByTestId('three-lines')).toContainText("Mark what you see. We'll show you how you looked.");
  await expect(page.getByTestId('three-lines')).toContainText('a proxy for where you looked');
  await expect(page.getByTestId('try-demo')).toHaveText('Try the demo');
  for (const id of ['mode-practice', 'mode-drill', 'mode-assessment']) await expect(page.getByTestId(id)).toBeVisible();
  await expect(page.getByTestId('drill-label')).toBeVisible();
  await expect(page.getByLabel(/^Assessment A/)).toBeVisible();
  await expect(page.getByLabel(/^Assessment B/)).toBeVisible();
  const how = page.getByTestId('how-it-works');
  for (const t of ['radiologists outlined', 'cursor', 'Kundel', 'validator', 'not eye tracking']) await expect(how).toContainText(t);
  const links = page.getByTestId('landing-links');
  for (const t of ['Reading log', 'About', 'Instructor (cohort)', 'Expert review']) await expect(links.getByRole('link', { name: t })).toBeVisible();
  await expect(page.getByTestId('disclaimer')).toContainText('For education. Not for clinical use.');
  // Three mode columns side by side on a laptop.
  const p = (await page.getByTestId('mode-practice').boundingBox())!;
  const d = (await page.getByTestId('mode-drill').boundingBox())!;
  expect(Math.abs(p.y - d.y)).toBeLessThan(2);
  // Picking a drill finding selects Drill.
  await page.getByTestId('drill-label').selectOption('nodule');
  await expect(page.getByRole('radio', { name: 'Drill' })).toBeChecked();
  await page.getByLabel(/^Practice/).check();
  await shot(page, '01-landing');
  await page.screenshot({ path: `${process.cwd().endsWith('frontend') ? '../' : ''}${SHOTS}/general-01-landing-full.png`, fullPage: true });
});

test('"Try the demo" starts a Practice session as Demo and lands on case 1', async ({ page }) => {
  const created: unknown[] = [];
  page.on('request', (r) => { if (r.url().endsWith('/api/sessions') && r.method() === 'POST') created.push(r.postDataJSON()); });
  await page.goto(ROOT);
  await page.getByTestId('try-demo').click();
  await expect(page).toHaveURL(/\/read$/);
  await filmReady(page);
  await expect(page.getByTestId('case-index')).toHaveText(/^Case 1\b/);
  await expect(page.getByTestId('mode')).toHaveText('Practice');
  await expect(page).toHaveTitle('Case 1 · Reading room · Blindspot');
  if (REAL) expect(created).toEqual([expect.objectContaining({ display_name: 'Demo', mode: 'practice', participant_code: null })]);
  await shot(page, '02-demo-case1', true);
});

test('access gate: a 401 shows one calm page; a wrong code says so; the right code unlocks and retries', async ({ page }) => {
  let unlocked = false;
  const posted: string[] = [];
  // Match API paths only: a glob like **/api/** would also catch Vite's /src/api/*.ts modules in dev.
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (path.endsWith('/api/access') && req.method() === 'POST') {
      const code = (req.postDataJSON() as { code: string }).code;
      posted.push(code);
      if (code === 'open-sesame') { unlocked = true; return json(route, 200, { ok: true, required: true }); }
      return json(route, 401, { error: 'invalid_code' });
    }
    if (!unlocked && !path.endsWith('/api/about')) return json(route, 401, { error: 'access_code_required' });
    return route.fallback();
  });
  await page.goto('/?mock=0');
  const gate = page.getByTestId('access-gate');
  await expect(gate).toBeVisible();
  await expect(gate).toContainText('Blindspot is a private preview.');
  await expect(gate).toContainText('Enter the access code.');
  await expect(page).toHaveTitle('Private preview · Blindspot');
  await expect(page.getByTestId('disclaimer')).toBeVisible();
  await expect(page.getByTestId('try-demo')).toHaveCount(0);
  await shot(page, '03-access-gate');

  await page.getByTestId('access-code').fill('wrong');
  await page.getByTestId('access-submit').click();
  await expect(page.getByTestId('access-error')).toHaveText('That code did not work. Check it and try again.');
  await page.getByTestId('access-code').fill('open-sesame');
  await page.getByTestId('access-submit').click();
  await expect(gate).toHaveCount(0);
  await expect(page.getByTestId('try-demo')).toBeVisible();
  // The failed health query is retried after unlocking.
  await expect(page.getByTestId('health')).toContainText('Server: ok', { timeout: 15_000 });
  expect(posted).toEqual(['wrong', 'open-sesame']);
  // The code is never kept client-side (the server's httpOnly cookie carries the grant).
  const stored = await page.evaluate(() => JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }) + document.cookie);
  expect(stored).not.toContain('open-sesame');
});

test('access gate also appears when a later call is refused, and About stays public', async ({ page }) => {
  let gated = false;
  await page.route('**/api/sessions', (route) => (gated ? json(route, 401, { error: 'access_code_required' }) : route.fallback()));
  await page.goto('/?mock=0');
  await expect(page.getByTestId('health')).toContainText('Server: ok', { timeout: 15_000 });
  gated = true;
  await page.getByTestId('try-demo').click();
  await expect(page.getByTestId('access-gate')).toBeVisible();
  await page.getByTestId('access-gate').getByRole('link', { name: 'read about Blindspot' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'About Blindspot' })).toBeVisible();
  await expect(page.getByTestId('about-run')).toContainText('Private repo during the hackathon');
});

for (const what of ['review', 'cohort'] as const) {
  test(`reviewer gate on /${what}: prompt, then the page loads`, async ({ page }) => {
    let ok = false;
    const target = what === 'review' ? '**/api/review/items**' : '**/api/cohort/dashboard**';
    await page.route('**/api/review/access', (route) => { ok = true; return json(route, 200, { ok: true, required: true }); });
    await page.route(target, (route) => (ok ? route.fallback() : json(route, 401, { error: 'review_code_required' })));
    await page.goto(`/${what}?mock=0`);
    const gate = page.getByTestId('reviewer-gate');
    await expect(gate).toBeVisible();
    await expect(gate).toContainText('Enter the reviewer code.');
    if (what === 'review') await shot(page, '04-reviewer-gate');
    await page.getByTestId('reviewer-code').fill('reviewer-123');
    await page.getByTestId('reviewer-submit').click();
    await expect(gate).toHaveCount(0);
    await expect(page.getByTestId(what === 'review' ? 'tab-debriefs' : 'cohort-n').or(page.getByTestId('queue-empty'))).toBeVisible({ timeout: 15_000 });
  });
}

test('below 900 px: a polite note instead of the reading room; landing and About still read', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`/read${ROOT.slice(1)}`);
  const note = page.getByTestId('small-screen');
  await expect(note).toBeVisible();
  await expect(note).toContainText('Blindspot needs a laptop or desktop screen to read radiographs properly');
  await expect(note.getByRole('link', { name: 'Read about Blindspot' })).toBeVisible();
  await expect(page.getByTestId('stage')).toHaveCount(0);
  await shot(page, '05-small-screen');
  for (const path of ['/review', '/cohort', '/progress']) {
    await page.goto(path);
    await expect(page.getByTestId('small-screen')).toBeVisible();
  }
  await page.goto(ROOT);
  await expect(page.getByTestId('landing-small-screen')).toBeVisible();
  await expect(page.getByTestId('try-demo')).toHaveCount(0);
  await expect(page.getByTestId('start')).toHaveCount(0);
  const p = (await page.getByTestId('mode-practice').boundingBox())!;
  const d = (await page.getByTestId('mode-drill').boundingBox())!;
  expect(d.y).toBeGreaterThan(p.y + p.height - 2); // one column
  const o = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
  expect(o.sw).toBeLessThanOrEqual(o.iw + 1);
  await shot(page, '06-small-landing');
  await page.goto('/about');
  await expect(page.getByRole('heading', { level: 1, name: 'About Blindspot' })).toBeVisible();
});

test('reading room for strangers: key help, nudges, loupe indicator, progress', async ({ page }) => {
  await startPractice(page);
  // First-visit auto-open is skipped under automation; "?" and the Keys button open it.
  await expect(page.getByTestId('keys-help')).toHaveCount(0);
  const nudge = page.getByTestId('nudge');
  await expect(nudge).toContainText('Click the film to mark a finding');
  await expect(nudge).toContainText('Use the wheel to zoom');
  await expect(page.getByTestId('loupe-toggle')).toHaveText('Loupe on');
  await page.mouse.move(2, 400);
  await page.keyboard.press('Shift+Slash');
  const help = page.getByTestId('keys-help');
  await expect(help).toBeVisible();
  for (const t of ['Click the film', 'Mouse wheel', 'Loupe on or off', 'Call it normal', 'Show anatomy', 'Next case']) await expect(help).toContainText(t);
  // Shortcuts do not fire behind the dialog.
  await page.keyboard.press('l');
  await expect(page.getByTestId('loupe-toggle')).toHaveText('Loupe on');
  await shot(page, '07-keys-help', true);
  await page.keyboard.press('Escape');
  await expect(help).toHaveCount(0);
  await page.getByTestId('keys-button').click();
  await expect(help).toBeVisible();
  await page.getByTestId('keys-close').click();
  await expect(help).toHaveCount(0);

  await page.keyboard.press('l');
  await expect(page.getByTestId('loupe-toggle')).toHaveText('Loupe off');
  await page.keyboard.press('l');
  const st = (await page.getByTestId('stage').boundingBox())!;
  await page.mouse.move(st.x + st.width / 2, st.y + st.height / 2);
  await page.mouse.wheel(0, -400);
  await expect(nudge).not.toContainText('Use the wheel to zoom');
  await expect(nudge).toContainText('Click the film to mark a finding');
});

test('assessment header shows "Case n of 20" with a progress bar', async ({ page }) => {
  await page.goto('/?mock=0');
  await page.getByTestId('name').fill('E2E general assess (test)');
  await page.getByLabel(/^Assessment A/).check();
  await page.getByTestId('start').click();
  await filmReady(page);
  await expect(page.getByTestId('case-index')).toHaveText(/^Case 1 of \d+$/);
  await expect(page.getByRole('progressbar', { name: 'Cases read' })).toHaveAttribute('aria-valuenow', '0');
  await expect(page.getByTestId('loupe-toggle')).toHaveText('Loupe off');
});

const DEBRIEF = {
  headline: 'You called this film normal.',
  verdict: 'correct_normal',
  findings: [],
  overcalls: [],
  search_coaching: 'Check both apices before you call a film normal.',
  calibration_note: '',
  next_step: 'Keep reading.',
  fact_ids: [],
};

const TAG_CASES = [
  { name: 'live + student reviewed', body: { status: 'ready', source: 'live', provenance: 'student_reviewed', debrief: DEBRIEF }, source: 'Claude debrief', prov: 'Student reviewed', busy: false },
  { name: 'cache + radiologist reviewed', body: { status: 'ready', source: 'cache', provenance: 'radiologist_reviewed', debrief: DEBRIEF }, source: 'Claude (cached)', prov: 'Radiologist reviewed', busy: false },
  { name: 'rate limited → built-in', body: { status: 'ready', source: 'template', provenance: 'ai_draft', error: 'rate_limited', debrief: DEBRIEF }, source: 'Built-in', prov: 'AI draft — not yet reviewed', busy: true },
  { name: 'failed', body: { status: 'failed', error: 'LiveCallError' }, source: null, prov: null, busy: true },
];

for (const c of TAG_CASES) {
  test(`debrief tags: ${c.name}`, async ({ page }) => {
    await page.route('**/api/attempts/*/debrief', (route) => json(route, 200, c.body));
    await startPractice(page, '/?mock=0');
    await submitNormal(page);
    const panel = page.getByTestId('debrief');
    if (c.source) await expect(panel.getByTestId('debrief-source')).toHaveText(c.source);
    else await expect(panel.getByTestId('debrief-source')).toHaveCount(0);
    if (c.prov) await expect(panel.getByTestId('provenance')).toHaveText(c.prov);
    if (c.busy) await expect(panel.getByTestId('debrief-busy')).toHaveText('The tutor is busy. Showing the built-in explanation instead.');
    else await expect(panel.getByTestId('debrief-busy')).toHaveCount(0);
    if (c.body.debrief) await expect(panel).toContainText('Check both apices');
    if (c.name.startsWith('live')) {
      await panel.scrollIntoViewIfNeeded();
      await shot(page, '08-debrief-tags', true);
    }
  });
}

test('Show anatomy (A) after submit: zone outlines with names on hover; not before', async ({ page }) => {
  const calls: string[] = [];
  page.on('request', (r) => { if (/\/api\/attempts\/[^/]+\/anatomy$/.test(new URL(r.url()).pathname)) calls.push(r.url()); });
  await startPractice(page, REAL ? '/?mock=0' : '/?mock=1');
  await page.mouse.move(2, 400);
  await page.keyboard.press('a'); // before submit: nothing
  await expect(page.getByTestId('anatomy-layer')).toHaveCount(0);
  await expect(page.getByTestId('anatomy-toggle')).toHaveCount(0);
  expect(calls).toEqual([]);
  await submitNormal(page);
  await page.waitForTimeout(1300); // let the reveal settle
  await page.keyboard.press('a');
  const layer = page.getByTestId('anatomy-layer');
  await expect(layer).toBeVisible();
  await expect(page.getByTestId('anatomy-toggle')).toHaveText(/Hide anatomy/);
  const zones = layer.locator('path[data-zone]');
  expect(await zones.count()).toBeGreaterThan(3);
  // Hover the smallest zone (drawn last, on top) and read its name.
  const last = zones.last();
  const box = (await last.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page.getByTestId('zone-name')).not.toContainText('Point at a zone');
  await expect(page.getByTestId('zone-name')).not.toBeEmpty();
  await shot(page, '09-reveal-anatomy', true);
  await page.keyboard.press('a');
  await expect(layer).toHaveCount(0);
});

test('page titles name the page', async ({ page }) => {
  for (const [path, title] of [['/about', 'About · Blindspot'], ['/progress?mock=0', 'Reading log · Blindspot'], ['/nope', 'Page not found · Blindspot']] as const) {
    await page.goto(path);
    await expect(page).toHaveTitle(title);
  }
});
