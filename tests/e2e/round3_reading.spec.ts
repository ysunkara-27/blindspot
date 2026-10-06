// Round 3 reading-room e2e (student feedback + UX audit). Author: frontend-engineer (reading room).
// Default: the in-browser SYNTHETIC mock (/start?mock=1). E2E_REAL=1: the real OFFLINE API on real films (shots are
// named live-*.png and stay out of git). Covers: pathology-first marking, required confidence, the three rail groups
// and the normal call, the magnifier, the reference drawer before submit, the first-run tutorial, the search trace
// (legend, toggle, "not visited" rings), auto-fit on reveal, the controls bar and header, keyboard-only reading.
import { expect, test, type Page } from '@playwright/test';

const REAL = process.env.E2E_REAL === '1';
const START = REAL ? '/start?mock=0' : '/start?mock=1';
const SHOTS = 'tests/e2e/__screenshots__';
const shot = (page: Page, name: string) =>
  page.screenshot({ path: `${process.cwd().endsWith('frontend') ? '../' : ''}${SHOTS}/${REAL ? 'live-' : ''}r3-${name}.png` });

test.use({ viewport: { width: 1280, height: 800 } });

async function filmReady(page: Page) {
  await expect(page.getByTestId('film')).toBeVisible();
  await page.waitForFunction(() => {
    const img = document.querySelector<HTMLImageElement>('[data-testid=film]');
    return !!img && img.complete && img.naturalWidth > 0;
  });
}

