// Round 4 (volumetric) — the pages around the reading room. Author: frontend-engineer (pages/app/dashboard/reference).
// Scan-type chips on the start screen, the CT session body, the provenance pill, the library grouped by scan type with
// a decoded CT slice, the reading-log scan-type switch, and the About provenance table.
// Runs against the REAL offline API of the throwaway stack (?mock=0). Where the backend's volumetric shapes are not
// loaded yet, the contract payloads (docs/PROGRESS.md BACKEND CONTRACT (volumetric)) are injected with page.route and
// the CT voxels/mask come from the synthetic fixtures in pipeline/tests/fixtures/synthetic (labelled synthetic).
import { expect, test, type APIRequestContext, type Page, type Route } from '@playwright/test';

const API = process.env.E2E_API ?? 'http://127.0.0.1:8000/api';
const ROOT = process.cwd().endsWith('frontend') ? '..' : '.';
const SHOTS = `${ROOT}/tests/e2e/__screenshots__`;
const FIX = `${ROOT}/pipeline/tests/fixtures/synthetic`;
const BANNED = /hackathon|\bdemo\b|\bpilot\b|judges|\bSUS\b|private preview/i;

test.use({ viewport: { width: 1280, height: 800 } });

type Stored = { sessionId: string; learnerId: string; mode: string };
const storedSession = (page: Page) => page.evaluate(() => (JSON.parse(sessionStorage.getItem('blindspot.session') ?? '{}').state?.session ?? null) as Stored | null);

/** The real /api/health with `cases_by_modality` added (the backend's volumetric shape), so chips light up. */
async function withModalities(page: Page, by: Record<string, number>) {
  await page.route('**/api/health', async (route) => {
    const res = await route.fetch();
    const json = (await res.json()) as Record<string, unknown>;
    await route.fulfill({ response: res, json: { ...json, modalities: Object.keys(by).filter((k) => by[k] > 0), cases_by_modality: by } });
  });
}

const PROV_CT = { dataset: 'Medical Segmentation Decathlon, Task07 Pancreas', segmented_by: 'an abdominal radiologist (single reader)', readers: 1, institution: 'Memorial Sloan Kettering Cancer Center', license: 'CC BY-SA 4.0', grade: 'radiologist' };
const PROV_TEXT_CT = 'Segmented by an abdominal radiologist (single reader) · Medical Segmentation Decathlon, Task07 Pancreas';
const PROV_TEXT_CXR = 'Outlined by three board-certified radiologists · ChestX-Det';

/** A /api/reference payload with one CT entry whose example is the synthetic fixture volume vol_001 (shape 16×64×64). */
async function withCtReference(page: Page) {
  await page.route('**/api/reference', async (route) => {
    const res = await route.fetch();
    const json = (await res.json()) as { labels: unknown[]; normal_examples: unknown[] };
    const ct = {
      label: 'pancreatic_tumour', display: 'Pancreatic tumour', kind: 'focal', modality: 'ct',
      one_liner: 'A focal mass in the pancreas, usually hypoenhancing against the gland on contrast CT.',
      key_signs: ['Hypoenhancing mass in the gland', 'Abrupt duct cut-off with upstream dilatation'], mimics: ['Focal pancreatitis', 'Unopacified bowel loop'],
      commonly_confused_with: ['liver_tumour'], search_tip: 'Follow the gland head to tail on every slice; compare the enhancement of each part.', radiopaedia_url: null, review_status: 'ai_draft',
      examples: [{
        case_id: 'vol_001', image_url: '/api/cases/vol_001/image', width: 64, height: 64, modality: 'ct',
        volume_url: '/api/cases/vol_001/volume', mask_url: '/api/cases/vol_001/maskvol', shape: [16, 64, 64], spacing: [3, 1.5, 1.5], window: { wc: 50, ww: 400 },
        provenance: PROV_CT,
        finding: { finding_id: 'vol_001#F1', polygon: null, bbox: [20, 32, 29, 41], relative_location: 'middle slices of the volume', side: 'right', slice_range: [6, 10], measure: { long_mm: 13.5, slice: 8 }, label_values: [2] },
      }],
    };
    // Replace the server's own pancreatic_tumour card (no examples yet) rather than add a second one.
    const labels = (json.labels as { label?: string }[]).filter((l) => l.label !== 'pancreatic_tumour');
    await route.fulfill({ response: res, json: { ...json, labels: [...labels, ct] } });
  });
  const gz = (file: string) => (route: Route) => route.fulfill({ path: `${FIX}/${file}`, contentType: 'application/gzip' });
  await page.route('**/api/cases/vol_001/volume', gz('volumes/vol_001.i16.gz'));
  await page.route('**/api/cases/vol_001/maskvol', gz('masks/vol_001.u8.gz'));
}

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

