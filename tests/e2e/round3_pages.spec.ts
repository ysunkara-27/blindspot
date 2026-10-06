// Round 3 — the pages around the reading room. Author: frontend-engineer (pages/app/dashboard).
// Start screen → set length → end-of-set summary → one film's review; weak-spots gating; the test-set summary's review
// links; the learner nav; the finding library; the copy sweep; the returning learner.
// Runs against the REAL offline API of the throwaway stack (?mock=0). Reads are submitted through the API, not by
// clicking the film, so these tests do not depend on how marking works in the reading room.
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const API = process.env.E2E_API ?? 'http://127.0.0.1:8000/api';
const SHOTS = `${process.cwd().endsWith('frontend') ? '../' : ''}tests/e2e/__screenshots__`;
const BANNED = /hackathon|\bdemo\b|\bpilot\b|judges|\bSUS\b|private preview/i;

test.use({ viewport: { width: 1280, height: 800 } });

type Stored = { sessionId: string; learnerId: string; mode: string };
const storedSession = (page: Page) => page.evaluate(() => (JSON.parse(sessionStorage.getItem('blindspot.session') ?? '{}').state?.session ?? null) as Stored | null);

/** Submit every remaining film of a session as "normal, confidence 3" with a short cursor trace. Returns how many. */
async function readAll(request: APIRequestContext, sid: string, max = 60) {
  let n = 0;
  for (; n < max; n++) {
    const next = await (await request.get(`${API}/sessions/${sid}/next`)).json();
    if (next.done) break;
    const { width: w, height: h } = next.case;
    const res = await request.post(`${API}/attempts/${next.attempt_id}/submit`, {
      data: {
        marks: [], patterns: [], declared_normal: true, normal_confidence: 3,
        telemetry: [{ t: 0, kind: 'move', x: w * 0.4, y: h * 0.4, zoom: 1, vp: [0, 0, w, h], loupe: false }, { t: 400, kind: 'move', x: w * 0.6, y: h * 0.6, zoom: 1, vp: [0, 0, w, h], loupe: false }],
        hints_used: 0,
        client_timing: { shown_at: new Date(Date.now() - 15_000).toISOString(), submitted_at: new Date().toISOString() },
      },
    });
    expect(res.ok(), `submit ${n + 1}: ${res.status()}`).toBeTruthy();
  }
  return n;
}