async function start(page: Page, opts: { test?: boolean; query?: string } = {}) {
  await page.goto(`${START}${opts.query ?? ''}`);
  await page.getByTestId('name').fill('E2E round 3 (test)');
  if (opts.test) await page.getByTestId('practice-test').check();
  await page.getByTestId('start').click();
  await filmReady(page);
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
const filmSize = (page: Page) => page.getByTestId('film').evaluate((el: HTMLImageElement) => ({ w: el.width, h: el.height }));

async function markPos(page: Page, id: string) {
  const t = await page.locator(`[data-mark-id="${id}"]`).getAttribute('transform');
  const [, x, y] = t!.match(/translate\(([-\d.e]+) ([-\d.e]+)\)/)!;
  return { x: Number(x), y: Number(y) };
}

/** Pathology-first: pick the finding in the rail, click the film, say how sure. */
async function armAndMark(page: Page, label: string, fx: number, fy: number, conf: number | null) {
  const { w, h } = await filmSize(page);
  const v = await view(page);
  await page.getByTestId(`arm-${label}`).click();
  const [sx, sy] = v.toScreen(w * fx, h * fy);
  await page.mouse.click(Math.round(sx), Math.round(sy));
  const pop = page.getByTestId('mark-popover');
  await expect(pop).toBeVisible();
  await expect(pop).toHaveAttribute('data-mode', 'confidence');
  if (conf) {
    await pop.getByRole('radio', { name: `Confidence ${conf} of 5` }).click();
    await expect(pop).toBeHidden();
  }
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
  await page.getByTestId('submit').click();
  await expect(page.getByTestId('outcomes')).toBeVisible();
}

const boxesOverlap = (a: { x: number; y: number; width: number; height: number }, b: { x: number; y: number; width: number; height: number }) =>
  a.x < b.x + b.width - 0.5 && b.x < a.x + a.width - 0.5 && a.y < b.y + b.height - 0.5 && b.y < a.y + a.height - 0.5;

test('the rail reads in the order of thinking: point-to findings, whole-film findings, nothing abnormal', async ({ page }) => {
  await start(page);
  const rail = page.getByRole('complementary');
  const g1 = page.getByTestId('group-point');
  const g2 = page.getByTestId('group-whole');
  const g3 = page.getByTestId('group-normal');
  await expect(g1).toContainText('Findings you can point to');
  await expect(g1).toContainText('What do you see?');
  await expect(g2).toContainText('Findings of the whole film');
  await expect(g2).toContainText('No single spot to click; tick it if the whole film shows it');
  await expect(g3).toContainText('Nothing abnormal');
  await expect(g3).toContainText('Use this only if you see no findings at all');
  await expect(page.getByTestId('call-normal')).toHaveText(/Call it normal/);
  const [b1, b2, b3] = [await g1.boundingBox(), await g2.boundingBox(), await g3.boundingBox()];
  expect(b1!.y).toBeLessThan(b2!.y);
  expect(b2!.y).toBeLessThan(b3!.y);
  // Nine finding types to point at, each with an "i"; "not sure" stays an option; four whole-film findings.
  for (const id of ['pneumothorax', 'effusion', 'consolidation', 'atelectasis', 'nodule', 'mass', 'calcification', 'fracture', 'pleural_thickening']) {
    await expect(page.getByTestId(`arm-${id}`)).toBeVisible();
    await expect(g1.getByTestId(`info-${id}`)).toBeVisible();
  }
  await expect(page.getByTestId('arm-not_sure')).toHaveText('Not sure what it is');
  for (const id of ['cardiomegaly', 'emphysema', 'fibrosis', 'diffuse_nodule']) {
    await expect(page.getByTestId(`pattern-${id}`)).toBeVisible();
    await expect(g2.getByTestId(`info-${id}`)).toBeVisible();
  }
  await expect(rail).not.toContainText('Global findings');
  // Hints are free: no points cost anywhere.
  await expect(page.getByTestId('hints-left')).toHaveText('Hints — 3 left');
  await expect(page.getByTestId('hint-btn')).toHaveText(/Get a hint/);
  await expect(rail).not.toContainText(/\d+ points?|points? (each|off)|\bcosts?\b/i);
  // Nothing chosen yet: Submit is off and says what to do.
  await expect(page.getByTestId('submit')).toBeDisabled();
  await expect(page.getByTestId('submit-help')).toHaveText('Mark a finding, tick a whole-film one, or call it normal.');
  await shot(page, '01-rail-before-submit');

  // A whole-film finding needs its own confidence; nothing is preselected.
  await page.getByTestId('pattern-cardiomegaly').check();
  const conf = page.getByTestId('confidence-cardiomegaly');
  await expect(conf.getByRole('radio', { checked: true })).toHaveCount(0);
  await expect(page.getByTestId('submit-help')).toHaveText('Cardiomegaly needs a confidence.');
  await conf.getByRole('radio', { name: 'Confidence 2 of 5' }).click();
  await expect(page.getByTestId('submit')).toBeEnabled();
  await page.getByTestId('hint-btn').click();
  await expect(page.getByTestId('hint-list').locator('li')).toHaveCount(1);
  await expect(page.getByTestId('hints-left')).toHaveText('Hints — 2 left');
  await expect(rail).not.toContainText(/\d+ points?|points? (each|off)|\bcosts?\b/i);
  // The newest hint is scrolled into view, as a calm card.
  await expect(page.getByTestId('hint-list').locator('li').last()).toBeInViewport();
  await shot(page, '01b-rail-hint-and-whole-film');
});

test('pathology-first: pick what you see, click where, then say how sure (nothing preselected)', async ({ page }) => {
  await start(page);
  const { w, h } = await filmSize(page);
  const v = await view(page);
  await page.getByTestId('arm-nodule').click();
  await expect(page.getByTestId('arm-nodule')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('stage')).toHaveAttribute('data-armed', 'nodule');
  await expect(page.getByTestId('armed-prompt')).toContainText('Nodule');
  await expect(page.getByTestId('armed-prompt')).toContainText('click the film where you see it');
  // The armed label rides with the cursor over the film.
  const [sx, sy] = v.toScreen(w * 0.3, h * 0.42);
  await page.mouse.move(sx - 30, sy - 20);
  await page.mouse.move(sx, sy, { steps: 4 });
  await expect(page.getByTestId('armed-cursor')).toBeVisible();
  await expect(page.getByTestId('armed-cursor')).toHaveText('Nodule');
  await shot(page, '02-armed-cursor');

  await page.mouse.click(Math.round(sx), Math.round(sy));
  const pop = page.getByTestId('mark-popover');
  await expect(pop).toBeVisible();
  await expect(pop).toHaveAttribute('data-mode', 'confidence');
  await expect(pop.getByTestId('popover-label')).toHaveText('Nodule');
  await expect(pop).toContainText('How sure are you?');
  await expect(pop).toContainText('guessing');
  await expect(pop).toContainText('certain');
  await expect(pop.getByRole('radio')).toHaveCount(5);
  await expect(pop.getByRole('radio', { checked: true })).toHaveCount(0);
  await expect(page.locator('[data-mark-id="M1"]')).toHaveAttribute('data-label', 'nodule');
  const p = await markPos(page, 'M1');
  expect(Math.abs(p.x - w * 0.3)).toBeLessThanOrEqual(2);
  expect(Math.abs(p.y - h * 0.42)).toBeLessThanOrEqual(2);
  // One pick, one mark: the finding is put down again.
  await expect(page.getByTestId('arm-nodule')).toHaveAttribute('aria-pressed', 'false');
  // The popover sits beside the mark (with a connector), never on it.
  const pb = (await pop.boundingBox())!;
  expect(sx >= pb.x && sx <= pb.x + pb.width && sy >= pb.y && sy <= pb.y + pb.height).toBe(false);
  await expect(page.getByTestId('popover-connector')).toBeVisible();
  // Submit is off and says exactly what is missing.
  await expect(page.getByTestId('submit')).toBeDisabled();
  await expect(page.getByTestId('submit-help')).toHaveText('M1 needs a confidence.');
  await expect(page.getByTestId('mark-need-M1')).toHaveText('needs a confidence');
  await shot(page, '03-confidence-control');

  // A digit answers for the selected mark and closes the short popover.
  await page.keyboard.press('4');
  await expect(pop).toBeHidden();
  await expect(page.getByTestId('confidence-M1').getByRole('radio', { name: 'Confidence 4 of 5' })).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByTestId('submit')).toBeEnabled();
  await expect(page.getByTestId('submit-help')).toHaveCount(0);

  // Clicking the film with nothing picked still works: the popover asks what it is, then how sure.
  const [tx, ty] = v.toScreen(w * 0.66, h * 0.6);
  await page.mouse.click(Math.round(tx), Math.round(ty));
  await expect(pop).toBeVisible();
  await expect(pop).toHaveAttribute('data-mode', 'full');
  await expect(pop.getByRole('button', { name: 'Not sure what it is' })).toBeVisible();
  await expect(page.getByTestId('submit-help')).toHaveText('M2 needs a label and a confidence.');
  await pop.getByRole('button', { name: 'Mass', exact: true }).click();
  await expect(page.getByTestId('submit-help')).toHaveText('M2 needs a confidence.');
  await expect(pop.getByRole('radio', { checked: true })).toHaveCount(0);
  await pop.getByRole('radio', { name: 'Confidence 2 of 5' }).click();
  await pop.getByRole('button', { name: 'Done' }).click();
  await expect(pop).toBeHidden();
  await expect(page.getByTestId('mark-count')).toHaveText('2');
  await expect(page.getByTestId('submit')).toBeEnabled();

  // Esc puts a picked finding down without placing anything.
  await page.getByTestId('arm-effusion').click();
  await expect(page.getByTestId('armed-prompt')).toContainText('Pleural effusion');
  await page.mouse.move(2, 400);
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('armed-prompt')).toHaveCount(0);
  await expect(page.getByTestId('mark-count')).toHaveText('2');
});

