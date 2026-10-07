// Round 5 (signs) — the rail and the reference drawer. Author: frontend-engineer (rail/reference side).
// Clinician feedback: "in the tutor debrief, show images not in the dataset that show the pathology, and links to
// Radiopaedia"; "include common signs the tutor mentions to look for, drawn and explained".
// Default: the in-browser SYNTHETIC mock (/start?mock=1). E2E_REAL=1: the real OFFLINE API of the throwaway stack on
// real films (shots named live-*.png, gitignored). Where the backend's round-5 shapes are not loaded yet, they are
// injected with page.route: GET /api/signs (schematics) and `signs` on the reveal findings (from each finding's bbox).
import { expect, test, type Page, type Route } from '@playwright/test';

const REAL = process.env.E2E_REAL === '1';
const START = REAL ? '/start?mock=0' : '/start?mock=1';
const SHOTS = 'tests/e2e/__screenshots__';
const shot = (page: Page, name: string, films = false) =>
  page.screenshot({ path: `${process.cwd().endsWith('frontend') ? '../' : ''}${SHOTS}/${films && REAL ? 'live-' : ''}r5-${name}.png` });

test.use({ viewport: { width: 1280, height: 800 } });

const SVG = (body: string) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><rect x="20" y="20" width="160" height="160" fill="none" stroke="#8C99A6"/>${body}</svg>`;
/** Twelve stand-in schematics, two of them not tied to a graded finding (what the backend's content will hold). */
const SCHEMATICS = [
  ['visceral_pleural_line', 'Visceral pleural line', ['pneumothorax']], ['deep_sulcus', 'Deep sulcus sign', ['pneumothorax']],
  ['meniscus', 'Meniscus sign', ['effusion']], ['blunted_angle', 'Blunted costophrenic angle', ['effusion', 'pleural_thickening']],
  ['air_bronchogram', 'Air bronchogram', ['consolidation']], ['silhouette_sign', 'Silhouette sign', ['consolidation', 'atelectasis']],
  ['golden_s', 'Golden S sign', ['atelectasis', 'mass']], ['spiculated_edge', 'Spiculated edge', ['nodule', 'mass']],
  ['popcorn_calcification', 'Popcorn calcification', ['calcification']], ['cortical_step', 'Cortical step-off', ['fracture']],
  ['cardiothoracic_ratio', 'Cardiothoracic ratio', ['cardiomegaly']], ['flat_diaphragm', 'Flattened diaphragm', ['emphysema']],
  ['honeycombing', 'Honeycombing', ['fibrosis']], ['miliary_pattern', 'Miliary pattern', ['diffuse_nodule']],
  ['kerley_b', 'Kerley B lines', []], ['bat_wing', 'Bat-wing opacity', []],
].map(([id, name, labels]) => ({
  id, name, labels, modality: 'cxr', description: `What to look for: ${String(name).toLowerCase()}.`, review_status: 'ai_draft',
  radiopaedia_url: `https://radiopaedia.org/articles/${String(id).replace(/_/g, '-')}`, svg: SVG(`<path d="M40 150 Q100 40 160 150" fill="none" stroke="#35C9DD" stroke-width="3"/>`),
}));
const FIRST_SIGN: Record<string, [string, string]> = {
  pneumothorax: ['visceral_pleural_line', 'Visceral pleural line'], effusion: ['meniscus', 'Meniscus'], consolidation: ['air_bronchogram', 'Air bronchogram'],
  atelectasis: ['silhouette_sign', 'Silhouette sign'], nodule: ['spiculated_edge', 'Edge of the lesion'], mass: ['spiculated_edge', 'Edge of the lesion'],
  calcification: ['popcorn_calcification', 'Dense calcium'], fracture: ['cortical_step', 'Cortical step'], pleural_thickening: ['blunted_angle', 'Pleural band'],
  cardiomegaly: ['cardiothoracic_ratio', 'Heart width'],
};

/** REAL only: until the backend's round-5 routes land, serve the schematics and draw one sign per reveal finding. */
async function withSigns(page: Page) {
  if (!REAL) return;
  await page.route((u) => u.pathname.endsWith('/api/signs'), async (route: Route) => {
    const res = await route.fetch().catch(() => null);
    if (res && res.ok()) return route.fulfill({ response: res });
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SCHEMATICS) });
  });
  await page.route((u) => /\/api\/attempts\/[^/]+\/(submit|result)$/.test(u.pathname), async (route: Route) => {
    const res = await route.fetch();
    if (!res.ok()) return route.fulfill({ response: res });
    const json = (await res.json()) as { reveal?: { findings?: Record<string, unknown>[] }; facts_card?: { lines: string[] } };
    for (const f of json.reveal?.findings ?? []) {
      if (Array.isArray(f.signs)) continue;
      const [sid, name] = FIRST_SIGN[String(f.label)] ?? ['edge', 'Edge of the finding'];
      const b = f.bbox as [number, number, number, number];
      const cx = (b[0] + b[2]) / 2;
      const cy = (b[1] + b[3]) / 2;
      f.signs = [{ id: `${f.finding_id}:${sid}`, name, text: 'Compare the edge with the lung around it.', geometry: { kind: 'circle', points: [[cx, cy]], radius: Math.max(12, (b[2] - b[0]) / 2) }, schematic: sid }];
    }
    await route.fulfill({ response: res, json });
  });
}