test('a 5-film mixed set: "of 5" in the header, an end screen with 5 rows, and one film reviewed', async ({ page, request }) => {
  const posted: Record<string, unknown>[] = [];
  page.on('request', (r) => { if (r.url().endsWith('/api/sessions') && r.method() === 'POST') posted.push(r.postDataJSON()); });
  await page.goto('/start?mock=0');
  await expect(page.getByRole('heading', { level: 1, name: 'Start reading' })).toBeVisible();
  // A new learner cannot pick "My weak spots" yet, and is told why.
  await expect(page.getByTestId('practice-weak')).toBeDisabled();
  await expect(page.getByTestId('note-weak')).toHaveText('Opens after 5 films, so there is something to go on. You have read 0; 5 to go.');
  await expect(page.getByTestId('practice-mixed')).toBeChecked();
  await expect(page.getByTestId('scan-type')).toHaveText('Chest X-ray');
  await expect(page.getByText('More body regions are planned')).toBeVisible();
  await expect(page.getByTestId('half-normal')).toHaveText('About half the films are normal — finding nothing is a real answer.');
  await expect(page.getByTestId('level')).toHaveCount(0);
  await page.getByTestId('name').fill('E2E round3 (test)');
  await page.getByTestId('count-5').check({ force: true });
  await page.screenshot({ path: `${SHOTS}/round3-01-start.png`, fullPage: true });
  await page.getByTestId('start').click();
  await expect(page).toHaveURL(/\/read(\?|$)/);
  expect(posted).toEqual([expect.objectContaining({ display_name: 'E2E round3 (test)', level: 'other', mode: 'practice', settings: expect.objectContaining({ case_count: 5, selection: 'adaptive' }) })]);
  await expect(page.getByTestId('case-index')).toContainText('of 5', { timeout: 15_000 });

  const s = (await storedSession(page))!;
  expect(await readAll(request, s.sessionId)).toBe(5);

  // Back in the reading room the set is over: the end screen, not a sixth film.
  await page.goto('/read');
  const end = page.getByTestId('session-summary');
  await expect(end).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('summary-title')).toHaveText('Set complete');
  await expect(page.getByTestId('count-films')).toContainText('5');
  await expect(page.getByTestId('count-found')).toContainText(/\d+ of \d+|No findings in this set/);
  await expect(page.getByTestId('count-normal')).toContainText(/\d+ of \d+|No normal films in this set/);
  await expect(page.getByTestId('common-miss')).toContainText(/You most often|No misses and no false alarms/);
  await expect(page.getByTestId('case-row')).toHaveCount(5);
  await expect(page.getByTestId('case-review-link')).toHaveCount(5);
  await expect(page.getByTestId('read-another')).toHaveText('Read another set');
  await expect(page.getByTestId('open-log')).toHaveText('Open my reading log');
  expect(await page.locator('main').innerText()).not.toMatch(BANNED);
  await page.screenshot({ path: `${SHOTS}/round3-02-set-summary.png`, fullPage: true });

  // One row opens that film's review: the film, what was there, the facts, the debrief.
  await page.getByTestId('case-review-link').first().click();
  await expect(page).toHaveURL(/\/review-case\/[^/?]+\?set=/);
  await expect(page.getByTestId('case-review-page')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('case-review-title')).toHaveText('Film 1 of 5');
  // The reading room's own components: the still film, the "what was there" list, the search summary, the debrief.
  await expect(page.getByTestId('case-review')).toBeVisible();
  await expect(page.getByTestId('outcomes')).toBeVisible();
  await expect(page.getByTestId('score')).toContainText('/ 100');
  await expect(page.getByTestId('facts-card')).toBeVisible();
  await expect(page.getByTestId('case-zero-marks')).toHaveText('You placed no marks on this film.'); // these reads were normal calls
  await expect(page.getByTestId('case-film')).toBeVisible();
  await page.waitForFunction(() => {
    const img = document.querySelector<HTMLImageElement>('[data-testid=case-film]');
    return !!img && img.complete && img.naturalWidth > 0;
  });
  await expect(page.getByTestId('debrief')).toBeVisible();
  await expect(page.getByTestId('debrief-source')).toBeVisible({ timeout: 20_000 }); // offline stack: the built-in explanation
  await expect(page.getByTestId('debrief')).toHaveCSS('opacity', '1'); // no reveal animation on a stored review
  await page.screenshot({ path: `${SHOTS}/live-round3-03-case-review.png`, fullPage: true });
  await page.getByTestId('next-film').click();
  await expect(page.getByTestId('case-review-title')).toHaveText('Film 2 of 5');
  await page.getByTestId('back-to-summary').click();
  await expect(page).toHaveURL(new RegExp(`/set/${s.sessionId}$`));
  await expect(page.getByTestId('case-row')).toHaveCount(5);

  // Five films is exactly where the reading log starts showing numbers, and where weak spots opens.
  await page.getByTestId('open-log').click();
  await expect(page.getByTestId('learner-dashboard')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('summary-stats-n')).toHaveText('n = 5 films');
  await page.goto('/start');
  await expect(page.getByTestId('welcome-back')).toHaveText('Welcome back, E2E round3 (test).');
  await expect(page.getByTestId('practice-weak')).toBeEnabled();
  await page.getByTestId('practice-weak').check();
  await page.getByTestId('count-5').check({ force: true });
  await page.getByTestId('start').click();
  await expect(page).toHaveURL(/\/read(\?|$)/);
  expect(posted[1]).toEqual(expect.objectContaining({ mode: 'practice', settings: expect.objectContaining({ case_count: 5, selection: 'weak_areas', learner_id: s.learnerId }) }));
});