test('with the magnifier on, the popover keeps off the lens and the mark', async ({ page }) => {
  await start(page);
  const { w, h } = await filmSize(page);
  const v = await view(page);
  await expect(page.getByTestId('loupe-toggle')).toHaveText(/Magnifier off/);
  await expect(page.getByTestId('loupe')).toBeHidden();
  await page.keyboard.press('m');
  await expect(page.getByTestId('loupe-toggle')).toHaveText(/Magnifier on/);
  // First time on: a short tip says what it is.
  await expect(page.getByTestId('magnifier-tip')).toContainText('2.5× lens that follows your cursor');
  const [sx, sy] = v.toScreen(w * 0.3, h * 0.4);
  await page.mouse.move(sx, sy, { steps: 3 });
  await expect(page.getByTestId('loupe')).toBeVisible();
  await page.mouse.click(Math.round(sx), Math.round(sy));
  const pop = page.getByTestId('mark-popover');
  await expect(pop).toBeVisible();
  const pb = (await pop.boundingBox())!;
  const nx = Math.min(Math.max(sx, pb.x), pb.x + pb.width);
  const ny = Math.min(Math.max(sy, pb.y), pb.y + pb.height);
  expect(Math.hypot(nx - sx, ny - sy)).toBeGreaterThanOrEqual(89); // lens radius 90
  // The lens stays on the mark while the popover is open.
  await expect(page.getByTestId('loupe')).toBeVisible();
  await shot(page, '04-popover-beside-lens');
  await page.keyboard.press('Escape');
  await page.keyboard.press('l'); // the old key is kept as an alias
  await expect(page.getByTestId('loupe-toggle')).toHaveText(/Magnifier off/);
  await expect(page.getByRole('complementary')).not.toContainText(/loupe/i);
});

test('normal call: its own confidence, groups 1 and 2 off, visible undo', async ({ page }) => {
  await start(page);
  await page.getByTestId('call-normal').click();
  const called = page.getByTestId('normal-called');
  await expect(called).toContainText('You called this film normal.');
  await expect(called).toContainText('How sure?');
  await expect(page.getByTestId('confidence-normal').getByRole('radio', { checked: true })).toHaveCount(0);
  await expect(page.getByTestId('submit')).toBeDisabled();
  await expect(page.getByTestId('submit-help')).toHaveText('The normal call needs a confidence.');
  // Groups 1 and 2 are switched off and say why.
  await expect(page.getByTestId('arm-nodule')).toBeDisabled();
  await expect(page.getByTestId('pattern-cardiomegaly')).toBeDisabled();
  await expect(page.getByTestId('group-point')).toContainText('Off while the film is called normal');
  await expect(page.getByTestId('mark-blocked')).toContainText('You called this film normal');
  // A click on the film places nothing.
  const { w, h } = await filmSize(page);
  const v = await view(page);
  const [sx, sy] = v.toScreen(w * 0.5, h * 0.5);
  await page.mouse.click(sx, sy);
  await page.waitForTimeout(350);
  await expect(page.getByTestId('mark-count')).toHaveText('0');
  await shot(page, '05-normal-called');
  // Undo is a visible button and switches everything back on.
  await expect(page.getByTestId('undo-normal')).toHaveText('Undo normal call');
  await page.getByTestId('undo-normal').click();
  await expect(page.getByTestId('arm-nodule')).toBeEnabled();
  await expect(page.getByTestId('pattern-cardiomegaly')).toBeEnabled();
  // Call it again by key; a digit sets the confidence of the normal call.
  await page.mouse.move(2, 400);
  await page.keyboard.press('n');
  await page.keyboard.press('5');
  await expect(page.getByTestId('confidence-normal').getByRole('radio', { name: 'Confidence 5 of 5' })).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByTestId('submit')).toBeEnabled();
  await page.getByTestId('submit').click();
  await expect(page.getByTestId('outcomes')).toBeVisible();
});

