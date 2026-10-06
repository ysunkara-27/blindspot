// M4 reading-room e2e (SPEC §15.2 M4). Author: frontend-engineer (qa-reviewer owns this directory).
// Default: runs against the in-browser SYNTHETIC mock (/?mock=1) so it never depends on the backend.
// E2E_REAL=1: runs against the real API (start it with BLINDSPOT_OFFLINE=1) and also checks the no-GT-before-submit rule.
import { expect, test, type Page } from '@playwright/test';

const REAL = process.env.E2E_REAL === '1';
// Round 3: the start form lives at /start (practice-mixed, 10 films by default; practice-test = the fixed test set).
const ROOT = REAL ? '/start?mock=0' : '/start?mock=1';
const SHOTS = 'tests/e2e/__screenshots__';
// Real-API runs show dataset radiographs: name those shots live-*.png (gitignored). Mock runs keep their names.
const shot = (page: Page, name: string) =>
  page.screenshot({ path: `${process.cwd().endsWith('frontend') ? '../' : ''}${SHOTS}/${REAL ? 'live-' : ''}${name}.png` });

test.use({ viewport: { width: 1280, height: 800 } });

async function start(page: Page, mode = 'practice', root = ROOT) {
  await page.goto(root);
  await page.getByTestId('name').fill('E2E learner');
  if (mode === 'assess_A') await page.getByTestId('practice-test').check();
  await page.getByTestId('start').click();
  await expect(page.getByTestId('film')).toBeVisible();
  await page.waitForFunction(() => {
    const img = document.querySelector<HTMLImageElement>('[data-testid=film]');
    return !!img && img.complete && img.naturalWidth > 0;
  });
}

async function view(page: Page) {
  const stage = page.getByTestId('stage');
  const box = (await stage.boundingBox())!;
  const [ox, oy, sc] = (await stage.getAttribute('data-view'))!.split(',').map(Number);
  return {
    box, ox, oy, sc,
    toScreen: (ix: number, iy: number) => [box.x + ox + ix * sc, box.y + oy + iy * sc] as const,
    zoom: Number(await stage.getAttribute('data-zoom')),
  };
}

async function filmSize(page: Page) {
  return page.getByTestId('film').evaluate((el: HTMLImageElement) => ({ w: el.width, h: el.height }));
}

async function markPos(page: Page, id: string) {
  const t = await page.locator(`[data-mark-id="${id}"]`).getAttribute('transform');
  const [, x, y] = t!.match(/translate\(([-\d.e]+) ([-\d.e]+)\)/)!;
  return { x: Number(x), y: Number(y) };
}

async function placeMark(page: Page, ix: number, iy: number, label: string, conf: number) {
  const v = await view(page);
  const [sx, sy] = v.toScreen(ix, iy);
  await page.mouse.click(Math.round(sx), Math.round(sy));
  const pop = page.getByTestId('mark-popover');
  await expect(pop).toBeVisible();
  await pop.getByRole('button', { name: label, exact: true }).click();
  await pop.getByRole('radio', { name: `Confidence ${conf} of 5` }).click();
  await pop.getByRole('button', { name: 'Done' }).click();
  await expect(pop).toBeHidden();
}

async function sweep(page: Page, ms: number) {
  const v = await view(page);
  const t0 = Date.now();
  let i = 0;
  while (Date.now() - t0 < ms) {
    const a = (i++ / 40) * Math.PI;
    await page.mouse.move(v.box.x + v.box.width / 2 + Math.cos(a) * 220, v.box.y + v.box.height / 2 + Math.sin(a * 1.3) * 250);
    await page.waitForTimeout(16);
  }
}

