// Round 5 — the viewer after clinician feedback. Author: frontend-engineer (viewer / reading room).
// Default: the in-browser SYNTHETIC mock (/start?mock=1). E2E_REAL=1: the real OFFLINE API on real films (shots are
// named live-*.png and stay out of git). Covers: the tools strip (Point · Draw · Caliper next to the magnifier, keys
// P / D / C, the caliper out of the View menu), a drawn outline → a labelled mark with a polygon in the submit body →
// the outline verdict chip on the reveal; "My search" off by default with its legend line and a remembered toggle;
// the signs layer ("Look for" pills, the S key, focusSign from the rail seam); the search tip after the first read.
import { expect, test, type Page } from '@playwright/test';

const REAL = process.env.E2E_REAL === '1';
const START = REAL ? '/start?mock=0' : '/start?mock=1';
const SHOTS = 'tests/e2e/__screenshots__';
const shot = (page: Page, name: string) =>
  page.screenshot({ path: `${process.cwd().endsWith('frontend') ? '../' : ''}${SHOTS}/${REAL ? 'live-' : ''}r5v-${name}.png` });

test.use({ viewport: { width: 1280, height: 800 } });

async function filmReady(page: Page) {
  await expect(page.getByTestId('film')).toBeVisible();
  await page.waitForFunction(() => {
    const img = document.querySelector<HTMLImageElement>('[data-testid=film]');
    return !!img && img.complete && img.naturalWidth > 0;
  });
}

async function start(page: Page, query = '') {
  await page.goto(`${START}${query}`);
  await page.getByTestId('name').fill('E2E round 5 (test)');
  await page.getByTestId('start').click();
  await filmReady(page);
}

async function view(page: Page) {
  const stage = page.getByTestId('stage');
  const box = (await stage.boundingBox())!;
  const [ox, oy, sc] = (await stage.getAttribute('data-view'))!.split(',').map(Number);
  return { box, sc, toScreen: (ix: number, iy: number) => [box.x + ox + ix * sc, box.y + oy + iy * sc] as const };
}
const filmSize = (page: Page) => page.getByTestId('film').evaluate((el: HTMLImageElement) => ({ w: el.width, h: el.height }));

/** Trace a circle of radius r (image px) around (cx, cy) with the mouse held down. */
async function trace(page: Page, cx: number, cy: number, r: number, n = 40) {
  const v = await view(page);
  const at = (i: number) => v.toScreen(cx + r * Math.cos((2 * Math.PI * i) / n), cy + r * Math.sin((2 * Math.PI * i) / n));
  const [x0, y0] = at(0);
  await page.mouse.move(x0, y0);
  await page.mouse.down();
  for (let i = 1; i <= n; i++) {
    const [x, y] = at(i);
    await page.mouse.move(x, y, { steps: 2 });
  }
  await page.mouse.up();
}

async function markPos(page: Page, id: string) {
  const t = await page.locator(`[data-mark-id="${id}"]`).getAttribute('transform');
  const [, x, y] = t!.match(/translate\(([-\d.e]+) ([-\d.e]+)\)/)!;
  return { x: Number(x), y: Number(y) };
}

async function sweep(page: Page, ms: number) {
  const v = await view(page);
  const t0 = Date.now();
  let i = 0;
  while (Date.now() - t0 < ms) {
    const a = (i++ / 40) * Math.PI;
    await page.mouse.move(v.box.x + v.box.width / 2 + Math.cos(a) * 110, v.box.y + v.box.height / 2 + Math.sin(a * 1.3) * 120);
    await page.waitForTimeout(16);
  }
}

async function callNormalAndSubmit(page: Page) {
  await page.mouse.move(2, 400);
  await page.keyboard.press('n');
  await page.keyboard.press('3');
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('reveal-layer')).toBeVisible();
}

type SubmitBody = { marks: { mark_id: string; x: number; y: number; label: string; tool?: string; polygon?: [number, number][] }[] };
const lastSubmit = (page: Page) => page.evaluate(() => (window as unknown as { __bsLastSubmit?: SubmitBody }).__bsLastSubmit!);