test('reference drawer: generic teaching material, usable before submit, from every "i"', async ({ page }) => {
  const submits: string[] = [];
  page.on('request', (r) => { if (/\/submit$/.test(new URL(r.url()).pathname)) submits.push(r.url()); });
  await start(page);
  const caseFilm = await page.getByTestId('film').getAttribute('src');
  await page.getByTestId('group-point').getByTestId('info-nodule').click();
  const drawer = page.getByTestId('reference-drawer');
  await expect(drawer).toBeVisible();
  await expect(drawer.getByRole('heading', { level: 2 })).toHaveText('Nodule');
  await expect(drawer).toContainText('What does this look like?');
  await expect(drawer.getByTestId('reference-definition')).not.toBeEmpty();
  await expect(drawer).toContainText('Key signs');
  await expect(drawer).toContainText('Often confused with');
  await expect(drawer).toContainText('Commonly mistaken normal structures');
  await expect(drawer.getByTestId('reference-note')).toHaveText('Examples from a separate reference set, not from your cases.');
  const examples = drawer.getByTestId('reference-examples').getByTestId('reference-example');
  if (!REAL || (await examples.count()) > 0) {
    expect(await examples.count()).toBeGreaterThanOrEqual(2);
    expect(await examples.count()).toBeLessThanOrEqual(3);
    await expect(drawer.getByTestId('reference-outline').first()).toBeVisible();
    await expect(examples.first().locator('figcaption')).not.toBeEmpty();
    // Never the film being read.
    for (const src of await examples.locator('img').evaluateAll((els) => els.map((e) => (e as HTMLImageElement).getAttribute('src')))) expect(src).not.toBe(caseFilm);
  }
  if (!REAL || (await drawer.getByTestId('reference-normals').count()) > 0) {
    await expect(drawer.getByTestId('reference-normals').getByTestId('reference-example')).toHaveCount(3);
  }
  const link = drawer.getByTestId('reference-radiopaedia');
  await expect(link).toHaveText(/Read more on Radiopaedia/);
  await expect(link).toHaveAttribute('href', /^https:\/\/radiopaedia\.org\//);
  await expect(link).toHaveAttribute('target', '_blank');
  // The drawer covers the rail, not the film.
  const db = (await drawer.boundingBox())!;
  const sb = (await page.getByTestId('stage').boundingBox())!;
  expect(db.x).toBeGreaterThanOrEqual(sb.x + sb.width - 1);
  await shot(page, '06-reference-drawer');
  // Keys typed in the drawer do not reach the reading room (N would call the film normal).
  await page.keyboard.press('n');
  await expect(page.getByTestId('normal-called')).toHaveCount(0);
  // "Often confused with" switches the card.
  await drawer.getByRole('button', { name: 'Mass', exact: true }).click();
  await expect(drawer.getByRole('heading', { level: 2 })).toHaveText('Mass');
  await page.keyboard.press('Escape');
  await expect(drawer).toHaveCount(0);
  expect(submits).toEqual([]); // all of this happened before any submit

  // From a whole-film finding, and from the mark popover.
  await page.getByTestId('group-whole').getByTestId('info-cardiomegaly').click();
  await expect(drawer.getByRole('heading', { level: 2 })).toHaveText('Cardiomegaly');
  await drawer.getByTestId('reference-close').click();
  const { w, h } = await filmSize(page);
  const v = await view(page);
  const [sx, sy] = v.toScreen(w * 0.31, h * 0.37);
  await page.mouse.click(Math.round(sx), Math.round(sy));
  const pop = page.getByTestId('mark-popover');
  await expect(pop).toBeVisible();
  await pop.getByTestId('info-effusion').click();
  await expect(drawer.getByRole('heading', { level: 2 })).toHaveText('Pleural effusion');
  await drawer.getByTestId('reference-close').click();
  // The mark is still being labelled: finish it and submit; the debrief rows offer "See examples".
  await pop.getByRole('button', { name: 'Mass', exact: true }).click();
  await pop.getByRole('radio', { name: 'Confidence 3 of 5' }).click();
  await pop.getByRole('button', { name: 'Done' }).click();
  await page.getByTestId('submit').click();
  await expect(page.getByTestId('outcomes')).toBeVisible();
  await expect(page.getByTestId('debrief-source')).toBeVisible({ timeout: 20_000 });
  const see = page.locator('[data-testid^="see-examples-"]').first();
  if (!REAL || (await see.count()) > 0) {
    await see.click();
    await expect(drawer).toBeVisible();
    await expect(drawer.getByTestId('reference-note')).toBeVisible();
  }
});

test('tutorial opens with ?tutorial=1: seven coach marks on the real controls, Next/Back/Skip, keyboard', async ({ page }) => {
  await start(page, { query: '&tutorial=1' });
  const tour = page.getByTestId('tutorial');
  const card = page.getByTestId('tutorial-card');
  await expect(tour).toBeVisible();
  await expect(tour).toHaveAttribute('data-step', 'film');
  await expect(page.getByTestId('tutorial-count')).toContainText('step 1 of 7');
  await expect(card).toContainText('wheel to zoom');
  await expect(page.getByTestId('tutorial-back')).toBeDisabled();
  const stage = page.getByTestId('stage');
  const ids = ['film', 'magnifier', 'pick', 'confidence', 'whole', 'hints', 'submit'];
  const targets: Record<string, string> = {
    film: '[data-tour="film"]', magnifier: '[data-tour="magnifier"]', pick: '[data-tour="pick"]', confidence: '[data-tour="confidence"]',
    whole: '[data-tour="whole-normal"]', hints: '[data-tour="hints"]', submit: '[data-tour="submit"]',
  };
  let onFilm = 0;
  for (const [i, id] of ids.entries()) {
    await expect(tour).toHaveAttribute('data-step', id);
    await expect(page.getByTestId('tutorial-count')).toContainText(`step ${i + 1} of 7`);
    // The ring sits on the real control.
    const ring = (await page.getByTestId('tutorial-ring').boundingBox())!;
    const target = (await page.locator(targets[id]).first().boundingBox())!;
    expect(Math.abs(ring.x - (target.x - 4))).toBeLessThan(3);
    expect(Math.abs(ring.y - (target.y - 4))).toBeLessThan(3);
    // The card never hides its own target, and sits on the film for at most one step.
    if (id !== 'film') await expect.poll(async () => boxesOverlap((await card.boundingBox())!, target), { message: `card over its target at step ${id}` }).toBe(false);
    const cb = (await card.boundingBox())!;
    if (boxesOverlap(cb, (await stage.boundingBox())!)) onFilm++;
    if (id === 'film') await shot(page, '07a-tutorial-step1');
    if (id === 'pick') {
      await expect(card).toContainText('Pick what you see, then click where it is');
      await shot(page, '07-tutorial-step3');
      // The real control stays usable while the tour is open.
      await page.getByTestId('arm-mass').click();
      await expect(page.getByTestId('arm-mass')).toHaveAttribute('aria-pressed', 'true');
      await page.getByTestId('arm-mass').click();
      await page.getByTestId('tutorial-next').focus();
    }
    if (i < ids.length - 1) {
      // Alternate the button and the keyboard.
      if (i % 2 === 0) await page.getByTestId('tutorial-next').click();
      else await page.keyboard.press('ArrowRight');
    }
  }
  expect(onFilm).toBeLessThanOrEqual(1);
  await expect(page.getByTestId('tutorial-next')).toHaveText('Start reading');
  await page.keyboard.press('ArrowLeft');
  await expect(tour).toHaveAttribute('data-step', 'hints');
  await expect(card).not.toContainText(/\d+ points?|\bcosts?\b/i);
  await page.getByTestId('tutorial-back').click();
  await expect(tour).toHaveAttribute('data-step', 'whole');
  await page.keyboard.press('Escape'); // skip
  await expect(tour).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem('bs_tutorial_done'))).toBe('1');
  expect(new URL(page.url()).searchParams.get('tutorial')).toBeNull();
  // Re-openable from "How to read here", next to Keys.
  await page.getByTestId('tutorial-button').click();
  await expect(tour).toHaveAttribute('data-step', 'film');
  await page.getByTestId('tutorial-skip').click();
  await expect(tour).toHaveCount(0);
});