test('one finding type sends a drill on that finding; the test set sends no length', async ({ page }) => {
  const posted: Record<string, unknown>[] = [];
  page.on('request', (r) => { if (r.url().endsWith('/api/sessions') && r.method() === 'POST') posted.push(r.postDataJSON()); });
  await page.goto('/start?mock=0');
  // Thirteen finding types, by their display names.
  await expect(page.getByTestId('finding-pick').locator('option')).toHaveCount(13);
  await page.getByTestId('finding-pick').selectOption({ label: 'Pleural effusion' });
  await expect(page.getByTestId('practice-finding')).toBeChecked();
  await page.getByTestId('count-20').check({ force: true });
  await page.getByTestId('start').click();
  await expect(page).toHaveURL(/\/read(\?|$)/);
  await expect(page.getByTestId('case-index')).toContainText('of 20', { timeout: 15_000 });
  expect(posted[0]).toEqual(expect.objectContaining({ display_name: 'Anonymous', participant_code: null, level: 'other', mode: 'drill', settings: expect.objectContaining({ case_count: 20, label: 'effusion' }) }));

  await page.goto('/start');
  await expect(page.getByTestId('welcome-back')).toHaveText('Welcome back.'); // the anonymous reader is remembered on this device
  await page.getByTestId('practice-test').check();
  await expect(page.getByTestId('count-5')).toHaveCount(0);
  await expect(page.getByTestId('count-fixed')).toBeVisible();
  await page.getByTestId('start').click();
  await expect(page).toHaveURL(/\/read(\?|$)/);
  await expect(page.getByTestId('case-index')).toContainText('of 20', { timeout: 15_000 });
  expect(posted[1]).toEqual(expect.objectContaining({ level: 'other', mode: 'assess_A' }));
  expect((posted[1].settings ?? {}) as object).not.toHaveProperty('case_count');
});

test('the test-set summary lists every film with a review link, and a review opens', async ({ page, request }) => {
  const s = await (await request.post(`${API}/sessions`, { data: { display_name: 'E2E round3 test set (test)', level: 'other', mode: 'assess_A' } })).json();
  // Before the last film is in, no review of a test film is open.
  const first = await (await request.get(`${API}/sessions/${s.session_id}/next`)).json();
  expect(await readAll(request, s.session_id)).toBe(20);
  await page.goto('/?mock=0');
  await page.evaluate(([sid, lid]) => {
    sessionStorage.setItem('blindspot.session', JSON.stringify({
      state: { session: { sessionId: sid, learnerId: lid, displayName: 'E2E round3 test set (test)', level: 'other', mode: 'assess_A' }, projector: false }, version: 0,
    }));
    // This browser remembers the reader, as it would after starting the test from /start.
    localStorage.setItem('bs_learner', JSON.stringify({ learnerId: lid, name: 'E2E round3 test set (test)', tests: [] }));
  }, [s.session_id, s.learner_id]);
  await page.goto('/read');
  await expect(page.getByTestId('assessment-summary')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('case-row')).toHaveCount(20);
  await expect(page.getByTestId('case-review-link')).toHaveCount(20);
  await page.screenshot({ path: `${SHOTS}/round3-04-test-summary.png`, fullPage: true });
  await page.getByTestId('case-review-link').first().click();
  await expect(page.getByTestId('case-review-page')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('case-review-title')).toHaveText('Film 1 of 20');
  await expect(page.getByTestId('outcomes')).toBeVisible();
  expect(page.url()).toContain(first.attempt_id);
  // The finished test moves this reader on to the second set next time.
  await page.goto('/start');
  await expect(page.getByTestId('note-test')).toContainText('You have taken the first set, so this is the second.');
});

