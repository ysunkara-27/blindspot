// M7 /review e2e (SPEC §11.1, §15.2 M7). Author: frontend-engineer. Runs against the REAL API (BLINDSPOT_OFFLINE=1).
// Debrief ratings go to the real DB under reviewer "E2E reviewer (test)". Card approvals are intercepted so the test
// never rewrites content/teaching_cards/*.yaml. Shots containing films are named live-*.png (gitignored).
import { expect, test, type APIRequestContext } from '@playwright/test';

const API = process.env.E2E_API ?? 'http://127.0.0.1:8000/api';
const SHOTS = `${process.cwd().endsWith('frontend') ? '../' : ''}tests/e2e/__screenshots__`;
const REVIEWER = 'E2E reviewer (test)';

test.use({ viewport: { width: 1280, height: 800 } });

/** Make sure at least two live debriefs exist: two practice reads with a mark each, debrief polled to ready. */
async function seedDebriefs(request: APIRequestContext) {
  const s = await (await request.post(`${API}/sessions`, { data: { display_name: 'E2E review (test)', level: 'MS3', mode: 'practice' } })).json();
  for (let i = 0; i < 2; i++) {
    const next = await (await request.get(`${API}/sessions/${s.session_id}/next`)).json();
    const { width: w, height: h } = next.case;
    await request.post(`${API}/attempts/${next.attempt_id}/submit`, {
      data: {
        marks: [{ mark_id: 'M1', x: w * 0.3, y: h * 0.55, label: 'nodule', confidence: 4 }], patterns: [], declared_normal: false,
        telemetry: [{ t: 0, kind: 'move', x: w * 0.3, y: h * 0.55, zoom: 1, vp: [0, 0, w, h], loupe: true }], hints_used: 0,
        client_timing: { shown_at: new Date(Date.now() - 9000).toISOString(), submitted_at: new Date().toISOString() },
      },
    });
    for (let k = 0; k < 40; k++) {
      const d = await (await request.get(`${API}/attempts/${next.attempt_id}/debrief`)).json();
      if (d.status !== 'pending') break;
      await new Promise((r) => setTimeout(r, 250));
    }
  }
}