test('practice flow: zoom, pan, loupe, marks, hint, submit, reveal, facts, debrief, next', async ({ page }) => {
  await start(page);
  await expect(page.getByTestId('case-index')).toHaveText(/Case 1/);
  const { w, h } = await filmSize(page);

  // Zoom at cursor ×3 with the wheel, then pan, then double-click resets.
  let v = await view(page);
  const cx = v.box.x + v.box.width / 2;
  const cy = v.box.y + v.box.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.wheel(0, -732.4); // exp(732.4 × 0.0015) = 3
  await expect.poll(async () => (await view(page)).zoom).toBeGreaterThan(2.9);
  await shot(page, 'm4-01-zoom3x');
  v = await view(page);
  await page.mouse.down();
  await page.mouse.move(cx + 120, cy + 60, { steps: 8 });
  await page.mouse.up();
  const panned = await view(page);
  expect(panned.ox).toBeCloseTo(v.ox + 120, 0);
  await page.mouse.dblclick(cx, cy);
  await expect.poll(async () => (await view(page)).zoom).toBeCloseTo(1, 2);

  // The magnifier is off until asked for (round 3); M turns it on and the lens follows the cursor over the film.
  await expect(page.getByTestId('loupe-toggle')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByTestId('loupe-toggle')).toHaveText(/Magnifier off/);
  await page.keyboard.press('m');
  await expect(page.getByTestId('loupe-toggle')).toHaveText(/Magnifier on/);
  await sweep(page, 1500);
  v = await view(page);
  const [lx, ly] = v.toScreen(w * 0.3, h * 0.4);
  await page.mouse.move(lx, ly);
  await expect(page.getByTestId('loupe')).toBeVisible();
  await shot(page, 'm4-02-loupe');
  await page.keyboard.press('m');
  await expect(page.getByTestId('loupe')).toBeHidden();

  // Two marks with labels and confidence. syn_005: F1 mass (right upper), F2 nodule (left lower). M2 is an overcall.
  await placeMark(page, w * 0.31, h * 0.37, 'Mass', 4);
  await placeMark(page, w * 0.23, h * 0.7, 'Nodule', 2);
  await expect(page.getByTestId('mark-count')).toHaveText('2');

  // Hint
  await page.getByTestId('hint-btn').click();
  await expect(page.getByTestId('hint-list').locator('li')).toHaveCount(1);
  await expect(page.getByTestId('hints-left')).toContainText('2 left');
  await shot(page, 'm4-03-marked');

  // Submit → reveal
  await page.getByTestId('submit').click();
  await expect(page.getByTestId('reveal-layer')).toBeVisible();
  await expect(page.getByTestId('search-trace')).toBeVisible();
  // Mock case syn_005 always has two findings (one found, one missed). A real case may be a normal film.
  if (!REAL || (await page.locator('[data-testid^="outline-"]').count()) > 0) {
    await expect(page.locator('[data-testid^="outline-"]').first()).toBeVisible();
  }
  // M2 is a wrong mark, so an arrow runs from it to the missed finding (arrows never start from the film centre).
  if (!REAL || (await page.locator('[data-testid^="arrow-F"]').count()) > 0) {
    await expect(page.locator('[data-testid^="arrow-F"]').first()).toBeVisible();
  }
  await page.waitForTimeout(1400); // let the ~1.2 s sequence finish
  if (!REAL) await expect(page.getByTestId('outcomes')).toContainText('Found it');
  else await expect(page.getByTestId('outcomes')).toBeVisible();
  await expect(page.getByTestId('facts-card')).toBeVisible();
  await shot(page, 'm4-04-reveal');

  // Debrief (template in mock / offline mode)
  await expect(page.getByTestId('debrief-source')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('provenance')).toBeVisible();
  await page.getByTestId('debrief').scrollIntoViewIfNeeded();
  await shot(page, 'm4-05-debrief');

  // Ask the tutor (3 questions max)
  const ask = page.getByTestId('ask');
  await ask.getByRole('textbox').fill('Why does a nodule look white?');
  await ask.getByRole('button', { name: 'Ask the tutor' }).click();
  await expect(ask).toContainText('2 questions left');

  // Next case
  await page.getByTestId('next-case').click();
  await expect(page.getByTestId('case-index')).toHaveText(/Case 2/);
  await expect(page.getByTestId('submit')).toBeDisabled();
});

test('telemetry: ≥ 30 events per 10 s of movement', async ({ page }) => {
  test.setTimeout(60_000);
  await start(page);
  const before = await page.evaluate(() => (window as unknown as { __bsTelemetry: { length: number } }).__bsTelemetry.length);
  await sweep(page, 10_000);
  const after = await page.evaluate(() => (window as unknown as { __bsTelemetry: { length: number } }).__bsTelemetry.length);
  console.log(`telemetry events in 10 s: ${after - before}`);
  expect(after - before).toBeGreaterThanOrEqual(30);
  const ev = await page.evaluate(() => (window as unknown as { __bsTelemetry: { snapshot(): { x?: number; zoom: number; vp: number[] }[] } }).__bsTelemetry.snapshot().at(-1));
  expect(ev!.vp).toHaveLength(4);
  expect(ev!.zoom).toBeCloseTo(1, 2);
});