test('a film that is not submitted yet has no review: the page says so and offers the way back', async ({ page, request }) => {
  const s = await (await request.post(`${API}/sessions`, { data: { display_name: 'E2E round3 open (test)', level: 'other', mode: 'practice', settings: { case_count: 5 } } })).json();
  const next = await (await request.get(`${API}/sessions/${s.session_id}/next`)).json();
  await page.goto(`/review-case/${next.attempt_id}?set=${s.session_id}&mock=0`);
  await expect(page.getByTestId('case-review-error')).toContainText('This review is not open yet.');
  await expect(page.getByTestId('case-review-page')).toHaveCount(0);
  await expect(page.getByTestId('case-film')).toHaveCount(0); // no film, no outlines before submit
  await expect(page.getByTestId('outcomes')).toHaveCount(0);
  await page.goto(`/set/${s.session_id}`);
  await expect(page.getByTestId('summary-title')).toHaveText('Set in progress');
  await expect(page.getByTestId('summary-lede')).toContainText('0 of 5 films');
  await page.goto('/review-case/not-an-attempt');
  await expect(page.getByTestId('case-review-error')).toContainText('No read was found for this link.');
});

test('learner nav is Read · Reading log · Reference · About; cohort and review are reached from About', async ({ page }) => {
  await page.goto('/?mock=0');
  const nav = page.getByRole('navigation', { name: 'Main' });
  await expect(nav.getByRole('link')).toHaveText(['Read', 'Reading log', 'Reference', 'About']);
  await expect(nav.getByRole('link', { name: /cohort/i })).toHaveCount(0);
  await expect(nav.getByRole('link', { name: /review/i })).toHaveCount(0);
  await expect(page.getByTestId('projector-toggle')).toHaveCount(0);
  await nav.getByRole('link', { name: 'Read', exact: true }).click();
  await expect(page).toHaveURL(/\/start$/);
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'About' }).click();
  const staff = page.getByTestId('about-staff');
  await expect(staff).toContainText('For instructors and reviewers');
  await expect(staff.getByRole('link', { name: 'cohort view' })).toHaveAttribute('href', /\/cohort$/);
  await expect(staff.getByRole('link', { name: 'expert review' })).toHaveAttribute('href', /\/review$/);
  // Both pages still open by URL.
  await page.goto('/cohort');
  await expect(page.getByRole('heading', { level: 1, name: 'Cohort' })).toBeVisible();
  await page.goto('/review');
  await expect(page.getByRole('heading', { level: 1, name: 'Expert review' })).toBeVisible();
});

test('the finding library lists 13 finding types with signs, mimics, examples and normal films', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/reference?mock=0');
  await expect(page.getByRole('heading', { level: 1, name: 'Finding library' })).toBeVisible();
  await expect(page.getByTestId('ref-entry')).toHaveCount(13, { timeout: 15_000 });
  await expect(page.getByTestId('ref-index').getByRole('link')).toHaveCount(await page.getByTestId('ref-normal').count() ? 14 : 13);
  const nodule = page.locator('#nodule');
  await expect(nodule.getByRole('heading', { level: 2, name: 'Nodule' })).toBeVisible();
  await expect(nodule).toContainText('Key signs');
  await expect(nodule).toContainText('Often mistaken for it');
  // Outlines can be switched off to look at the films unmarked.
  if (await page.getByTestId('ref-outline').count()) {
    await page.getByTestId('ref-outline-toggle').uncheck();
    await expect(page.getByTestId('ref-outline')).toHaveCount(0);
    await page.getByTestId('ref-outline-toggle').check();
  }
  // Radiopaedia is a link out, nothing more.
  for (const a of await page.getByRole('link', { name: 'Read more on Radiopaedia' }).all()) await expect(a).toHaveAttribute('href', /^https:\/\/radiopaedia\.org\//);
  await page.screenshot({ path: `${SHOTS}/live-round3-05-reference-top.png` });
  await page.goto('/reference#effusion');
  await expect(page.locator('#effusion')).toBeInViewport({ timeout: 15_000 });
  expect(await page.locator('main').innerText()).not.toMatch(BANNED);
  // Example films load lazily: wait for the ones in view before the shot.
  await page.waitForFunction(() => [...document.querySelectorAll<HTMLImageElement>('#effusion img')].every((i) => i.complete));
  await page.screenshot({ path: `${SHOTS}/live-round3-05-reference-entry.png` });
  expect(errors).toEqual([]);
});