test('tools strip: Point · Draw · Caliper sit next to the magnifier with their keys; the caliper left the View menu', async ({ page }) => {
  await start(page);
  const seg = page.getByTestId('tool-segment');
  await expect(seg).toBeVisible();
  await expect(seg.locator('button')).toHaveText(['PointP', 'DrawD', 'CaliperC']);
  await expect(page.getByTestId('tool-mark')).toHaveAttribute('aria-pressed', 'true');
  // Left of the magnifier, in the same strip.
  const sb = (await seg.boundingBox())!;
  const lb = (await page.getByTestId('loupe-toggle').boundingBox())!;
  expect(sb.x + sb.width).toBeLessThanOrEqual(lb.x);
  expect(Math.abs(sb.y - lb.y)).toBeLessThan(12);
  await shot(page, '01-tools-strip');

  // D arms Draw (the strip says what to do), D again returns to Point; Esc does too.
  await page.mouse.move(2, 400);
  await page.keyboard.press('d');
  await expect(page.getByTestId('tool-draw')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('draw-prompt')).toContainText('press and drag to trace');
  await expect(page.getByTestId('stage')).toHaveAttribute('data-tool', 'draw');
  await page.keyboard.press('d');
  await expect(page.getByTestId('tool-mark')).toHaveAttribute('aria-pressed', 'true');
  await page.getByTestId('tool-draw').click();
  await expect(page.getByTestId('draw-prompt')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('tool-mark')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('draw-prompt')).toHaveCount(0);

  // The caliper is reachable from the strip (and by C): a drag measures in px on a film.
  await page.getByTestId('caliper-toggle').click();
  await expect(page.getByTestId('caliper-toggle')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('caliper-prompt')).toContainText('drag from edge to edge');
  const v = await view(page);
  const [ax, ay] = v.toScreen(100, 100);
  const [bx, by] = v.toScreen(200, 100);
  await page.mouse.move(ax, ay);
  await page.mouse.down();
  await page.mouse.move(bx, by, { steps: 5 });
  await page.mouse.up();
  await expect(page.getByTestId('caliper-readout')).toHaveText('100 px');
  await page.keyboard.press('c');
  await expect(page.getByTestId('tool-mark')).toHaveAttribute('aria-pressed', 'true');
  await page.keyboard.press('p');
  await expect(page.getByTestId('tool-mark')).toHaveAttribute('aria-pressed', 'true');
  // No caliper in the View menu any more.
  await page.getByTestId('view-menu').click();
  await expect(page.getByTestId('view-menu-list')).toBeVisible();
  await expect(page.getByTestId('caliper-menu')).toHaveCount(0);
  await page.keyboard.press('Escape');
  // The key sheet mentions Draw.
  await page.keyboard.press('?');
  await expect(page.getByTestId('keys-help')).toContainText('trace an outline');
  await page.keyboard.press('Escape');
});