test('debrief review: keyboard rating, auto-advance, persisted reviewer, CSV export', async ({ page, request }) => {
  await seedDebriefs(request);
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/review?mock=0');
  await expect(page.getByTestId('debrief-review')).toBeVisible();
  await expect(page.getByTestId('queue-pos')).toHaveText(/^Item 1 of \d+$/);
  await page.getByTestId('reviewer-name').fill(REVIEWER);
  await page.getByTestId('reviewer-role').selectOption('Radiologist');
  // The film, expert outlines (if any) and the learner's marks render read-only.
  await expect(page.getByTestId('review-film')).toBeVisible();
  await expect(page.locator('[data-testid^="review-mark-"]').first()).toBeVisible();
  await expect(page.getByTestId('facts-summary')).toBeVisible();
  await expect(page.getByTestId('review-debrief')).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/live-review-debrief.png`, fullPage: true });

  // Enter without ratings explains what is missing.
  await page.locator('body').click({ position: { x: 5, y: 300 } });
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('rating-error')).toContainText('Rate accuracy and teaching value');

  // 4 → accuracy, 5 → teaching, N → no safety concern, C → correction, Escape, Enter → submit.
  await page.keyboard.press('4');
  await page.keyboard.press('5');
  await page.keyboard.press('n');
  await expect(page.getByTestId('accuracy-4')).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByTestId('teaching-5')).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByTestId('safety-no')).toHaveAttribute('aria-checked', 'true');
  await page.keyboard.press('c');
  await expect(page.getByTestId('correction')).toBeFocused();
  await page.keyboard.type('Clear and correct; e2e test rating.');
  await page.keyboard.press('Escape');
  const firstId = await page.getByTestId('queue-pos').textContent();
  const posted = page.waitForRequest((r) => r.url().endsWith('/api/review/ratings') && r.method() === 'POST');
  await page.keyboard.press('Enter');
  const body = (await posted).postDataJSON();
  expect(body).toMatchObject({ reviewer: REVIEWER, role: 'Radiologist', item_type: 'debrief', accuracy: 4, teaching: 5, safety_flag: false, comment: 'Clear and correct; e2e test rating.' });
  // Auto-advance to the next item with a fresh form.
  await expect(page.getByTestId('queue-done')).toHaveText('1 rated this visit');
  await expect(page.getByTestId('queue-pos')).not.toHaveText(firstId!);
  await expect(page.getByTestId('accuracy-4')).toHaveAttribute('aria-checked', 'false');

  // Reviewer identity survives a reload.
  await page.reload();
  await expect(page.getByTestId('reviewer-name')).toHaveValue(REVIEWER);
  await expect(page.getByTestId('reviewer-role')).toHaveValue('Radiologist');

  // The export link serves the stored rating.
  const href = await page.getByTestId('export-csv').getAttribute('href');
  const csv = await (await request.get(`${process.env.E2E_WEB ?? 'http://127.0.0.1:5173'}${href}`)).text();
  expect(csv.split('\n')[0]).toContain('reviewer,role,item_type,item_id,accuracy,teaching,safety_flag,comment');
  expect(csv).toContain(`${REVIEWER},Radiologist,debrief,${body.item_id},4,5,0,Clear and correct; e2e test rating.`);
  expect(errors).toEqual([]);
});

test('debrief review: rating needs a reviewer name', async ({ page, request }) => {
  await seedDebriefs(request);
  await page.goto('/review?mock=0');
  await page.evaluate(() => localStorage.removeItem('blindspot.reviewer'));
  await page.reload();
  await expect(page.getByTestId('debrief-review')).toBeVisible();
  await page.getByTestId('accuracy-3').click();
  await page.getByTestId('teaching-3').click();
  await page.getByTestId('safety-yes').click();
  await page.getByTestId('submit-rating').click();
  await expect(page.getByTestId('rating-error')).toContainText('Enter your name and role');
  await expect(page.getByTestId('reviewer-name')).toBeFocused();
});

test('empty debrief queue explains where items come from', async ({ page }) => {
  await page.route('**/api/review/items?type=debrief*', (r) => r.fulfill({ json: { type: 'debrief', n: 0, items: [] } }));
  await page.goto('/review?mock=0');
  await expect(page.getByTestId('queue-empty')).toContainText('eval/samples/review_queue.jsonl');
  await expect(page.getByTestId('queue-empty')).toContainText('This seems wrong');
});

test('teaching cards: inline edit + approve posts card_edits; flag needs a note', async ({ page }) => {
  const bodies: Record<string, unknown>[] = [];
  // Never write the YAML from a test: answer the POST here.
  await page.route('**/api/review/ratings', async (r) => { bodies.push(r.request().postDataJSON()); await r.fulfill({ json: { ok: true } }); });
  await page.goto('/review?tab=cards&mock=0');
  await page.getByTestId('reviewer-name').fill(REVIEWER);
  await page.getByTestId('reviewer-role').selectOption('Medical student');
  await expect(page.getByTestId('card-review')).toBeVisible();
  await page.getByTestId('card-nodule').click();
  await expect(page.getByTestId('field-display_name')).toHaveValue('Nodule');
  await page.screenshot({ path: `${SHOTS}/review-cards.png`, fullPage: true });

  // Flag without a note is refused.
  await page.getByTestId('card-accuracy-4').click();
  await page.getByTestId('card-teaching-3').click();
  await page.getByTestId('flag-card').click();
  await expect(page.getByTestId('card-msg')).toContainText('Say what needs changing');

  // Edit one field inline, then approve with keyboard ratings.
  const one = page.getByTestId('field-one_liner');
  await one.fill('A round spot in the lung, up to the size of a grape. (e2e edit)');
  await expect(page.getByTestId('approve-card')).toHaveText('Approve with 1 edit');
  await page.locator('h2', { hasText: 'Nodule' }).click();
  await page.getByTestId('card-accuracy-5').click();
  await page.keyboard.press('4'); // teaching is now the active scale
  await expect(page.getByTestId('card-teaching-4')).toHaveAttribute('aria-checked', 'true');
  await page.getByTestId('approve-card').click();
  await expect(page.getByTestId('card-msg')).toContainText('Approved as student reviewed with 1 edited field');
  const approve = bodies.at(-1)!;
  expect(approve).toMatchObject({
    reviewer: REVIEWER, role: 'Medical student', item_type: 'card', item_id: 'nodule', accuracy: 5, teaching: 4,
    card_edits: { one_liner: 'A round spot in the lung, up to the size of a grape. (e2e edit)', status: 'student_reviewed' },
  });
  expect(Object.keys(approve.card_edits as object).sort()).toEqual(['one_liner', 'status']);

  // Flag with a note posts no card_edits.
  await page.getByTestId('card-comment').fill('Mimics list should mention the nipple marker.');
  await page.getByTestId('flag-card').click();
  await expect(page.getByTestId('card-msg')).toContainText('Flagged');
  expect(bodies.at(-1)).toMatchObject({ item_type: 'card', item_id: 'nodule', card_edits: null, comment: 'Mimics list should mention the nipple marker.' });
});