test('copy sweep: no hackathon, demo, pilot, judges or SUS on the pages around the reading room; no all-caps labels', async ({ page }) => {
  for (const path of ['/?mock=0', '/start', '/about', '/progress', '/reference', '/nope']) {
    await page.goto(path);
    await expect(page.getByTestId('disclaimer').first()).toBeVisible();
    await expect(page.locator('main')).not.toBeEmpty();
    const text = await page.locator('body').innerText();
    expect(text, path).not.toMatch(BANNED);
    // Sentence case: no shouted run of three or more words (acronyms in citations such as "IEEE CVPR" are fine).
    expect(text.match(/\b[A-Z]{3,}(\s+[A-Z]{3,}){2,}\b/g) ?? [], path).toEqual([]);
    const upper = await page.evaluate(() => [...document.querySelectorAll('body *')].filter((el) => getComputedStyle(el).textTransform === 'uppercase' && (el.textContent ?? '').trim()).length);
    expect(upper, `${path}: text-transform uppercase`).toBe(0);
  }
  await page.goto('/about');
  await expect(page.getByTestId('about-search')).toContainText('Drew, Võ and Wolfe');
  await expect(page.getByTestId('about-search')).toContainText('proxy for gaze');
  await expect(page.getByTestId('about-next')).toContainText('plans, not promises');
  await expect(page.getByTestId('about-limits')).not.toContainText(/pilot/i);
  await expect(page.getByTestId('about-run').getByRole('link')).toHaveAttribute('href', 'https://github.com/ysunkara-27/blindspot');
  await page.screenshot({ path: `${SHOTS}/about.png`, fullPage: true });
});

test('a returning learner is welcomed back, continues the same log, and can start as someone new', async ({ page }) => {
  await page.goto('/start?mock=0');
  await page.getByTestId('name').fill('Maya (e2e test)');
  await page.getByTestId('count-5').check({ force: true });
  await page.getByTestId('start').click();
  await expect(page).toHaveURL(/\/read(\?|$)/);
  const first = (await storedSession(page))!;
  await page.goto('/');
  await expect(page.getByTestId('welcome-back')).toContainText('Welcome back, Maya (e2e test).');
  await expect(page.getByTestId('start-reading')).toHaveText('Continue');
  await page.screenshot({ path: `${SHOTS}/round3-06-welcome-back.png` });
  await page.getByTestId('start-reading').click();
  await expect(page.getByTestId('welcome-back')).toHaveText('Welcome back, Maya (e2e test).');
  await page.getByTestId('count-5').check({ force: true });
  await page.getByTestId('start').click();
  await expect(page).toHaveURL(/\/read(\?|$)/);
  await expect.poll(async () => (await storedSession(page))?.sessionId).not.toBe(first.sessionId);
  expect((await storedSession(page))!.learnerId).toBe(first.learnerId); // same reader, same log
  await page.goto('/');
  await page.getByTestId('forget-learner').click();
  await expect(page.getByTestId('welcome-back')).toHaveCount(0);
  await expect(page.getByTestId('start-reading')).toHaveText('Start reading');
});