test('the scan-type chips reflect what the library holds: chest films only → CT and MRI are muted "coming"', async ({ page }) => {
  await page.goto('/start?mock=0');
  await expect(page.getByRole('heading', { level: 1, name: 'Start reading' })).toBeVisible();
  const health = await (await page.request.get(`${API}/health`)).json() as { cases_by_modality?: Record<string, number> };
  const has = (m: string) => (health.cases_by_modality?.[m] ?? (m === 'cxr' ? 1 : 0)) > 0;
  // Scan type is the first question on the page.
  const legends = page.locator('form legend, form h2');
  await expect(legends.first()).toHaveText('Scan type');
  await expect(page.getByTestId('scan-cxr')).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByTestId('scan-cxr')).toBeEnabled();
  for (const m of ['ct', 'mr'] as const) {
    const chip = page.getByTestId(`scan-${m}`);
    await expect(chip).toHaveAttribute('data-available', has(m) ? '1' : '0');
    if (!has(m)) { await expect(chip).toBeDisabled(); await expect(chip).toContainText('coming'); }
  }
  await expect(page.getByTestId('scan-ct')).toContainText('Abdominal CT');
  await expect(page.getByTestId('scan-mr')).toContainText('Brain MRI');
  await expect(page.getByTestId('finding-pick').locator('option')).toHaveCount(13);
  await expect(page.getByTestId('half-normal')).toHaveText('About half the films are normal — finding nothing is a real answer.');
  expect(await page.locator('main').innerText()).not.toMatch(BANNED);
  await page.screenshot({ path: `${SHOTS}/round4-01-start-chips.png`, fullPage: true });
});

test('with CT and MRI in the library: choosing CT starts a ct session, lists CT findings, says "studies", hides the test, and is remembered', async ({ page }) => {
  await withModalities(page, { cxr: 500, ct: 12, mr: 6 });
  const posted: Record<string, unknown>[] = [];
  page.on('request', (r) => { if (r.url().endsWith('/api/sessions') && r.method() === 'POST') posted.push(r.postDataJSON()); });

  // The landing hero gains its one line.
  await page.goto('/?mock=0');
  await expect(page.getByTestId('scan-types-line')).toHaveText('Chest X-ray, abdominal CT and brain MRI.');
  await expect(page.getByTestId('health')).toHaveText(/^Library: 500 chest films, 12 abdominal CT and 6 brain MRI studies, with expert outlines\.$/);

  await page.goto('/start');
  for (const m of ['cxr', 'ct', 'mr']) await expect(page.getByTestId(`scan-${m}`)).toBeEnabled();
  await expect(page.getByTestId('scan-ct')).not.toContainText('coming');
  await page.getByTestId('scan-ct').click();
  await expect(page.getByTestId('scan-ct')).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByTestId('scan-cxr')).toHaveAttribute('aria-checked', 'false');
  // Wording: studies, not films; CT findings only; no test set for CT.
  await expect(page.locator('form legend').filter({ hasText: 'How many' })).toHaveText('How many studies?');
  await expect(page.getByTestId('note-mixed')).toContainText('Studies chosen to suit how you have read so far.');
  await expect(page.getByTestId('finding-pick').locator('option')).toHaveText(['Pancreatic tumour', 'Liver tumour', 'Lung tumour', 'Colon tumour']);
  await expect(page.getByTestId('practice-test')).toBeDisabled();
  await expect(page.getByTestId('note-test')).toHaveText('Not yet available for this scan type.');
  await expect(page.getByTestId('practice-weak')).toBeDisabled();
  await expect(page.getByTestId('note-weak')).toContainText('Opens after 5 studies of this scan type');
  await expect(page.getByTestId('half-normal')).toHaveText('About half the studies show no lesion — finding nothing is a real answer.');
  await page.screenshot({ path: `${SHOTS}/round4-02-start-ct.png`, fullPage: true });

  // Remembered across a reload (localStorage), then sent as settings.modality + body_region.
  await page.reload();
  await expect(page.getByTestId('scan-ct')).toHaveAttribute('aria-checked', 'true');
  expect(await page.evaluate(() => localStorage.getItem('bs_modality'))).toBe('ct');
  await page.getByTestId('name').fill('E2E round4 (test)');
  await page.getByTestId('count-5').check({ force: true });
  await page.getByTestId('start').click();
  await expect(page).toHaveURL(/\/read(\?|$)/);
  expect(posted).toEqual([expect.objectContaining({ display_name: 'E2E round4 (test)', mode: 'practice', settings: expect.objectContaining({ case_count: 5, selection: 'adaptive', modality: 'ct', body_region: 'abdomen' }) })]);
  const s = (await storedSession(page))!;
  expect(s.sessionId).toBeTruthy();

  // MRI lists its one finding; the X-ray chip restores the thirteen and the test.
  await page.goto('/start');
  await page.getByTestId('scan-mr').click();
  await expect(page.getByTestId('finding-pick').locator('option')).toHaveText(['Brain tumour']);
  await page.getByTestId('scan-cxr').click();
  await expect(page.getByTestId('finding-pick').locator('option')).toHaveCount(13);
  await expect(page.getByTestId('practice-test')).toBeEnabled();
  expect(await page.evaluate(() => localStorage.getItem('bs_modality'))).toBe('cxr');
});