for (const zoom of [1, 3]) {
  test(`click maps to image coordinates within 2 px at ${zoom}×`, async ({ page }) => {
    await start(page);
    const { w, h } = await filmSize(page);
    if (zoom === 3) {
      const v0 = await view(page);
      await page.mouse.move(v0.box.x + v0.box.width / 2, v0.box.y + v0.box.height / 2);
      await page.mouse.wheel(0, -732.4);
      await expect.poll(async () => (await view(page)).zoom).toBeGreaterThan(2.95);
    }
    const v = await view(page);
    expect(v.zoom).toBeCloseTo(zoom, 1);
    const targets = [[w * 0.5, h * 0.5], [w * 0.47, h * 0.53]];
    for (const [i, [tx, ty]] of targets.entries()) {
      const [sx, sy] = v.toScreen(tx, ty);
      await page.mouse.click(Math.round(sx), Math.round(sy));
      await expect(page.getByTestId('mark-popover')).toBeVisible();
      const p = await markPos(page, `M${i + 1}`);
      expect(Math.abs(p.x - tx)).toBeLessThanOrEqual(2);
      expect(Math.abs(p.y - ty)).toBeLessThanOrEqual(2);
      await page.keyboard.press('Escape');
      await expect(page.getByTestId('mark-popover')).toBeHidden();
    }
  });
}

test('keyboard shortcuts: M (and L), N, Enter, →, Backspace, 1–5', async ({ page }) => {
  await start(page);
  await page.keyboard.press('m');
  await expect(page.getByTestId('loupe-toggle')).toHaveAttribute('aria-pressed', 'true');
  await page.keyboard.press('l'); // the old key still works
  await expect(page.getByTestId('loupe-toggle')).toHaveAttribute('aria-pressed', 'false');
  // mark → 5 → Backspace
  const { w, h } = await filmSize(page);
  const v = await view(page);
  const [sx, sy] = v.toScreen(w * 0.4, h * 0.4);
  await page.mouse.click(sx, sy);
  await expect(page.getByTestId('mark-popover')).toBeVisible();
  await page.keyboard.press('Escape');
  await page.keyboard.press('5');
  await expect(page.getByTestId('confidence-M1').getByRole('radio', { name: 'Confidence 5 of 5' })).toHaveAttribute('aria-checked', 'true');
  await page.keyboard.press('Backspace');
  await expect(page.getByTestId('mark-count')).toHaveText('0');
  // N → normal call; a digit says how sure (nothing is preselected); Enter submits; → next
  await page.keyboard.press('n');
  await expect(page.getByTestId('normal-called')).toBeVisible();
  await expect(page.getByTestId('submit')).toBeDisabled();
  await page.keyboard.press('4');
  await expect(page.getByTestId('confidence-normal').getByRole('radio', { name: 'Confidence 4 of 5' })).toHaveAttribute('aria-checked', 'true');
  await page.mouse.move(1, 400); // leave the film
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('outcomes')).toBeVisible();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByTestId('case-index')).toHaveText(/Case 2/);
});

test('reduced motion: the reveal is instant', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await start(page);
  const { w, h } = await filmSize(page);
  await placeMark(page, w * 0.31, h * 0.37, 'Mass', 3);
  await page.getByTestId('submit').click();
  await expect(page.getByTestId('reveal-layer')).toBeVisible();
  // No waiting: outlines are fully drawn and labels visible immediately.
  expect(await page.getByTestId('search-trace').evaluate((el) => getComputedStyle(el).animationName)).toBe('none');
  const outline = page.locator('[data-testid^="outline-"] polygon, [data-testid^="outline-"] rect').first();
  if (!REAL || (await outline.count()) > 0) { // a real case may be a normal film with nothing to outline
    expect(await outline.evaluate((el) => getComputedStyle(el).animationName)).toBe('none');
    expect(await outline.evaluate((el) => getComputedStyle(el).strokeDashoffset)).toMatch(/^0(px)?$/);
  }
  await shot(page, 'm4-06-reduced-motion');
});