test('tutorial stays closed under automation unless the page was loaded with ?tutorial=1', async ({ page }) => {
  await start(page);
  // The start page sends a first session to /read?tutorial=1 by itself; scripted runs must not get coach marks.
  await page.waitForTimeout(300);
  await expect(page.getByTestId('tutorial')).toHaveCount(0);
  await expect(page.getByTestId('keys-help')).toHaveCount(0);
  await expect(page.getByTestId('tutorial-button')).toHaveText('How to read here');
  await page.getByTestId('keys-button').click();
  const help = page.getByTestId('keys-help');
  await expect(help).toContainText('Magnifier on or off');
  await expect(help).not.toContainText(/loupe/i);
  await page.keyboard.press('Escape');
  await expect(help).toHaveCount(0);
});

test('search trace: only after submit, with a legend, an explainer, a remembered toggle and "not visited" rings', async ({ page }) => {
  await start(page);
  await sweep(page, 1200); // a small loop around the centre: the corners stay unvisited
  await expect(page.getByTestId('search-trace')).toHaveCount(0);
  await expect(page.getByTestId('film-legend')).toHaveCount(0);
  await expect(page.getByTestId('search-toggle')).toHaveCount(0);
  await callNormalAndSubmit(page);
  await expect(page.getByTestId('search-trace')).toBeVisible();
  const toggle = page.getByTestId('search-toggle');
  await expect(toggle).toHaveText('My search: on');
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  const legend = page.getByTestId('search-legend');
  await expect(legend).toContainText('Where your cursor spent time — a stand-in for where you looked');
  expect(await legend.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(13);
  expect(await page.getByTestId('proxy-note').evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(13);
  await expect(page.getByTestId('proxy-note')).toContainText('a proxy for where you looked');

  // Review areas the cursor did not visit: a dashed ring + "not visited" where the anatomy outlines place them.
  const areas = await page.getByTestId('search-areas').innerText();
  const rings = page.locator('[data-testid^="unvisited-"]:not([data-testid="unvisited-label"])');
  if (/did not visit/.test(areas)) {
    await expect(page.getByTestId('search-unvisited')).toBeVisible();
    if (await rings.count()) {
      await expect(page.getByTestId('unvisited-label').first()).toHaveText('not visited');
      expect(await rings.first().evaluate((el) => getComputedStyle(el).strokeDasharray)).not.toBe('none');
    } else {
      await expect(page.getByTestId('search-unvisited')).toContainText('Not visited:'); // listed in the legend only
    }
  }
  if (!REAL) expect(await rings.count()).toBeGreaterThan(0);
  await page.waitForTimeout(1300);
  await shot(page, '08-reveal-not-visited');

  // "What is this?" explains the proxy.
  await page.getByTestId('search-what').click();
  const why = page.getByTestId('search-explainer');
  await expect(why).toContainText('gorilla');
  await expect(why).toContainText('Drew, Võ & Wolfe, 2013');
  await expect(why).toContainText('It is a proxy, not a measurement.');
  await shot(page, '09-search-explainer');
  await page.keyboard.press('Escape');
  await expect(why).toHaveCount(0);

  // The toggle hides the trace and its rings, and is remembered for the next case.
  await toggle.click();
  await expect(toggle).toHaveText('My search: off');
  await expect(page.getByTestId('search-trace')).toHaveCount(0);
  await expect(rings).toHaveCount(0);
  await expect(page.getByTestId('search-legend')).toHaveCount(0);
  expect(await page.evaluate(() => localStorage.getItem('blindspot.showSearch'))).toBe('0');
  await page.getByTestId('next-case').click();
  await expect(page.getByTestId('case-index')).toHaveText(/Case 2/);
  await filmReady(page);
  await sweep(page, 500);
  await callNormalAndSubmit(page);
  await expect(page.getByTestId('search-toggle')).toHaveText('My search: off');
  await expect(page.getByTestId('search-trace')).toHaveCount(0);
  await page.getByTestId('search-toggle').click();
  await expect(page.getByTestId('search-trace')).toBeVisible();
});

test('the reveal fits the whole film when the learner was zoomed in', async ({ page }) => {
  await start(page);
  const v0 = await view(page);
  await page.mouse.move(v0.box.x + v0.box.width * 0.4, v0.box.y + v0.box.height * 0.4);
  await page.mouse.wheel(0, -732.4); // ×3
  await expect.poll(async () => (await view(page)).zoom).toBeGreaterThan(2.9);
  await expect(page.getByTestId('zoom-readout')).toHaveText('3.0×');
  // Mark what is under the cursor while zoomed, then submit.
  await page.getByTestId('arm-mass').click();
  await page.mouse.click(v0.box.x + v0.box.width * 0.4, v0.box.y + v0.box.height * 0.4);
  await expect(page.getByTestId('mark-popover')).toBeVisible();
  await page.keyboard.press('4');
  await page.waitForTimeout(500);
  expect((await view(page)).zoom).toBeGreaterThan(2.9); // still zoomed before the reveal
  await page.getByTestId('submit').click();
  await expect(page.getByTestId('reveal-layer')).toBeVisible();
  await expect.poll(async () => (await view(page)).zoom).toBeCloseTo(1, 2);
  // The whole film is inside the stage again.
  await page.waitForTimeout(600);
  const stage = (await page.getByTestId('stage').boundingBox())!;
  const film = (await page.getByTestId('film').boundingBox())!;
  expect(film.y).toBeGreaterThanOrEqual(stage.y - 1);
  expect(film.y + film.height).toBeLessThanOrEqual(stage.y + stage.height + 1);
  // After the reveal the learner can zoom again and the view stays where they put it.
  await page.mouse.move(stage.x + stage.width / 2, stage.y + stage.height / 2);
  await page.mouse.wheel(0, -300);
  await page.waitForTimeout(700);
  expect((await view(page)).zoom).toBeGreaterThan(1.3);
});

test('reveal: a missed finding with no wrong mark gets a halo, not an arrow; labels sit on pills; one merged list', async ({ page }) => {
  test.skip(REAL, 'needs the known synthetic case (syn_005: F1 mass, F2 nodule)');
  await start(page);
  await armAndMark(page, 'mass', 0.31, 0.37, 4); // finds F1, never visits F2
  await page.getByTestId('submit').click();
  await expect(page.getByTestId('reveal-layer')).toBeVisible();
  await expect(page.getByTestId('halo-F2')).toHaveCount(1);
  await expect(page.locator('[data-testid^="arrow-F"]')).toHaveCount(0);
  await expect(page.getByTestId('arrow-label')).toHaveCount(0);
  await expect(page.getByTestId('halo-F1')).toHaveCount(0);
  // Outline labels: text on a solid dark pill, no stroke halo on the text.
  const label = page.getByTestId('label-F2');
  await expect(label.locator('rect').first()).toBeVisible();
  expect(await label.locator('text').last().evaluate((el) => getComputedStyle(el).stroke)).toBe('none');
  await page.waitForTimeout(1500);
  await shot(page, '10-reveal-halo');

  // Score out of 100 with a one-sentence explanation.
  await expect(page.getByTestId('score')).toHaveText(/Score\s*\d+\s*\/\s*100/);
  await page.getByTestId('score-info-btn').click();
  await expect(page.getByTestId('score-info')).toContainText('70 for marking each finding in the right place, 20 for naming it, 10 for whole-film findings');
  // ONE list: each finding once, with name · location · outcome · one-line why. The search summary does not repeat it.
  const rows = page.getByTestId('outcomes').locator('li');
  await expect(rows).toHaveCount(2);
  await expect(page.getByTestId('outcome-F1')).toContainText('Mass');
  await expect(page.getByTestId('outcome-F1')).toContainText('Found it');
  await expect(page.getByTestId('outcome-F1')).toContainText('You marked it and named it.');
  await expect(page.getByTestId('outcome-F2')).toContainText('Nodule');
  await expect(page.getByTestId('outcome-F2')).toContainText('Never looked there');
  await expect(page.getByTestId('outcome-F2')).toContainText('No time spent there.');
  await expect(page.getByTestId('facts-card')).not.toContainText(/F1|F2|Mass|Nodule/);
  await expect(page.getByTestId('facts-card')).toContainText('Your cursor covered about');
  await expect(page.getByRole('complementary')).not.toContainText(/dwell|\b\d+ ?ms\b/i);
  // Order in the rail: the list, the search summary, then the tutor debrief.
  await expect(page.getByTestId('debrief-source')).toBeVisible({ timeout: 15_000 });
  const y = async (id: string) => (await page.getByTestId(id).boundingBox())!.y;
  expect(await y('outcomes')).toBeLessThan(await y('facts-card'));
  expect(await y('facts-card')).toBeLessThan(await y('debrief'));
  await page.getByTestId('outcomes').scrollIntoViewIfNeeded();
  await shot(page, '11-score-and-list');
});

test('arrows come only from a wrong mark, and identical labels are written once', async ({ page }) => {
  test.skip(REAL, 'needs the known synthetic case (syn_005)');
  await start(page);
  await armAndMark(page, 'nodule', 0.23, 0.7, 2); // a wrong mark, far from both findings
  await page.getByTestId('submit').click();
  await expect(page.getByTestId('reveal-layer')).toBeVisible();
  const arrows = page.locator('[data-testid^="arrow-F"]');
  expect(await arrows.count()).toBeGreaterThan(0);
  const texts = await page.getByTestId('arrow-label').evaluateAll((els) => els.map((e) => (e.getAttribute('data-label') ?? '').trim().toLowerCase()));
  expect(texts.length).toBeGreaterThan(0);
  expect(new Set(texts).size).toBe(texts.length);
  // A finding an arrow points at needs no halo.
  for (const id of await arrows.evaluateAll((els) => els.map((e) => e.getAttribute('data-testid')!.replace('arrow-', '')))) {
    await expect(page.getByTestId(`halo-${id}`)).toHaveCount(0);
  }
});

test('controls bar and header: labelled sliders, zoom buttons, invert, reset, View menu, strips off the film', async ({ page }) => {
  await start(page, { test: true });
  // Header: "Case 1 of N" with a progress bar you can see.
  await expect(page.getByTestId('case-index')).toHaveText(/^Case 1 of \d+$/);
  const bar = page.getByTestId('case-progress');
  await expect(bar).toBeVisible();
  const bb = (await bar.boundingBox())!;
  expect(bb.height).toBeGreaterThanOrEqual(4);
  expect(bb.width).toBeGreaterThanOrEqual(60);
  await expect(bar).toHaveAttribute('aria-valuenow', '0');
  // The magnifier is off by default in a test set too.
  await expect(page.getByTestId('loupe-toggle')).toHaveText(/Magnifier off/);
  await expect(page.getByTestId('loupe-toggle')).toHaveAttribute('aria-pressed', 'false');

  const tools = page.getByTestId('viewer-tools');
  await expect(tools).toContainText('Zoom');
  await expect(tools).toContainText('Brightness');
  await expect(tools).toContainText('Contrast');
  await expect(tools.getByRole('slider', { name: 'Brightness' })).toBeVisible();
  await expect(tools.getByRole('slider', { name: 'Contrast' })).toBeVisible();
  // The strips have their own rows: neither overlaps the film stage.
  const stage = (await page.getByTestId('stage').boundingBox())!;
  expect(boxesOverlap((await tools.boundingBox())!, stage)).toBe(false);
  expect(boxesOverlap((await page.getByTestId('viewer-strip').boundingBox())!, stage)).toBe(false);
  const film = (await page.getByTestId('film').boundingBox())!;
  expect(film.y).toBeGreaterThanOrEqual(stage.y);
  expect(film.y + film.height).toBeLessThanOrEqual(stage.y + stage.height);

  // Zoom readout with − / + buttons.
  await expect(page.getByTestId('zoom-readout')).toHaveText('1.0×');
  await expect(page.getByTestId('zoom-out')).toBeDisabled();
  await page.getByTestId('zoom-in').click();
  await page.getByTestId('zoom-in').click();
  await expect(page.getByTestId('zoom-readout')).toHaveText('1.6×');
  await page.getByTestId('zoom-out').click();
  await expect(page.getByTestId('zoom-readout')).toHaveText('1.3×');
  // Invert says its state; Reset view puts everything back.
  const invert = page.getByTestId('invert-toggle');
  await expect(invert).toHaveText('Invert: off');
  await invert.click();
  await expect(invert).toHaveText('Invert: on');
  expect(await page.getByTestId('film').evaluate((el) => (el as HTMLElement).style.filter)).toContain('invert(1)');
  await page.getByTestId('reset-view').click();
  await expect(invert).toHaveText('Invert: off');
  await expect(page.getByTestId('zoom-readout')).toHaveText('1.0×');

  // "Projector" left the header: it is "Large-screen mode" in the View menu.
  await expect(page.getByRole('banner')).not.toContainText('Projector');
  await page.getByTestId('view-menu').click();
  const item = page.getByTestId('projector-toggle');
  await expect(item).toContainText('Large-screen mode: off');
  await item.click();
  await expect(page.locator('html')).toHaveAttribute('data-projector', '1');
  await expect(item).toContainText('Large-screen mode: on');
  await item.click();
  await expect(page.locator('html')).not.toHaveAttribute('data-projector', '1');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('view-menu-list')).toHaveCount(0);
  await shot(page, '12-controls-and-header');
});

test('keyboard only: focus the film, move the crosshair, place a mark, label it, submit', async ({ page }) => {
  await start(page);
  const stage = page.getByTestId('stage');
  // Reach the film with Tab alone.
  for (let i = 0; i < 40; i++) {
    if (await stage.evaluate((el) => el === document.activeElement)) break;
    await page.keyboard.press('Tab');
  }
  await expect(stage).toBeFocused();
  expect(await stage.evaluate((el) => getComputedStyle(el).boxShadow)).not.toBe('none'); // visible focus ring
  await page.keyboard.press('ArrowRight'); // shows the crosshair at the centre
  const cross = page.getByTestId('crosshair');
  await expect(cross).toBeVisible();
  const x0 = Number(await cross.getAttribute('data-x'));
  const y0 = Number(await cross.getAttribute('data-y'));
  await page.keyboard.press('ArrowRight');
  const x1 = Number(await cross.getAttribute('data-x'));
  expect(x1).toBeGreaterThan(x0);
  await page.keyboard.press('Shift+ArrowUp');
  const y1 = Number(await cross.getAttribute('data-y'));
  expect(y0 - y1).toBeGreaterThan(3 * (x1 - x0)); // Shift = larger steps
  await page.keyboard.press('ArrowLeft');
  await page.keyboard.press('ArrowDown');
  // + and − zoom while the film has focus; the crosshair stays on screen.
  await page.keyboard.press('+');
  await expect(page.getByTestId('zoom-readout')).toHaveText('1.3×');
  await expect(cross).toBeInViewport();
  await page.keyboard.press('-');
  await expect(page.getByTestId('zoom-readout')).toHaveText('1.0×');
  const cx = Number(await cross.getAttribute('data-x'));
  const cy = Number(await cross.getAttribute('data-y'));
  await shot(page, '13-keyboard-crosshair');
  // Space places a mark at the crosshair and opens the popover with focus inside it.
  await page.keyboard.press('Space');
  const pop = page.getByTestId('mark-popover');
  await expect(pop).toBeVisible();
  const m = await markPos(page, 'M1');
  expect(Math.abs(m.x - cx)).toBeLessThanOrEqual(0.2);
  expect(Math.abs(m.y - cy)).toBeLessThanOrEqual(0.2);
  expect(await pop.evaluate((el) => el.contains(document.activeElement))).toBe(true);
  await page.keyboard.press('Enter'); // the focused label (the first one)
  await expect(page.locator('[data-mark-id="M1"]')).not.toHaveAttribute('data-label', '');
  await page.keyboard.press('3'); // how sure
  await expect(page.getByTestId('confidence-M1').getByRole('radio', { name: 'Confidence 3 of 5' })).toHaveAttribute('aria-checked', 'true');
  await page.keyboard.press('Escape'); // close the popover; focus returns to the film
  await expect(pop).toBeHidden();
  await expect(stage).toBeFocused();
  await expect(page.getByTestId('submit')).toBeEnabled();
  await page.keyboard.press('Control+Enter');
  await expect(page.getByTestId('outcomes')).toBeVisible();
  await expect(page.getByTestId('reveal-layer')).toBeVisible();
});

test('keyboard: an armed finding is placed with Enter at the crosshair', async ({ page }) => {
  await start(page);
  const stage = page.getByTestId('stage');
  await page.getByTestId('arm-effusion').focus();
  await page.keyboard.press('Enter');
  await expect(stage).toHaveAttribute('data-armed', 'effusion');
  await stage.focus();
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('ArrowDown');
  await expect(page.getByTestId('crosshair')).toContainText('Pleural effusion');
  await page.keyboard.press('Enter'); // with the crosshair showing, Enter places (it does not submit)
  await expect(page.locator('[data-mark-id="M1"]')).toHaveAttribute('data-label', 'effusion');
  await expect(page.getByTestId('outcomes')).toHaveCount(0);
  await page.keyboard.press('5');
  await expect(page.getByTestId('mark-popover')).toBeHidden();
  await expect(page.getByTestId('submit')).toBeEnabled();
});

test('anatomy overlay: dark lines on a light casing, names on hover, a compact legend', async ({ page }) => {
  await start(page);
  await sweep(page, 600);
  await callNormalAndSubmit(page);
  await page.waitForTimeout(1300);
  await page.mouse.move(2, 400);
  await page.keyboard.press('a');
  const layer = page.getByTestId('anatomy-layer');
  await expect(layer).toBeVisible();
  const zones = layer.locator('path[data-zone]');
  expect(await zones.count()).toBeGreaterThan(3);
  // Near-black stroke, with a light casing path underneath each outline.
  const stroke = await zones.first().evaluate((el) => getComputedStyle(el).stroke);
  const [r, g, b] = stroke.match(/\d+/g)!.map(Number);
  expect(Math.max(r, g, b)).toBeLessThan(40);
  const casing = await zones.first().evaluate((el) => getComputedStyle(el.previousElementSibling as Element).stroke);
  const [cr, cg, cb] = casing.match(/\d+/g)!.map(Number);
  expect(Math.min(cr, cg, cb)).toBeGreaterThan(200);
  await expect(page.getByTestId('anatomy-legend')).toContainText('Zone');
  await expect(page.getByTestId('anatomy-legend')).toContainText('Review area');
  const last = zones.last();
  const box = (await last.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page.getByTestId('zone-name')).not.toContainText('Point at a zone');
  await expect(page.getByTestId('zone-name')).not.toBeEmpty();
  await shot(page, '14-anatomy-overlay');
});
