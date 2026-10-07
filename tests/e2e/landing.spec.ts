// The landing (/): one scrolling page, no form. Author: frontend-engineer (qa-reviewer owns this directory).
// Six sections in order, "Start reading" → /start, a scan card → /start with that scan type preselected, the
// feedback link, the copy sweep, and the 390 px layout. Runs on the throwaway stack (real offline API, ?mock=0).
import { expect, test, type Page } from '@playwright/test';

const SHOTS = `${process.cwd().endsWith('frontend') ? '../' : ''}tests/e2e/__screenshots__`;
const BANNED = /hackathon|\bdemo\b|\bpilot\b|judges|\bSUS\b|private preview/i;

/** Health as a library with all three scan types, whatever the throwaway server holds. */
async function withModalities(page: Page, by: Record<string, number>) {
  await page.route('**/api/health', async (route) => {
    const res = await route.fetch();
    const json = (await res.json()) as Record<string, unknown>;
    await route.fulfill({ response: res, json: { ...json, modalities: Object.keys(by).filter((k) => by[k] > 0), cases_by_modality: by } });
  });
}

test('the six sections, in order, with the copy the owner asked for', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await withModalities(page, { cxr: 3578, ct: 85, mr: 47 });
  await page.goto('/?mock=0');
  await expect(page).toHaveTitle('Blindspot · medical imaging perception trainer');

  // 1. Hero
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Learn to see what you keep missing on medical images.');
  await expect(page.getByTestId('hero-support')).toHaveText('Read real radiographs and scans outlined by radiologists. Blindspot replays where you looked and explains each miss.');
  await expect(page.getByTestId('start-reading')).toHaveText('Start reading');
  await expect(page.getByTestId('try-sample')).toHaveText('Try a sample set');
  await expect(page.getByTestId('free-line')).toHaveText('Free · no account · about 2 minutes per film');
  await expect(page.getByTestId('hero-film')).toBeVisible();
  await expect(page.getByText('Cyan is the expert outline.')).toBeVisible();

  // 2. Why this exists: three sourced facts, one line each, no charts.
  const why = page.getByTestId('why-this-exists');
  await expect(why.getByRole('heading', { level: 2 })).toHaveText('Why this exists');
  await expect(why.getByRole('listitem')).toHaveCount(3);
  for (const t of ['60–80 %', 'radiology clerkship', 'small pneumothoraces']) await expect(why).toContainText(t);
  await expect(why.getByRole('link')).toHaveCount(3);
  await expect(why.locator('svg')).toHaveCount(0);

  // 3. How it works: three numbered steps with a glyph each, and the proxy caveat under step 2.
  const how = page.getByTestId('how-it-works');
  await expect(how.getByRole('heading', { level: 2 })).toHaveText('How it works');
  await expect(how.getByRole('heading', { level: 3 })).toHaveText(['1Mark what you see', '2See how you looked', '3Learn from the expert read']);
  await expect(how.locator('svg')).toHaveCount(3);
  for (const t of ['say how sure', 'never looked there, looked past it, or looked and judged it normal', 'Radiologist outlines', 'reading log']) await expect(how).toContainText(t);
  await expect(page.getByTestId('proxy-caveat')).toContainText('not eye tracking');

  // 4. What you can read: three cards with live counts, a provenance line each, and a start button each.
  const read = page.getByTestId('what-you-can-read');
  await expect(read.getByRole('heading', { level: 2 })).toHaveText('What you can read');
  await expect(read.getByRole('heading', { level: 3 })).toHaveText(['Chest X-ray', 'Abdominal CT', 'Brain MRI']);
  await expect(page.getByTestId('scan-count-cxr')).toHaveText('3,578 films · 13 finding types');
  await expect(page.getByTestId('scan-count-ct')).toHaveText('85 studies · pancreas and liver tumours');
  await expect(page.getByTestId('scan-count-mr')).toHaveText('47 studies · gliomas');
  await expect(page.getByTestId('scan-card-cxr').getByTestId('scan-provenance')).toHaveText(['Outlined by three board-certified radiologists · ChestX-Det']);
  await expect(page.getByTestId('scan-card-ct').getByTestId('scan-provenance').first()).toContainText('Segmented by an abdominal radiologist');
  await expect(page.getByTestId('scan-card-mr').getByTestId('scan-provenance')).toHaveText([/Segmented by .*neuroradiologists · Medical Segmentation Decathlon, Task01 Brain Tumour/]);
  for (const m of ['cxr', 'ct', 'mr']) await expect(page.getByTestId(`scan-start-${m}`)).toHaveAttribute('href', `/start?modality=${m}`);
  await expect(page.getByTestId('health')).toContainText('Library: 3,578 chest films, 85 abdominal CT and 47 brain MRI studies');

  // 5. Tell us what you think
  const fb = page.getByTestId('feedback-band');
  await expect(fb.getByRole('heading', { level: 2 })).toHaveText('Tell us what you think');
  await expect(fb).toContainText('Blindspot is an early build. If you’re a radiologist, resident or student, two minutes of feedback shapes what we build next.');
  const give = page.getByTestId('give-feedback');
  await expect(give).toHaveText('Give feedback');
  await expect(give).toHaveAttribute('href', '/feedback');
  await expect(give).not.toHaveAttribute('target', '_blank');
  await expect(fb).toContainText('or reply to the email that brought you here');
  await expect(page.getByTestId('landing-links').getByRole('link', { name: 'Finding library' })).toHaveAttribute('href', '/reference');
  await expect(page.getByTestId('landing-links').getByRole('link', { name: 'How it’s built' })).toHaveAttribute('href', '/about');

  // 6. Footer
  const foot = page.getByTestId('disclaimer');
  await expect(foot).toContainText('For education. Not for clinical use. Images are de-identified research radiographs and scans with expert annotations.');
  await expect(foot.getByRole('link', { name: 'About' })).toHaveAttribute('href', '/about');
  await expect(foot.getByRole('link', { name: 'Reading log' })).toHaveAttribute('href', '/progress');

  // Order on the page, and no form, sidebar or banned words.
  const tops = await Promise.all(['why-this-exists', 'how-it-works', 'what-you-can-read', 'feedback-band', 'disclaimer'].map(async (id) => (await page.getByTestId(id).boundingBox())!.y));
  for (let i = 1; i < tops.length; i++) expect(tops[i]).toBeGreaterThan(tops[i - 1]);
  await expect(page.locator('form')).toHaveCount(0);
  await expect(page.locator('aside')).toHaveCount(0);
  expect(await page.locator('body').innerText()).not.toMatch(BANNED);
  await page.screenshot({ path: `${SHOTS}/landing-v2-01-full.png`, fullPage: true });
});