test('projector mode: ?projector=1 boosts type and strokes', async ({ page }) => {
  await start(page, 'practice', `${ROOT}&projector=1`);
  await expect(page.locator('html')).toHaveAttribute('data-projector', '1');
  // The toggle lives in the header's View menu as "Large-screen mode".
  await page.getByTestId('view-menu').click();
  await expect(page.getByTestId('projector-toggle')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('projector-toggle')).toContainText('Large-screen mode: on');
  await page.keyboard.press('Escape');
  const filter = await page.getByTestId('film').evaluate((el) => (el as HTMLElement).style.filter);
  expect(filter).toContain('contrast(1.3)');
  const { w, h } = await filmSize(page);
  await placeMark(page, w * 0.31, h * 0.37, 'Mass', 4);
  await page.getByTestId('submit').click();
  await page.waitForTimeout(1400);
  await shot(page, 'm4-07-projector');
  await page.getByTestId('view-menu').click();
  await page.getByTestId('projector-toggle').click();
  await expect(page.locator('html')).not.toHaveAttribute('data-projector', '1');
});

test('assessment: no reveal, "Recorded", summary at the end', async ({ page }) => {
  await start(page, 'assess_A');
  await expect(page.getByTestId('loupe-toggle')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByTestId('hint-btn')).toHaveCount(0);
  for (let i = 0; i < 40; i++) {
    if (await page.getByTestId('assessment-summary').isVisible()) break;
    await expect(page.getByTestId('submit')).toBeVisible();
    await page.getByTestId('call-normal').click();
    await page.getByTestId('confidence-normal').getByRole('radio', { name: 'Confidence 3 of 5' }).click();
    await page.getByTestId('submit').click();
    await expect(page.getByTestId('recorded')).toBeVisible();
    await expect(page.getByTestId('reveal-layer')).toHaveCount(0);
    await expect(page.getByTestId('outcomes')).toHaveCount(0);
    await page.getByTestId('next-case').click();
    await expect(page.getByTestId('submit').or(page.getByTestId('assessment-summary'))).toBeVisible();
  }
  await expect(page.getByTestId('assessment-summary')).toBeVisible();
  await shot(page, 'm4-08-assessment-summary');
});

test('about page and the disclaimer footer on every page', async ({ page }) => {
  for (const path of ['/', '/about', '/progress', '/cohort', '/review']) {
    await page.goto(path);
    await expect(page.getByTestId('disclaimer')).toContainText('For education. Not for clinical use.');
  }
  await page.goto('/about');
  await expect(page.getByText(/cursor, (loupe|magnifier) and zoom/).first()).toBeVisible();
  await shot(page, 'm4-09-about');
});

test('no ground truth reaches the client before submit (real API only)', async ({ page }) => {
  test.skip(!REAL, 'needs the real API; the mock runs in-page');
  const leaks: string[] = [];
  page.on('response', async (r) => {
    if (!r.url().includes('/api/') || r.request().method() === 'GET' && r.url().includes('/debrief')) return;
    if (r.url().includes('/submit')) return;
    // The reference library is generic teaching material from a separate set of films, never the case being read.
    if (/\/api\/reference(\/|$|\?)/.test(r.url())) return;
    const body = await r.text().catch(() => '');
    for (const k of ['"polygon"', '"bbox"', '"findings"', '"is_normal"', '"centroid"']) if (body.includes(k)) leaks.push(`${r.url()} ${k}`);
  });
  await start(page);
  expect(leaks).toEqual([]);
});

test('layout at 1920×1080: viewer ≈ 68%, rail ≥ 360 px', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await start(page);
  const stage = (await page.getByTestId('stage').boundingBox())!;
  const rail = (await page.getByRole('complementary').boundingBox())!;
  expect(stage.width / 1920).toBeGreaterThan(0.64);
  expect(stage.width / 1920).toBeLessThan(0.72);
  expect(rail.width).toBeGreaterThanOrEqual(360);
  await shot(page, 'm4-10-1920');
});