async function filmReady(page: Page) {
  await expect(page.getByTestId('film')).toBeVisible();
  await page.waitForFunction(() => {
    const img = document.querySelector<HTMLImageElement>('[data-testid=film]');
    return !!img && img.complete && img.naturalWidth > 0;
  });
}

async function start(page: Page) {
  await page.goto(START);
  await page.getByTestId('name').fill('E2E round 5 (test)');
  await page.getByTestId('start').click();
  await filmReady(page);
}

/** Call the film normal (needs no knowledge of the case) and submit. */
async function submitNormal(page: Page) {
  await page.mouse.move(2, 400);
  await page.keyboard.press('n');
  const conf = page.getByRole('radio', { name: /Confidence 3 of 5/ }).first();
  if (await conf.isVisible().catch(() => false)) await conf.click();
  else await page.keyboard.press('3');
  await page.getByTestId('submit').click();
  await expect(page.getByTestId('outcomes')).toBeVisible();
}

/** Submit normal until a film with a focal finding (an F1 row) comes up; the mock's first practice film has two. */
async function reachAbnormal(page: Page, max = 12) {
  for (let i = 0; i < max; i++) {
    await submitNormal(page);
    if (await page.getByTestId('outcome-F1').isVisible().catch(() => false)) return;
    await page.getByTestId('next-case').click();
    await filmReady(page);
  }
  throw new Error('no abnormal film in the first cases');
}

test('debrief row: "Look for" chips focus the sign on the film, two example films from the reference set, Radiopaedia link', async ({ page, request }) => {
  await withSigns(page);
  await start(page);
  await reachAbnormal(page);
  const row = page.getByTestId('outcome-F1');
  const label = (await row.getByRole('button', { name: /What does .* look like/ }).getAttribute('data-testid'))!.replace('info-', '');

  // The facts list carries the backend's "Look for" line when it is there (the mock always sends one).
  if (!REAL) await expect(page.getByTestId('facts-look-for').first()).toContainText(/^Look for:/);

  const debrief = page.getByTestId('debrief');
  await expect(debrief).toBeVisible();
  const teach = page.getByTestId('finding-teaching-F1');
  await expect(teach).toBeAttached({ timeout: 20_000 });
  await teach.scrollIntoViewIfNeeded();

  // (1) Signs on the film: one chip per reveal sign, "Look for: <name>", the sign's text as the tooltip.
  const chips = teach.getByTestId(/^sign-chip-/);
  await expect(chips.first()).toBeVisible();
  await expect(chips.first()).toContainText(/^Look for:/);
  expect((await chips.first().getAttribute('title'))!.length).toBeGreaterThan(10);

  // (2) Example films: two thumbnails, not from the learner's cases, each captioned "Separate reference set".
  const thumbs = teach.getByTestId('example-thumb');
  await expect(thumbs).toHaveCount(2, { timeout: 15_000 });
  for (const t of await thumbs.all()) {
    await expect(t).toContainText('Separate reference set');
    const box = (await t.locator('span').first().boundingBox())!;
    expect(Math.round(box.height)).toBe(120);
  }
  const caseAttr = await page.getByTestId('stage').getAttribute('data-case').catch(() => null);
  if (caseAttr) for (const t of await thumbs.all()) expect(await t.getAttribute('data-case')).not.toBe(caseAttr);
  await expect(teach.getByTestId('example-outline').first()).toBeVisible();

  // (3) Read more on Radiopaedia: the teaching card's link, external, link-only.
  const link = teach.getByTestId('radiopaedia-F1');
  const expected = REAL
    ? ((await (await request.get(`${process.env.E2E_API ?? 'http://127.0.0.1:8000/api'}/reference/${label}`)).json()) as { radiopaedia_url: string | null }).radiopaedia_url
    : { mass: 'https://radiopaedia.org/articles/pulmonary-mass', nodule: 'https://radiopaedia.org/articles/pulmonary-nodule' }[label] ?? null;
  if (expected) {
    await expect(link).toHaveAttribute('href', expected);
    await expect(link).toHaveAttribute('target', '_blank');
    expect(await link.getAttribute('rel')).toMatch(/noopener/);
    await expect(teach).toContainText('Links only; Radiopaedia content is not reproduced here.');
  } else {
    await expect(link).toHaveCount(0);
  }
  await page.waitForTimeout(1400); // the rail's settle animation (SPEC §14.3) finishes before the shot
  await shot(page, '01-debrief-row', true);

  // Clicking a chip calls into the viewer: that sign gets the focused attribute on the film (layer turned on if off).
  const toggle = page.getByTestId('signs-toggle');
  if (await toggle.isVisible().catch(() => false) && (await toggle.getAttribute('aria-pressed')) === 'true') await toggle.click();
  const id = (await chips.first().getAttribute('data-testid'))!.replace('sign-chip-', '');
  await chips.first().click();
  await expect(page.getByTestId(`sign-${id}`)).toHaveAttribute('data-focused', '1');
  await shot(page, '02-sign-focused', true);

  // A thumbnail opens the reference drawer at that label; "Signs to know" lists the on-film sign first.
  await thumbs.first().click();
  const drawer = page.getByTestId('reference-drawer');
  await expect(drawer).toBeVisible();
  await expect(drawer).toHaveAttribute('data-label', label);
  const signs = drawer.getByTestId('signs-to-know');
  await signs.scrollIntoViewIfNeeded();
  await expect(signs).toBeVisible();
  await expect(signs).toContainText('Signs to know');
  await expect(signs.getByTestId('sign-provenance')).toHaveText('Schematic drawings, AI-drafted, not yet reviewed');
  const cards = signs.getByTestId('sign-card');
  expect(await cards.count()).toBeGreaterThanOrEqual(1);
  await expect(cards.first().getByTestId('sign-schematic-svg').locator('svg')).toBeVisible();
  await expect(cards.first()).toContainText('Drawn on your film');
  await expect(drawer).toContainText('It says nothing about the film you are reading.');
  await shot(page, '03-drawer-signs', true);
});