test('draw: trace an outline → a labelled mark with a polygon in the submit body; the reveal shows the outline verdict chip', async ({ page }) => {
  await start(page);
  const { w, h } = await filmSize(page);
  // Mock syn_005: F1 is a mass in a 33 px box centred on (80.5, 95.5) of a 256 px film. A real film: a circle in the right mid zone.
  const cx = REAL ? w * 0.3 : 80.5;
  const cy = REAL ? h * 0.45 : 95.5;
  const r = REAL ? w * 0.07 : 22;
  await page.getByTestId('arm-mass').click();
  await page.mouse.move(2, 400);
  await page.keyboard.press('d');
  await expect(page.getByTestId('armed-prompt')).toContainText('trace around it');
  await trace(page, cx, cy, r);
  // The outline is a mark: the armed label applies, only "How sure?" is asked.
  const pop = page.getByTestId('mark-popover');
  await expect(pop).toBeVisible();
  await expect(pop).toHaveAttribute('data-mode', 'confidence');
  const outline = page.locator('[data-outline-id="M1"]');
  await expect(outline).toBeVisible();
  await expect(page.locator('[data-mark-id="M1"]')).toHaveAttribute('data-tool', 'draw');
  await expect(page.locator('[data-mark-id="M1"]')).toHaveAttribute('data-label', 'mass');
  const p0 = await markPos(page, 'M1');
  expect(Math.abs(p0.x - cx)).toBeLessThan(r * 0.2);
  expect(Math.abs(p0.y - cy)).toBeLessThan(r * 0.2);
  await pop.getByRole('radio', { name: 'Confidence 4 of 5' }).click();
  await expect(pop).toBeHidden();
  await expect(page.getByTestId('mark-count')).toHaveText('1');
  await shot(page, '02-outline-drawn');

  // Dragging the tag moves the whole outline; Backspace deletes it; a redraw inside the selected outline replaces it.
  const d0 = (await outline.locator('path').first().getAttribute('d'))!;
  const v = await view(page);
  const [tx, ty] = v.toScreen(p0.x, p0.y);
  await page.mouse.move(tx, ty);
  await page.mouse.down();
  await page.mouse.move(tx + 30, ty + 10, { steps: 6 });
  await page.mouse.up();
  const p1 = await markPos(page, 'M1');
  expect(p1.x - p0.x).toBeGreaterThan(20 / v.sc);
  expect(await outline.locator('path').first().getAttribute('d')).not.toBe(d0);
  // Move it back for the grade.
  await page.mouse.move(tx + 30, ty + 10);
  await page.mouse.down();
  await page.mouse.move(tx, ty, { steps: 6 });
  await page.mouse.up();
  await page.keyboard.press('Escape'); // deselect (the popover is closed; this clears the selection)
  // A second outline (the Draw tool stays on), then delete it.
  await expect(page.getByTestId('tool-draw')).toHaveAttribute('aria-pressed', 'true');
  await trace(page, cx + w * 0.3, cy, r * 0.8);
  await expect(page.locator('[data-outline-id="M2"]')).toBeVisible();
  await expect(page.getByTestId('mark-popover')).toHaveAttribute('data-mode', 'full'); // nothing armed: label + confidence asked
  await page.keyboard.press('Backspace'); // deletes the selected mark
  await expect(page.getByTestId('mark-popover')).toBeHidden();
  await expect(page.locator('[data-outline-id="M2"]')).toHaveCount(0);
  await expect(page.getByTestId('mark-count')).toHaveText('1');

  // Submit: the body carries the polygon (≤ 120 points, in image px) and tool "draw".
  await page.mouse.move(2, 400);
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('reveal-layer')).toBeVisible({ timeout: 15_000 });
  const body = await lastSubmit(page);
  expect(body.marks).toHaveLength(1);
  expect(body.marks[0]).toMatchObject({ mark_id: 'M1', label: 'mass', tool: 'draw' });
  const poly = body.marks[0].polygon!;
  expect(poly.length).toBeGreaterThanOrEqual(3);
  expect(poly.length).toBeLessThanOrEqual(120);
  for (const [x, y] of poly) { expect(x).toBeGreaterThanOrEqual(0); expect(x).toBeLessThanOrEqual(w); expect(y).toBeGreaterThanOrEqual(0); expect(y).toBeLessThanOrEqual(h); }
  // The reveal keeps the outline in amber and grades it: the chip says how the outline sits on the finding.
  await expect(outline).toBeVisible();
  const verdict = await outline.getAttribute('data-verdict');
  expect(['on_target', 'partly', 'too_broad', 'off']).toContain(verdict);
  if (!REAL) {
    expect(verdict).toBe('on_target');
    await expect(page.getByTestId('verdict-M1')).toHaveText('On target');
  } else if (verdict !== 'off') {
    await expect(page.getByTestId('verdict-M1')).toHaveText({ on_target: 'On target', partly: 'Partly on it', too_broad: 'Too broad' }[verdict!]!);
  }
  await page.waitForTimeout(1300);
  await shot(page, '03-outline-reveal');
});

test('My search is off by default: no trace, no rings, a legend line that says so; the toggle turns it on and is remembered', async ({ page }) => {
  await start(page);
  await sweep(page, 800);
  await callNormalAndSubmit(page);
  const toggle = page.getByTestId('search-toggle');
  await expect(toggle).toHaveText('My search: off');
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByTestId('search-trace')).toHaveCount(0);
  await expect(page.locator('[data-testid^="unvisited-"]')).toHaveCount(0);
  const legend = page.getByTestId('search-legend');
  await expect(legend).toBeVisible();
  await expect(legend).toHaveText('My search is off — turn it on to see where you looked');
  await expect(legend).toHaveAttribute('data-search', 'off');
  await page.waitForTimeout(1300);
  await shot(page, '04-reveal-search-off');
  await toggle.click();
  await expect(toggle).toHaveText('My search: on');
  await expect(page.getByTestId('search-trace')).toBeVisible();
  await expect(legend).toContainText('Where your cursor spent time');
  expect(await page.evaluate(() => localStorage.getItem('blindspot.showSearch'))).toBe('1');
  // Remembered on the next case.
  await page.getByTestId('next-case').click();
  await filmReady(page);
  await sweep(page, 500);
  await callNormalAndSubmit(page);
  await expect(page.getByTestId('search-toggle')).toHaveText('My search: on');
  await expect(page.getByTestId('search-trace')).toBeVisible();
});

