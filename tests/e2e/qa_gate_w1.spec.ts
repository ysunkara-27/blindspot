// QA gate W1 (M1, M3, M4, M5) — owner: qa-reviewer. Run against the REAL API:
//   cd frontend && E2E_REAL=1 NODE_PATH=$PWD/node_modules BLINDSPOT_OFFLINE=1 npx playwright test --config ../tests/e2e/playwright.config.ts qa_gate_w1
// Screenshots contain dataset radiographs, so every file is named live-qa-*.png (gitignored).
import { expect, test, type Page } from '@playwright/test';

const SHOTS = 'tests/e2e/__screenshots__';
const shot = (page: Page, name: string) =>
  page.screenshot({ path: `${process.cwd().endsWith('frontend') ? '../' : ''}${SHOTS}/live-qa-${name}.png` });

const GT_KEYS = ['"polygon"', '"bbox"', '"findings"', '"is_normal"', '"centroid"', '"primary_zone"', '"relative_location"', '"reveal"', '"facts_card"', '"outcomes"', '"mask_path"'];

function watch(page: Page) {
  const errors: string[] = [];
  const failed: string[] = [];
  const bodies: { url: string; method: string; body: string }[] = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text().slice(0, 200)); });
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message.slice(0, 200)}`));
  page.on('requestfailed', (r) => failed.push(`${r.method()} ${r.url()}`));
  page.on('response', async (r) => {
    if (!r.url().includes('/api/') || r.url().includes('/image')) return;
    bodies.push({ url: r.url(), method: r.request().method(), body: await r.text().catch(() => '') });
  });
  return { errors, failed, bodies };
}

async function filmReady(page: Page) {
  await page.waitForFunction(() => {
    const img = document.querySelector<HTMLImageElement>('[data-testid=film]');
    return !!img && img.complete && img.naturalWidth > 0;
  });
}

// Round 3: the form moved from the landing to /start; "Assessment A" is now "Test myself" (set A the first time).
async function start(page: Page, mode: 'Practice' | 'Assessment A' = 'Practice', query = '') {
  await page.goto(`/start?mock=0${query}`);
  await page.getByTestId('name').fill('QA gate');
  if (mode === 'Assessment A') await page.getByTestId('practice-test').check();
  await page.getByTestId('start').click();
  await expect(page.getByTestId('film')).toBeVisible();
  await page.waitForFunction(() => {
    const img = document.querySelector<HTMLImageElement>('[data-testid=film]');
    return !!img && img.complete && img.naturalWidth > 0;
  });
}

async function geom(page: Page) {
  const box = (await page.getByTestId('stage').boundingBox())!;
  const [ox, oy, sc] = (await page.getByTestId('stage').getAttribute('data-view'))!.split(',').map(Number);
  return (ix: number, iy: number) => [box.x + ox + ix * sc, box.y + oy + iy * sc] as const;
}

async function mark(page: Page, ix: number, iy: number, label: string, conf = 3) {
  const [sx, sy] = (await geom(page))(ix, iy);
  await page.mouse.click(Math.round(sx), Math.round(sy));
  const pop = page.getByTestId('mark-popover');
  await expect(pop).toBeVisible();
  await pop.getByRole('button', { name: label, exact: true }).click();
  await pop.getByRole('radio', { name: `Confidence ${conf} of 5` }).click();
  await pop.getByRole('button', { name: 'Done' }).click();
}

async function noHorizontalScroll(page: Page, where: string) {
  const o = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
  expect(o.sw, `horizontal page scroll on ${where}`).toBeLessThanOrEqual(o.iw + 1);
}

for (const vp of [{ width: 1280, height: 800 }, { width: 1920, height: 1080 }]) {
  test(`full flow on the real API at ${vp.width}x${vp.height}`, async ({ page }) => {
    await page.setViewportSize(vp);
    const w = watch(page);
    await start(page);
    await noHorizontalScroll(page, 'read');
    await shot(page, `${vp.width}-01-case`);
    // zoom + wheel + marks + keyboard hint
    const stage = (await page.getByTestId('stage').boundingBox())!;
    await page.mouse.move(stage.x + stage.width / 2, stage.y + stage.height / 2);
    await page.mouse.wheel(0, -500);
    await page.waitForTimeout(200);
    await page.mouse.dblclick(stage.x + stage.width / 2, stage.y + stage.height / 2);
    await mark(page, 330, 520, 'Nodule', 4);
    await mark(page, 700, 520, 'Effusion'.replace('Effusion', 'Pleural effusion'), 2);
    await expect(page.getByTestId('mark-count')).toHaveText('2');
    await page.mouse.move(2, 400);
    await page.keyboard.press('h');
    await expect(page.getByTestId('hint-list').locator('li')).toHaveCount(1);
    const hint1 = await page.getByTestId('hint-list').locator('li').first().innerText();
    console.log('hint H1:', hint1.slice(0, 120));
    await shot(page, `${vp.width}-02-marked-hint`);
    // submit with Enter, measure reveal
    const t0 = Date.now();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('reveal-layer')).toBeVisible();
    const revealMs = Date.now() - t0;
    console.log(`reveal visible after ${revealMs} ms (includes network submit)`);
    await page.waitForTimeout(1500);
    await shot(page, `${vp.width}-03-reveal`);
    await expect(page.getByTestId('facts-card')).toBeVisible();
    const t1 = Date.now();
    await expect(page.getByTestId('debrief-source')).toBeVisible({ timeout: 20_000 });
    console.log(`debrief visible ${Date.now() - t1} ms after reveal settled`);
    await page.getByTestId('debrief').scrollIntoViewIfNeeded();
    await shot(page, `${vp.width}-04-debrief`);
    await noHorizontalScroll(page, 'reveal');
    // debrief text sanity in the rendered DOM
    const txt = await page.getByTestId('debrief').innerText();
    expect(txt).not.toMatch(/\b\d+(\.\d+)?\s?(cm|mm)\b/i);
    expect(txt).not.toMatch(/\b(treat|antibiotic|chest tube|biopsy|follow-?up)\b/i);
    await page.keyboard.press('ArrowRight');
    await expect(page.getByTestId('case-index')).toHaveText(/Case 2/);
    // pre-submit bodies carry no ground truth (everything except /submit, /debrief, /ask)
    const leaks: string[] = [];
    for (const b of w.bodies) {
      if (/\/(submit|debrief|ask)$/.test(b.url) || b.url.includes('/dev/') || b.url.includes('/review') || b.url.includes('/dashboard')) continue;
      for (const k of GT_KEYS) if (b.body.includes(k)) leaks.push(`${b.method} ${b.url} ${k}`);
    }
    expect(leaks).toEqual([]);
    expect(w.errors, 'console errors').toEqual([]);
    expect(w.failed, 'failed requests').toEqual([]);
  });
}

test('assessment: DOM and network show no feedback until the summary', async ({ page }) => {
  const w = watch(page);
  await start(page, 'Assessment A');
  const forbidden = ['reveal-layer', 'search-trace', 'facts-card', 'outcomes', 'debrief', 'ask', 'hint-btn', 'score'];
  let sawSummary = false;
  for (let i = 0; i < 25 && !sawSummary; i++) {
    if (await page.getByTestId('assessment-summary').isVisible()) { sawSummary = true; break; }
    await expect(page.getByTestId('submit')).toBeVisible();
    await filmReady(page);
    await page.waitForTimeout(300);
    if (i % 2 === 0) {
      await mark(page, 400 + i * 10, 500, 'Nodule', 3);
      await page.mouse.move(2, 400);
    } else {
      // Round 3: a normal call needs its own confidence (nothing is preselected). By button on some films, and by
      // keys alone on others: N, then a digit 1–5, then Enter.
      await page.mouse.move(2, 400);
      if (i % 4 === 1) await page.getByTestId('call-normal').click();
      else await page.keyboard.press('n');
      await expect(page.getByTestId('normal-called')).toBeVisible();
      await expect(page.getByTestId('submit')).toBeDisabled();
      await page.keyboard.press('3');
      await expect(page.getByTestId('confidence-normal').getByRole('radio', { name: 'Confidence 3 of 5' })).toHaveAttribute('aria-checked', 'true');
    }
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('recorded')).toBeVisible();
    for (const id of forbidden) await expect(page.getByTestId(id), `testid ${id} must be absent`).toHaveCount(0);
    expect(await page.locator('[data-testid^="outline-"], [data-testid^="arrow-"]').count()).toBe(0);
    const text = await page.locator('body').innerText();
    expect(text).not.toMatch(/Found it|Never looked there|Looked past it|missed|expert read|F\d\b/i);
    await page.getByTestId('next-case').click();
    await expect(page.getByTestId('submit').or(page.getByTestId('assessment-summary'))).toBeVisible();
  }
  await expect(page.getByTestId('assessment-summary')).toBeVisible();
  await shot(page, 'assess-summary');
  const gt = w.bodies.filter((b) => b.url.endsWith('/submit') || b.url.includes('/next') || b.url.includes('/hint'));
  for (const b of gt) for (const k of GT_KEYS) expect(b.body, `${b.url}`).not.toContain(k);
});

test('footer disclaimer on every page; /about attributions', async ({ page }) => {
  const pages = ['/', '/read', '/progress', '/cohort', '/review', '/about', '/dev/case/cxd_36212', '/no-such-route'];
  const missing: string[] = [];
  for (const p of pages) {
    await page.goto(`${p}?mock=0`);
    await page.waitForTimeout(250);
    const t = await page.locator('body').innerText();
    if (!t.includes('For education. Not for clinical use.')) missing.push(p);
    await noHorizontalScroll(page, p);
    await shot(page, `page-${p.replace(/[^a-z0-9]+/gi, '_') || 'root'}`);
  }
  expect(missing.filter((p) => p !== '/no-such-route'), 'pages without the disclaimer').toEqual([]);
  expect.soft(missing, 'unknown routes render without the footer disclaimer').toEqual([]);
  await page.goto('/about?mock=0');
  const about = await page.locator('body').innerText();
  expect.soft(about, 'NIH Clinical Center acknowledgement').toMatch(/NIH Clinical Center/);
  expect.soft(about, 'Wang 2017 citation').toMatch(/Wang X.*ChestX-ray8.*2017/s);
  expect.soft(about, 'ChestX-Det citation').toMatch(/Lian J.*ChestX-Det|ChestX-Det.*Lian/s);
  expect.soft(about, 'ChestX-Det/Deepwise Apache-2.0 attribution').toMatch(/Apache[- ]2\.0/);
  expect.soft(about, 'Deepwise').toMatch(/Deepwise/);
  await shot(page, 'about-full');
});

test('keyboard: H gives a hint, M (and L) toggle the magnifier, 1-5 sets confidence, Backspace deletes, Enter submits, Arrow advances', async ({ page }) => {
  await start(page);
  await page.mouse.move(2, 400);
  await page.keyboard.press('h');
  await expect(page.getByTestId('hints-left')).toContainText('2 left');
  await page.keyboard.press('h');
  await expect(page.getByTestId('hints-left')).toContainText('1 left');
  await page.keyboard.press('h');
  await expect(page.getByTestId('hints-left')).toContainText('0 left');
  await page.keyboard.press('h'); // a fourth press must not break the page
  await expect(page.getByTestId('hint-list').locator('li')).toHaveCount(3);
  // Round 3: the magnifier starts off in every mode; M turns it on and the old key L still toggles it.
  await expect(page.getByTestId('loupe-toggle')).toHaveAttribute('aria-pressed', 'false');
  await page.keyboard.press('m');
  await expect(page.getByTestId('loupe-toggle')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('loupe-toggle')).toHaveText(/Magnifier on/);
  await page.keyboard.press('l');
  await expect(page.getByTestId('loupe-toggle')).toHaveAttribute('aria-pressed', 'false');
  // 1-5 for the selected mark, Backspace deletes it; N, a digit, Enter submits a normal call; the arrow advances.
  await mark(page, 420, 520, 'Nodule', 2);
  await page.mouse.move(2, 400);
  await page.keyboard.press('5');
  await expect(page.getByTestId('confidence-M1').getByRole('radio', { name: 'Confidence 5 of 5' })).toHaveAttribute('aria-checked', 'true');
  await page.keyboard.press('Backspace');
  await expect(page.getByTestId('mark-count')).toHaveText('0');
  await page.keyboard.press('n');
  await page.keyboard.press('4');
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('reveal-layer')).toBeVisible();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByTestId('case-index')).toHaveText(/Case 2/);
});

test('projector mode on the real film: label/outline legibility', async ({ page }) => {
  await start(page, 'Practice', '&projector=1');
  await mark(page, 330, 520, 'Nodule', 4);
  await page.mouse.move(2, 400);
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('reveal-layer')).toBeVisible();
  await page.waitForTimeout(1600);
  await shot(page, 'projector-reveal');
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.waitForTimeout(300);
  await shot(page, 'projector-reveal-1920');
});

test('reduced motion on the real film', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await start(page);
  await mark(page, 330, 520, 'Nodule', 4);
  await page.mouse.move(2, 400);
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('reveal-layer')).toBeVisible();
  const anim = await page.getByTestId('search-trace').evaluate((el) => getComputedStyle(el).animationName);
  expect(anim).toBe('none');
  await shot(page, 'reduced-motion');
});
