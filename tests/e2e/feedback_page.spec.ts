// /feedback — the in-app feedback form. Author: frontend-engineer (qa-reviewer owns this directory).
// The worker is mocked with page.route: a valid send shows the thank-you and the POST body matches the worker's
// contract; a 429 shows the hourly-limit line; the four ratings and the verdict are enforced before anything is
// sent; the landing band links here. Runs on the throwaway stack (?mock=0 is not needed: nothing hits the API).
import { expect, test, type Page } from '@playwright/test';

const SHOTS = `${process.cwd().endsWith('frontend') ? '../' : ''}tests/e2e/__screenshots__`;
const WORKER = '**/feedback/submit';

async function rateAll(page: Page, values: Record<'ease' | 'teaching' | 'accuracy' | 'recommend', number>) {
  for (const [k, v] of Object.entries(values)) await page.getByTestId(`fb-${k}-${v}`).click();
}

test('a full answer is sent as the worker expects and ends on the thank-you', async ({ page }) => {
  let body: unknown = null;
  let contentType = '';
  await page.route(WORKER, async (route) => {
    body = route.request().postDataJSON();
    contentType = route.request().headers()['content-type'] ?? '';
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, id: 'e2e' }) });
  });
  await page.goto('/feedback');
  await expect(page).toHaveTitle('Feedback · Blindspot');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Feedback');
  await expect(page.getByTestId('disclaimer')).toBeVisible();

  await page.getByTestId('fb-role-resident').click();
  await page.getByTestId('fb-years-5-15').click();
  await rateAll(page, { ease: 4, teaching: 5, accuracy: 3, recommend: 4 });
  await page.getByTestId('fb-verdict-yes').click();
  await page.getByTestId('fb-missing').fill('  More CT cases, and a way to compare two films.  ');
  await expect(page.getByTestId('fb-missing-count')).toHaveText('50 / 600');
  await page.getByTestId('fb-contact').fill(' Dr A. Example · a@example.org ');
  await page.screenshot({ path: `${SHOTS}/feedback-v2-01-filled.png`, fullPage: true });

  await page.getByTestId('fb-send').click();
  await expect(page.getByTestId('feedback-done')).toContainText('Thank you — received.');
  await expect(page.getByTestId('feedback-back')).toHaveAttribute('href', '/start');
  expect(contentType).toMatch(/^application\/json/);
  expect(body).toEqual({
    role: 'resident', years: '5-15', ease: 4, teaching: 5, accuracy: 3, recommend: 4, real_product: 'yes',
    missing: 'More CT cases, and a way to compare two films.', contact: 'Dr A. Example · a@example.org',
  });
  await page.screenshot({ path: `${SHOTS}/feedback-v2-02-done.png` });
  await page.getByTestId('feedback-back').click();
  await expect(page).toHaveURL(/\/start$/);
});

test('the minimum answer sends "other" for no role and "" for no years', async ({ page }) => {
  let body: Record<string, unknown> | null = null;
  await page.route(WORKER, async (route) => {
    body = route.request().postDataJSON();
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' });
  });
  await page.goto('/feedback');
  await rateAll(page, { ease: 2, teaching: 2, accuracy: 2, recommend: 2 });
  await page.getByTestId('fb-verdict-maybe').click();
  await page.getByTestId('fb-send').click();
  await expect(page.getByTestId('feedback-done')).toBeVisible();
  expect(body).toEqual({ role: 'other', years: '', ease: 2, teaching: 2, accuracy: 2, recommend: 2, real_product: 'maybe', missing: '', contact: '' });
});

test('the ratings and the verdict are required; nothing is sent until they are answered', async ({ page }) => {
  let posts = 0;
  await page.route(WORKER, async (route) => { posts++; await route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' }); });
  await page.goto('/feedback');
  await page.getByTestId('fb-send').click();
  await expect(page.getByTestId('fb-error')).toHaveText('Rate all four questions first.');
  await expect(page.getByTestId('feedback-done')).toHaveCount(0);
  // Three of four: still the same line; the one still missing is the one framed.
  await rateAll(page, { ease: 3, teaching: 3, accuracy: 3 } as never);
  await page.getByTestId('fb-send').click();
  await expect(page.getByTestId('fb-error')).toHaveText('Rate all four questions first.');
  await page.getByTestId('fb-recommend-5').click();
  await page.getByTestId('fb-send').click();
  await expect(page.getByTestId('fb-error')).toHaveText('Say whether this could become a real tool.');
  expect(posts).toBe(0);
  await page.getByTestId('fb-verdict-no').click();
  await page.getByTestId('fb-send').click();
  await expect(page.getByTestId('feedback-done')).toBeVisible();
  expect(posts).toBe(1);
});

test('the hourly limit (429) and a failed connection are explained inline, and the answers stay', async ({ page }) => {
  await page.route(WORKER, (route) => route.fulfill({ status: 429, contentType: 'application/json', body: JSON.stringify({ error: 'Thanks — that is plenty for one hour. Try again later.' }) }));
  await page.goto('/feedback');
  await rateAll(page, { ease: 5, teaching: 4, accuracy: 4, recommend: 5 });
  await page.getByTestId('fb-verdict-yes').click();
  await page.getByTestId('fb-missing').fill('Keep this');
  await page.getByTestId('fb-send').click();
  await expect(page.getByTestId('fb-error')).toHaveText("You've sent a few already — try again in an hour.");
  await expect(page.getByTestId('feedback-done')).toHaveCount(0);
  await expect(page.getByTestId('fb-missing')).toHaveValue('Keep this');
  await expect(page.getByTestId('fb-ease')).toHaveAttribute('data-value', '5');
  await page.screenshot({ path: `${SHOTS}/feedback-v2-03-limit.png` });

  await page.unroute(WORKER);
  await page.route(WORKER, (route) => route.abort('failed'));
  await page.getByTestId('fb-send').click();
  await expect(page.getByTestId('fb-error')).toHaveText('No connection. Check your network and try again.');
  await expect(page.getByTestId('fb-send')).toBeEnabled();
});

test('the landing band links to the form', async ({ page }) => {
  await page.goto('/?mock=0');
  await page.getByTestId('give-feedback').click();
  await expect(page).toHaveURL(/\/feedback$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Feedback');
});

test('at 1280 and 390 px the form fits, with no sideways scroll', async ({ page }) => {
  await page.goto('/feedback');
  await page.screenshot({ path: `${SHOTS}/feedback-v2-04-1280.png`, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/feedback');
  await expect(page.getByTestId('small-screen')).toHaveCount(0);
  await expect(page.getByTestId('fb-send')).toBeVisible();
  const o = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
  expect(o.sw).toBeLessThanOrEqual(o.iw + 1);
  await page.screenshot({ path: `${SHOTS}/feedback-v2-05-390.png`, fullPage: true });
});