test('the sample set reader is called "Sample set" in the reading log', async ({ page }) => {
  await page.goto('/?mock=0');
  await page.getByTestId('try-sample').click();
  await expect(page).toHaveURL(/\/read(\?|$)/);
  await page.goto('/progress');
  await expect(page.getByTestId('learner-name')).toHaveText('Sample set', { timeout: 15_000 });
  await expect(page.getByTestId('dashboard-n')).toContainText('The sample set is shared by everyone who tries it');
  // Trying the sample never becomes "you" on this device.
  await page.goto('/');
  await expect(page.getByTestId('welcome-back')).toHaveCount(0);
});

// The synthetic fallback (no server) follows the same flow: a set has a length, ends in the summary, and each film
// opens its review. Here the reads go through the reading room itself (keyboard: N, a confidence digit, Submit).
test('synthetic fallback: a 5-film set ends in the summary and a film review, marked as synthetic', async ({ page }) => {
  await page.goto('/start?mock=1');
  await expect(page.getByTestId('synthetic-badge')).toHaveText('Synthetic cases');
  await expect(page.getByTestId('practice-weak')).toBeDisabled();
  await page.getByTestId('count-5').check({ force: true });
  await page.getByTestId('start').click();
  for (let i = 1; i <= 5; i++) {
    await expect(page.getByTestId('case-index')).toContainText(`Case ${i} of 5`, { timeout: 15_000 });
    await expect(page.getByTestId('film')).toBeVisible();
    await page.mouse.move(2, 400);
    await page.keyboard.press('n');
    await page.keyboard.press('3');
    await page.getByTestId('submit').click();
    await expect(page.getByTestId('outcomes')).toBeVisible();
    await page.getByTestId('next-case').click();
  }
  await expect(page.getByTestId('session-summary')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('case-row')).toHaveCount(5);
  await page.getByTestId('case-review-link').nth(1).click();
  await expect(page.getByTestId('case-review-page')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('case-review-title')).toHaveText('Film 2 of 5');
  await expect(page.getByTestId('case-film')).toBeVisible();
  await expect(page.getByTestId('outcomes')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/round3-07-synthetic-review.png`, fullPage: true });
  // No dashboard is built from synthetic reads.
  await page.goto('/progress');
  await expect(page.getByTestId('dashboard-mock')).toContainText('no reading log is kept');
  await page.goto('/reference');
  await expect(page.getByTestId('ref-synthetic')).toBeVisible();
  await expect(page.getByTestId('ref-entry')).toHaveCount(13);
});

test('a film review draws your own mark, and works from the attempt link alone', async ({ page, request }) => {
  const s = await (await request.post(`${API}/sessions`, { data: { display_name: 'E2E round3 mark (test)', level: 'other', mode: 'practice', settings: { case_count: 3 } } })).json();
  const next = await (await request.get(`${API}/sessions/${s.session_id}/next`)).json();
  const { width: w, height: h } = next.case;
  const res = await request.post(`${API}/attempts/${next.attempt_id}/submit`, {
    data: {
      marks: [{ mark_id: 'M1', x: w * 0.3, y: h * 0.45, label: 'nodule', confidence: 4 }], patterns: [], declared_normal: false,
      telemetry: [{ t: 0, kind: 'move', x: w * 0.3, y: h * 0.45, zoom: 1, vp: [0, 0, w, h], loupe: false }], hints_used: 0,
      client_timing: { shown_at: new Date(Date.now() - 9000).toISOString(), submitted_at: new Date().toISOString() },
    },
  });
  expect(res.ok()).toBeTruthy();
  // No ?set=: the stored result itself says which film it was and where the mark went.
  await page.goto(`/review-case/${next.attempt_id}?mock=0`);
  await expect(page.getByTestId('case-review-page')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('case-review-title')).toHaveText('Film review');
  await expect(page.getByTestId('case-film')).toBeVisible();
  await expect(page.getByTestId('case-mark-M1')).toBeVisible();
  await expect(page.getByTestId('case-no-marks')).toHaveCount(0);
  await expect(page.getByTestId('case-zero-marks')).toHaveCount(0);
  await expect(page.getByTestId('outcomes')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/live-round3-08-review-with-mark.png` });
});