test('signs layer: ≥ 1 sign with a "Look for" pill on the reveal; S and the toggle hide it; focusSign pulses one', async ({ page }) => {
  await start(page);
  await callNormalAndSubmit(page);
  const signs = page.locator('[data-testid="signs-layer"] > g[data-testid^="sign-"]');
  // The real API may serve a normal film (no findings, no signs); the mock's first case always has them.
  if (REAL && (await page.getByTestId('signs-toggle').count()) === 0) {
    test.info().annotations.push({ type: 'note', description: 'no signs on this film (normal case or backend without signs)' });
    return;
  }
  const toggle = page.getByTestId('signs-toggle');
  await expect(toggle).toHaveText(/Signs: on/);
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  await expect(signs.first()).toBeVisible();
  expect(await signs.count()).toBeGreaterThanOrEqual(1);
  const first = signs.first();
  const id = (await first.getAttribute('data-testid'))!.slice('sign-'.length);
  await expect(page.getByTestId(`sign-label-${id}`)).toContainText('Look for:');
  // Cyan, dashed for a line-like sign; a dark casing under it.
  const kind = await first.getAttribute('data-sign-kind');
  if (kind === 'polyline' || kind === 'polygon' || kind === 'circle') {
    const line = first.locator('path, circle').nth(1);
    expect(await line.evaluate((el) => getComputedStyle(el).strokeDasharray)).not.toBe('none');
  }
  // Hovering (the pill is the easiest part to hit) shows the sign's text.
  await page.getByTestId(`sign-label-${id}`).locator('rect').hover({ force: true });
  await expect(page.getByTestId(`sign-tip-${id}`)).toBeVisible();
  await page.waitForTimeout(1300);
  await shot(page, '05-reveal-signs');
  // The rail seam: focusSign(id) marks the sign focused (and pulses it) for 1.5 s.
  await page.evaluate((sid) => (window as unknown as { __bsFocusSign?: (id: string) => void }).__bsFocusSign?.(sid), id);
  await expect(first).toHaveAttribute('data-focused', '1');
  await expect(first).not.toHaveAttribute('data-focused', '1', { timeout: 4000 });
  // S hides the layer; the toggle brings it back.
  await page.mouse.move(2, 400);
  await page.keyboard.press('s');
  await expect(toggle).toHaveText(/Signs: off/);
  await expect(page.getByTestId('signs-layer')).toHaveCount(0);
  await toggle.click();
  await expect(toggle).toHaveText(/Signs: on/);
  await expect(signs.first()).toBeVisible();
});

test('the search tip: one coach mark on "My search" after the first submitted read (with ?tutorial=1); Next turns it on', async ({ page }) => {
  await start(page, '&tutorial=1');
  const tour = page.getByTestId('tutorial');
  await expect(tour).toHaveAttribute('data-step', 'film');
  // Step 3 mentions Draw.
  await page.getByTestId('tutorial-next').click();
  await page.getByTestId('tutorial-next').click();
  await expect(tour).toHaveAttribute('data-step', 'pick');
  await expect(page.getByTestId('tutorial-card')).toContainText('trace an outline around it with D');
  await page.getByTestId('tutorial-skip').click();
  await expect(tour).toHaveCount(0);
  await callNormalAndSubmit(page);
  await expect(tour).toHaveAttribute('data-step', 'search');
  await expect(tour).toHaveAttribute('data-tour-kind', 'tip');
  const card = page.getByTestId('tutorial-card');
  await expect(card).toContainText('See how you looked');
  await expect(card).toContainText('Turn on My search to replay your cursor over the film and see which areas you never visited.');
  await expect(page.getByTestId('tutorial-count')).toHaveText('After your first read');
  // The ring sits on the toggle.
  const ring = (await page.getByTestId('tutorial-ring').boundingBox())!;
  const target = (await page.getByTestId('search-toggle').boundingBox())!;
  expect(Math.abs(ring.x - (target.x - 4))).toBeLessThan(3);
  expect(Math.abs(ring.y - (target.y - 4))).toBeLessThan(3);
  await expect(page.getByTestId('search-toggle')).toHaveText('My search: off');
  await shot(page, '06-search-tip');
  await expect(page.getByTestId('tutorial-next')).toHaveText('Turn it on');
  await page.getByTestId('tutorial-next').click();
  await expect(tour).toHaveCount(0);
  await expect(page.getByTestId('search-toggle')).toHaveText('My search: on');
  expect(await page.evaluate(() => localStorage.getItem('bs_search_tip_done'))).toBe('1');
  // Once only: the next read shows no tip.
  await page.getByTestId('next-case').click();
  await filmReady(page);
  await callNormalAndSubmit(page);
  await page.waitForTimeout(300);
  await expect(tour).toHaveCount(0);
});

test('under automation without ?tutorial=1 the first reveal shows no tip', async ({ page }) => {
  await start(page);
  await callNormalAndSubmit(page);
  await page.waitForTimeout(300);
  await expect(page.getByTestId('tutorial')).toHaveCount(0);
  await expect(page.getByTestId('search-toggle')).toHaveText('My search: off');
});