test('pre-submit: the "i" drawer shows "Signs to know" with drawn, explained signs and no word about this case', async ({ page }) => {
  await withSigns(page);
  await start(page);
  await page.getByTestId('group-point').getByTestId('info-pneumothorax').click();
  const drawer = page.getByTestId('reference-drawer');
  await expect(drawer).toBeVisible();
  const signs = drawer.getByTestId('signs-to-know');
  await signs.scrollIntoViewIfNeeded();
  await expect(signs).toBeVisible();
  await expect(signs.getByTestId('sign-card').first()).toContainText('Visceral pleural line');
  await expect(signs.getByTestId('sign-card').first().getByTestId('sign-schematic-svg').locator('svg')).toBeVisible();
  await expect(signs.getByTestId('sign-card').first().getByTestId('sign-radiopaedia')).toHaveAttribute('href', /^https:\/\/radiopaedia\.org\//);
  await expect(signs).not.toContainText('Drawn on your film');
  // Nothing about the case leaks: no reveal, no outlines, no sign on the film before submit.
  await expect(page.getByTestId('signs-layer')).toHaveCount(0);
  await expect(page.getByTestId('outcomes')).toHaveCount(0);
  await shot(page, '04-presubmit-signs');
});

test('/reference has a Signs tab listing every schematic, including ones not graded yet', async ({ page }) => {
  await withSigns(page);
  await page.goto(`/reference${REAL ? '?mock=0' : '?mock=1'}`);
  await expect(page.getByRole('heading', { level: 1, name: 'Finding library' })).toBeVisible();
  await page.getByTestId('ref-tab-signs').click();
  await expect(page).toHaveURL(/tab=signs/);
  const tab = page.getByTestId('signs-tab');
  await expect(tab).toBeVisible();
  const cards = tab.getByTestId('sign-card');
  expect(await cards.count()).toBeGreaterThanOrEqual(10);
  for (const c of (await cards.all()).slice(0, 3)) await expect(c.getByTestId('sign-schematic-svg').locator('svg')).toBeVisible();
  await expect(tab.getByTestId('sign-provenance')).toHaveText('Schematic drawings, AI-drafted, not yet reviewed');
  const other = tab.getByTestId('signs-other');
  await expect(other).toBeVisible();
  await expect(tab).toContainText('Not graded in Blindspot yet; worth knowing');
  await expect(other).toContainText(/Bat-wing|Kerley/);
  await shot(page, '05-reference-signs-tab');
  // The Findings tab keeps the library, now with "Signs to know" under an entry.
  await page.getByTestId('ref-tab-findings').click();
  await expect(page.getByTestId('ref-index')).toBeVisible();
  const entry = page.locator('#pneumothorax');
  await entry.scrollIntoViewIfNeeded();
  await expect(entry.getByTestId('signs-to-know')).toBeVisible();
  await expect(entry.getByTestId('sign-card').first()).toContainText('Visceral pleural line');
});