test('"Start reading" opens the start screen', async ({ page }) => {
  await page.goto('/?mock=0');
  await page.getByTestId('start-reading').click();
  await expect(page).toHaveURL(/\/start$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Start reading' })).toBeVisible();
});

test('a scan card opens the start screen with that scan type preselected', async ({ page }) => {
  await withModalities(page, { cxr: 500, ct: 12, mr: 6 });
  await page.goto('/?mock=0');
  await page.getByTestId('scan-start-ct').click();
  await expect(page).toHaveURL(/\/start\?modality=ct$/);
  await expect(page.getByTestId('scan-ct')).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByTestId('scan-cxr')).toHaveAttribute('aria-checked', 'false');
  await expect(page.getByTestId('finding-pick').locator('option').first()).toHaveText('Pancreatic tumour');
  // A scan type the server does not hold cannot be started from its card, which says so.
  await withModalities(page, { cxr: 500, ct: 0, mr: 0 });
  await page.goto('/?mock=0');
  await expect(page.getByTestId('scan-start-cxr')).toHaveAttribute('href', '/start?modality=cxr');
  await expect(page.getByTestId('scan-start-ct')).toHaveText('Not loaded on this server yet.');
  await expect(page.getByTestId('scan-count-ct')).toHaveText('Pancreas and liver tumours');
});

test('at 390 px the page stacks, reads in full, and asks for a computer instead of starting', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await withModalities(page, { cxr: 3578, ct: 85, mr: 47 });
  await page.goto('/?mock=0');
  await expect(page.getByTestId('small-screen')).toHaveCount(0);
  await expect(page.getByTestId('landing-small-screen')).toContainText('Open this page on a computer to start');
  await expect(page.getByTestId('start-reading')).toHaveCount(0);
  await expect(page.getByTestId('try-sample')).toHaveCount(0);
  for (const id of ['why-this-exists', 'how-it-works', 'what-you-can-read', 'feedback-band', 'disclaimer']) await expect(page.getByTestId(id)).toBeVisible();
  // Cards and steps stack: each starts below the previous one.
  const cards = await Promise.all(['cxr', 'ct', 'mr'].map(async (m) => (await page.getByTestId(`scan-card-${m}`).boundingBox())!));
  expect(cards[1].y).toBeGreaterThanOrEqual(cards[0].y + cards[0].height);
  expect(cards[2].y).toBeGreaterThanOrEqual(cards[1].y + cards[1].height);
  expect(cards[0].width).toBeGreaterThan(300);
  await expect(page.getByTestId('scan-start-cxr')).toHaveCount(0);
  const o = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
  expect(o.sw).toBeLessThanOrEqual(o.iw + 1);
  await expect(page.getByTestId('give-feedback')).toHaveAttribute('href', '/feedback');
  await page.screenshot({ path: `${SHOTS}/landing-v2-02-narrow.png`, fullPage: true });
});