test('a remembered scan type the library no longer holds reads as Chest X-ray', async ({ page }) => {
  await page.goto('/start?mock=0');
  await page.evaluate(() => localStorage.setItem('bs_modality', 'mr'));
  await page.reload();
  await expect(page.getByTestId('health')).toContainText('Library');
  const health = await (await page.request.get(`${API}/health`)).json() as { cases_by_modality?: Record<string, number> };
  if ((health.cases_by_modality?.mr ?? 0) > 0) test.skip(true, 'the library holds MRI studies, so the remembered choice stands');
  await expect(page.getByTestId('scan-cxr')).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByTestId('scan-mr')).toHaveAttribute('aria-checked', 'false');
});

test('the provenance pill: ChestX-Det on a reviewed chest film; the dataset on a CT row of the set summary', async ({ page, request }) => {
  await page.goto('/start?mock=0');
  await page.getByTestId('name').fill('E2E round4 prov (test)');
  await page.getByTestId('count-5').check({ force: true });
  await page.getByTestId('start').click();
  await expect(page).toHaveURL(/\/read(\?|$)/);
  await expect(page.getByTestId('case-index')).toContainText('of 5', { timeout: 15_000 });
  const s = (await storedSession(page))!;
  expect(await readAll(request, s.sessionId)).toBe(5);
  await page.goto(`/set/${s.sessionId}`);
  await expect(page.getByTestId('case-row')).toHaveCount(5);
  // A chest set: rows say "Film", carry no scan-type column (nothing to tell apart) and no pill.
  await expect(page.getByTestId('case-row').first()).toContainText('Film 1');
  await expect(page.getByTestId('row-modality')).toHaveCount(0);
  await expect(page.getByTestId('summary-modality')).toHaveCount(0);
  await page.getByTestId('case-review-link').first().click();
  await expect(page.getByTestId('case-review-page')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('case-review-title')).toHaveText('Film 1 of 5');
  const pill = page.getByTestId('provenance-badge');
  await expect(pill).toHaveCount(1);
  await expect(pill).toHaveText(PROV_TEXT_CXR);
  await expect(pill).toHaveAttribute('data-grade', 'radiologist');
  await expect(page.getByTestId('review-modality')).toHaveCount(0);

  // The same set summary with the backend's volumetric row shape: a CT row says "Study", names the scan type and its dataset.
  await page.route(`**/api/sessions/${s.sessionId}/summary`, async (route) => {
    const res = await route.fetch();
    const json = (await res.json()) as { cases: Record<string, unknown>[] };
    const cases = json.cases.map((c, i) => (i === 0 ? { ...c, modality: 'ct', provenance: PROV_CT } : c));
    await route.fulfill({ response: res, json: { ...json, cases } });
  });
  await page.goto(`/set/${s.sessionId}`);
  await expect(page.getByTestId('case-row')).toHaveCount(5);
  const first = page.getByTestId('case-row').first();
  await expect(first).toHaveAttribute('data-modality', 'ct');
  await expect(first).toContainText('Study 1');
  await expect(first.getByTestId('row-modality')).toHaveText('Abdominal CT');
  await expect(first.getByTestId('provenance-badge')).toHaveText('Medical Segmentation Decathlon, Task07 Pancreas');
  await expect(first.getByTestId('provenance-badge')).toHaveAttribute('title', PROV_TEXT_CT);
  // The other rows are chest films and show their own (short) badge beside the scan type.
  const second = page.getByTestId('case-row').nth(1);
  await expect(second.getByTestId('row-modality')).toHaveText('Chest X-ray');
  await expect(second.getByTestId('provenance-badge')).toHaveText('ChestX-Det');
  // A mixed set keeps "films" in the counts (nothing is called a study for the whole set).
  await expect(page.getByTestId('count-films')).toContainText('Films read');
  expect(await page.locator('main').innerText()).not.toMatch(BANNED);
});

test('the finding library groups by scan type; a CT card draws a decoded slice with the outline and scrubs through the slices', async ({ page }) => {
  await withCtReference(page);
  await page.goto('/reference?mock=0');
  await expect(page.getByRole('heading', { level: 1, name: 'Finding library' })).toBeVisible();
  await expect(page.getByTestId('reference')).toBeVisible({ timeout: 15_000 });
  // One group per scan type the library's cards cover: chest first, then CT, then MRI when the server lists brain_tumour.
  const ref = await (await page.request.get(`${API}/reference`)).json() as { labels: { label: string }[] };
  const hasMr = ref.labels.some((l) => l.label === 'brain_tumour');
  const groups = page.getByTestId('ref-scan-group');
  await expect(groups).toHaveCount(hasMr ? 3 : 2);
  await expect(groups.nth(0)).toHaveAttribute('data-modality', 'cxr');
  await expect(groups.nth(1)).toHaveAttribute('data-modality', 'ct');
  await expect(groups.nth(1).getByRole('heading', { level: 2, name: 'Abdominal CT' })).toBeVisible();
  if (hasMr) await expect(groups.nth(2).getByRole('heading', { level: 2, name: 'Brain MRI' })).toBeVisible();
  await expect(page.getByTestId('ref-index')).toContainText('Abdominal CT · Marked on a slice');
  await expect(page.getByTestId('ref-lede')).toContainText('by scan type');

  const entry = page.locator('[data-testid=ref-entry][data-modality=ct]#pancreatic_tumour');
  await expect(entry).toHaveCount(1);
  await expect(entry.getByRole('heading', { level: 2 })).toHaveText('Pancreatic tumour');
  await expect(entry).toContainText('Marked on a slice');
  await expect(entry).toContainText('Hypoenhancing mass in the gland');
  await expect(entry).toContainText('Focal pancreatitis');
  await expect(entry).toContainText('Example studies (1)');
  const card = entry.getByTestId('reference-example');
  await expect(card).toHaveAttribute('data-modality', 'ct');
  // Starts on the finding's measured slice (index 8 → "Slice 9"), with the mask outline drawn from the decoded gz.
  await expect(card.getByTestId('reference-slice-text')).toHaveText('Slice 9 of 16 · on the finding', { timeout: 15_000 });
  await expect(card.getByTestId('reference-outline').locator('polygon')).toHaveCount(1);
  await expect(card.getByTestId('provenance-badge')).toHaveText('Medical Segmentation Decathlon, Task07 Pancreas');
  // The canvas holds real voxels: not all one colour.
  const painted = await card.getByTestId('reference-slice').evaluate((c: HTMLCanvasElement) => {
    const d = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
    const seen = new Set<number>();
    for (let i = 0; i < d.length; i += 4) seen.add(d[i]);
    return seen.size;
  });
  expect(painted).toBeGreaterThan(2);
  await entry.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${SHOTS}/round4-03-library-ct-card.png`, clip: (await entry.boundingBox())! });
  // Scrub off the finding: the outline goes, the text says where the finding is.
  await card.getByTestId('reference-slice-scrub').fill('0');
  await expect(card.getByTestId('reference-slice-text')).toHaveText('Slice 1 of 16 · finding on 7–11');
  await expect(card.getByTestId('reference-outline')).toHaveCount(0);
  await card.getByTestId('reference-slice-scrub').fill('7');
  await expect(card.getByTestId('reference-slice-text')).toHaveText('Slice 8 of 16 · on the finding');
  // The outline toggle applies to the CT card too.
  await page.getByTestId('ref-outline-toggle').uncheck();
  await expect(card.getByTestId('reference-outline')).toHaveCount(0);
  // The chest group still holds its thirteen entries and the normal films.
  await expect(groups.nth(0).getByTestId('ref-entry')).toHaveCount(13);
  // Normal films sit inside the chest group (the fixture bank has none).
  const normals = (await (await page.request.get(`${API}/reference`)).json() as { normal_examples: unknown[] }).normal_examples.length;
  await expect(groups.nth(0).getByTestId('ref-normal')).toHaveCount(normals ? 1 : 0);
  expect(await page.locator('main').innerText()).not.toMatch(BANNED);
});

test('the reading log gets a scan-type switch; CT shows misses by zone instead of the chest map', async ({ page }) => {
  await withModalities(page, { cxr: 500, ct: 12, mr: 0 });
  const dash = (modality: string | null) => ({
    n_attempts: modality === 'ct' ? 6 : 14,
    n_by_modality: { cxr: 8, ct: 6 },
    modality,
    summary: { n: modality === 'ct' ? 6 : 14, n_abnormal: 4, n_normal: 2, sensitivity: 0.5, specificity: 1, localization_fraction: 0.5, n_focal_findings: 4, false_positives_per_image: 0, miss_type_mix: { search: 1, recognition: 1, decision: 0, interpretation: 0, overcall: 0 }, score_mean: 60 },
    learning_curve: { window: 10, n: 6, overall: [1, 2, 3, 4, 5, 6].map((a) => ({ attempt: a, success_rate: 0.5, window_n: a })), per_label: {} },
    miss_type_mix: { window: 10, n: 6, windows: [{ from: 1, to: 6, n: 6, search: 1, recognition: 1, decision: 0, interpretation: 0, overcall: 0 }] },
    calibration: { bins: [], n: 0, confident_misses: 0 },
    froc: { n_images: 6, n_lesions: 4, n_marks: 2, points: [] },
    blindspot_map: modality === 'ct'
      ? { frame: 'volume', n: 4, n_missed: 2, points: [{ x: 0.5, y: 0.5, label: 'pancreatic_tumour', result: 'missed_search', found: false, zone: 'pancreas' }, { x: 0.6, y: 0.4, label: 'pancreatic_tumour', result: 'found', found: true, zone: 'pancreas' }, { x: 0.3, y: 0.2, label: 'liver_tumour', result: 'missed_recognition', found: false, zone: 'liver' }, { x: 0.2, y: 0.5, label: 'liver_tumour', result: 'found', found: true, zone: 'hepatic_vessels' }] }
      : { frame: 'lung_bbox', n: 4, n_missed: 2, points: [{ x: 0.3, y: 0.3, label: 'nodule', result: 'found', found: true }, { x: 0.7, y: 0.6, label: 'mass', result: 'missed_search', found: false }, { x: 0.5, y: 0.5, label: 'nodule', result: 'found', found: true }, { x: 0.2, y: 0.8, label: 'effusion', result: 'missed_decision', found: false }] },
    review_area_habit: { n: 6, areas: [] },
    abilities: [], empty_message: null,
    learner: { id: 'lrn_e2e', display_name: 'E2E round4 log (test)', level: 'other' },
  });
  await page.route('**/api/learners/lrn_e2e/dashboard*', (route) => {
    const m = new URL(route.request().url()).searchParams.get('modality');
    return route.fulfill({ json: dash(m) });
  });
  await page.goto('/progress?learner=lrn_e2e&mock=0');
  await expect(page.getByTestId('learner-dashboard')).toBeVisible({ timeout: 15_000 });
  const sw = page.getByTestId('log-scope');
  await expect(sw).toBeVisible();
  await expect(sw.getByRole('radio')).toHaveText(['All', 'Chest X-ray 8', 'CT 6', 'MRI 0']);
  await expect(page.getByTestId('log-scope-all')).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByTestId('blindspot-map')).toBeVisible();
  await expect(page.getByTestId('zone-misses')).toHaveCount(0);
  await expect(page.getByTestId('dashboard-n')).toContainText('n = 14 films from practice sets');

  await page.getByTestId('log-scope-ct').click();
  await expect(page).toHaveURL(/modality=ct/);
  await expect(page.getByTestId('log-scope-ct')).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByTestId('dashboard-n')).toContainText('n = 6 studies from practice sets (Abdominal CT)');
  await expect(page.getByTestId('summary-stats-n')).toHaveText('n = 6 films');
  await expect(page.getByTestId('blindspot-map')).toHaveCount(0);
  const zones = page.getByTestId('zone-misses');
  await expect(zones).toBeVisible();
  await expect(page.getByTestId('zone-misses-n')).toHaveText('n = 4 findings · 2 missed');
  await expect(zones.getByRole('listitem')).toHaveCount(3);
  await expect(zones.getByTestId('zone-pancreas')).toContainText('1 of 2 missed');
  await expect(zones.getByTestId('zone-liver')).toContainText('1 of 1 missed');
  await expect(zones.getByTestId('zone-hepatic_vessels')).toContainText('0 of 1 missed');
  // The miss-type names are unchanged.
  await expect(page.getByTestId('miss-mix')).toContainText('Never looked there');
  await expect(page.getByTestId('log-scope-unfiltered')).toHaveCount(0);
  await page.screenshot({ path: `${SHOTS}/round4-04-log-ct.png`, fullPage: true });

  await page.getByTestId('log-scope-all').click();
  await expect(page).not.toHaveURL(/modality=/);
  await expect(page.getByTestId('blindspot-map')).toBeVisible();
});

test('an older server that ignores the scan-type filter says so', async ({ page }) => {
  await withModalities(page, { cxr: 500, ct: 12, mr: 0 });
  await page.route('**/api/learners/lrn_old/dashboard*', (route) => route.fulfill({ json: {
    n_attempts: 6, summary: { n: 6, n_abnormal: 3, n_normal: 3, sensitivity: 0.67, specificity: 1, localization_fraction: 0.67, n_focal_findings: 3, false_positives_per_image: 0, miss_type_mix: { search: 1, recognition: 0, decision: 0, interpretation: 0, overcall: 0 }, score_mean: 70 },
    learner: { id: 'lrn_old', display_name: 'E2E old (test)', level: 'other' },
  } }));
  await page.goto('/progress?learner=lrn_old&modality=ct&mock=0');
  await expect(page.getByTestId('learner-dashboard')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('log-scope-ct')).toHaveAttribute('aria-checked', 'true');
  await expect(page.getByTestId('log-scope-unfiltered')).toHaveText('The reading log does not yet separate scan types, so every read is shown.');
  // Unfiltered data is chest data: the chest map stays, no zone list.
  await expect(page.getByTestId('blindspot-map')).toBeVisible();
  await expect(page.getByTestId('zone-misses')).toHaveCount(0);
});

test('About: scan types, the provenance table with every dataset, the lesion-free-slab caveat and the MSD citation', async ({ page }) => {
  await page.goto('/about?mock=0');
  await expect(page.getByRole('heading', { level: 1, name: 'About Blindspot' })).toBeVisible();
  await expect(page.getByTestId('about-scans')).toContainText('Chest X-ray');
  await expect(page.getByTestId('about-scans')).toContainText('Abdominal CT');
  await expect(page.getByTestId('about-scans')).toContainText('Brain MRI');
  await expect(page.getByTestId('about-slab-caveat')).toContainText('a slab where the dataset labelled no lesion; not certified normal by a radiologist');
  const table = page.getByTestId('provenance-table');
  await expect(table).toBeVisible();
  const rows = page.getByTestId('provenance-row');
  await expect(rows).toHaveCount(7);
  const keys = await rows.evaluateAll((els) => els.map((e) => e.getAttribute('data-key')));
  expect(keys).toEqual(['chestx-det', 'Task07_Pancreas', 'Task08_HepaticVessel', 'Task03_Liver', 'Task01_BrainTumour', 'Task06_Lung', 'Task10_Colon']);
  await expect(rows.first()).toContainText('Chest X-ray');
  await expect(rows.first()).toContainText('three board-certified radiologists');
  await expect(rows.first()).toContainText('Apache-2.0');
  await expect(rows.nth(1).locator('td').first()).toHaveText('CT');
  await expect(rows.nth(1)).toContainText('CC BY-SA 4.0');
  await expect(rows.nth(4).locator('td').first()).toHaveText('MRI');
  await expect(page.getByTestId('msd-citation')).toContainText('The Medical Segmentation Decathlon. Nature Communications, 2022');
  await expect(page.getByTestId('about-provenance').getByTestId('provenance-badge')).toHaveText(PROV_TEXT_CXR);
  await expect(page.getByTestId('about-limits')).toContainText('reported, not scored');
  expect(await page.locator('main').innerText()).not.toMatch(BANNED);
  await page.getByTestId('about-provenance').scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${SHOTS}/round4-05-about-provenance.png`, clip: (await page.getByTestId('about-provenance').boundingBox())! });
});
