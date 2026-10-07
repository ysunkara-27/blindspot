// Round 4 — the volume viewer (CT / MR) in the same reading room. Author: frontend-engineer (viewer).
// Default: the in-browser SYNTHETIC mock (`/start?mock=1&modality=ct` seeds a CT set; `modality=mr` the brain case).
// E2E_REAL=1: the real OFFLINE API with the fixture data dir
//   E2E_API_ENV="BLINDSPOT_PROCESSED_DIR=pipeline/tests/fixtures/synthetic" (frontend/playwright.local.config.ts);
// the start screen must then offer the scan type (the pages agent's `settings.modality`).
// Covers: the 2×2 grid on open → double-click the axial pane → scroll slices (wheel, keys, slider) → arm a finding →
// click → confidence → the size step (Measure → drag → Record) → submit → the reveal (outline from the label volume,
// slice dwell bar, size verdict) → the mask is never requested before submit → the brain case shows components.
import { expect, test, type Page } from '@playwright/test';

const REAL = process.env.E2E_REAL === '1';
const SHOTS = 'tests/e2e/__screenshots__';
const shot = (page: Page, name: string) =>
  page.screenshot({ path: `${process.cwd().endsWith('frontend') ? '../' : ''}${SHOTS}/${REAL ? 'live-' : ''}r4-${name}.png` });

test.use({ viewport: { width: 1280, height: 800 } });

async function startVolume(page: Page, modality: 'ct' | 'mr') {
  await page.goto(REAL ? `/start?mock=0&modality=${modality}` : `/start?mock=1&modality=${modality}`);
  await page.getByTestId('name').fill('E2E round 4 (test)');
  // The start screen's scan-type chip (pages side, `settings.modality`); the mock also reads `?modality=` from the address.
  const pick = page.locator(`[data-testid="scan-${modality}"][data-available="1"]`);
  if (await pick.count()) await pick.first().click();
  await page.getByTestId('start').click();
  await expect(page.getByTestId('stage')).toBeVisible();
}

async function view(page: Page) {
  const stage = page.getByTestId('stage');
  const box = (await stage.boundingBox())!;
  const [ox, oy, sc] = (await stage.getAttribute('data-view'))!.split(',').map(Number);
  return { box, toScreen: (ix: number, iy: number) => [box.x + ox + ix * sc, box.y + oy + iy * sc] as const, sc };
}

/** Wait for the voxels to be decoded and the grid to be up. */
async function gridReady(page: Page) {
  await expect(page.getByTestId('volume-grid')).toBeVisible();
  await expect(page.getByTestId('pane-axial').locator('canvas')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('film-loading')).toHaveCount(0);
}

test.describe('round 4 — volume viewer', () => {
  test('CT: grid → axial → slices → mark → measure → submit → reveal; the mask is never requested before submit', async ({ page }) => {
    const maskRequests: string[] = [];
    page.on('request', (r) => { if (/\.u8\.gz|maskvol/.test(r.url())) maskRequests.push(r.url()); });

    await startVolume(page, 'ct');
    await gridReady(page);
    // The grid is the default: three planes and the info panel with the provenance badge; no mask yet.
    await expect(page.getByTestId('stage')).toHaveAttribute('data-plane', 'grid');
    for (const p of ['axial', 'coronal', 'sagittal']) await expect(page.getByTestId(`pane-${p}`)).toBeVisible();
    await expect(page.getByTestId('volume-info')).toContainText('Voxel');
    await expect(page.getByTestId('volume-info').getByTestId('provenance-badge')).toContainText('Segmented by');
    await expect(page.getByTestId('plane-all')).toHaveAttribute('aria-pressed', 'true');
    // The same rail: three groups, scan-type findings, "Call it normal".
    await expect(page.getByTestId('group-point')).toBeVisible();
    await expect(page.getByTestId('group-whole')).toBeVisible();
    await expect(page.getByTestId('group-normal')).toBeVisible();
    await expect(page.getByTestId('arm-pancreatic_tumour')).toBeVisible();
    await expect(page.getByTestId('arm-pneumothorax')).toHaveCount(0);
    await shot(page, '01-grid');

    // Wheel over a grid pane scrolls that pane only.
    const axialBefore = Number(await page.getByTestId('pane-axial').getAttribute('data-slice'));
    const coronalBefore = Number(await page.getByTestId('pane-coronal').getAttribute('data-slice'));
    const pane = (await page.getByTestId('pane-axial').boundingBox())!;
    await page.mouse.move(pane.x + pane.width / 2, pane.y + pane.height / 2);
    await page.mouse.wheel(0, 100);
    await expect(page.getByTestId('pane-axial')).toHaveAttribute('data-slice', String(axialBefore + 1));
    await expect(page.getByTestId('pane-coronal')).toHaveAttribute('data-slice', String(coronalBefore));

    // Double-click the axial pane → the single-plane view where marking happens.
    await page.getByTestId('pane-axial').dblclick();
    await expect(page.getByTestId('stage')).toHaveAttribute('data-plane', 'axial');
    await expect(page.getByTestId('film')).toBeVisible();
    await expect(page.getByTestId('plane-axial')).toHaveAttribute('aria-pressed', 'true');
    const readout = page.getByTestId('slice-readout');
    await expect(readout).toHaveText(/Slice \d+ of \d+/);

    // Slices: wheel, ↑ / ↓, PageDown, the slider. Every change is a telemetry event with plane and slice.
    const v = await view(page);
    await page.mouse.move(v.box.x + v.box.width / 2, v.box.y + v.box.height / 2);
    const s0 = Number(await page.getByTestId('stage').getAttribute('data-slice'));
    await page.mouse.wheel(0, 100);
    await expect(page.getByTestId('stage')).toHaveAttribute('data-slice', String(s0 + 1));
    await page.keyboard.press('ArrowUp');
    await expect(page.getByTestId('stage')).toHaveAttribute('data-slice', String(s0));
    await page.keyboard.press('PageDown');
    await expect(page.getByTestId('stage')).toHaveAttribute('data-slice', String(s0 + 5));
    await page.getByTestId('slice-slider').fill('8');
    await expect(page.getByTestId('stage')).toHaveAttribute('data-slice', '8');
    await expect(readout).toHaveText('Slice 9 of 16');
    const tel = await page.evaluate(() => {
      const t = (window as unknown as { __bsTelemetry: { snapshot(): { kind: string; plane?: string; slice?: number }[] } }).__bsTelemetry.snapshot();
      return { slices: t.filter((e) => e.kind === 'slice').length, planes: t.filter((e) => e.kind === 'plane').length, withPlane: t.filter((e) => e.plane === 'axial').length, n: t.length };
    });
    expect(tel.slices).toBeGreaterThanOrEqual(4);
    expect(tel.planes).toBeGreaterThanOrEqual(1);
    expect(tel.withPlane).toBe(tel.n);

    // Ctrl + wheel zooms; the zoom readout moves; reset view brings it back.
    await page.keyboard.down('Control');
    await page.mouse.wheel(0, -300);
    await page.keyboard.up('Control');
    await expect(page.getByTestId('zoom-readout')).not.toHaveText('1.0×');
    await page.getByTestId('reset-view').click();
    await expect(page.getByTestId('zoom-readout')).toHaveText('1.0×');

    // Window: a preset and the W/L readout; brightness / contrast sliders are gone, invert still works.
    await expect(page.getByLabel('Brightness')).toHaveCount(0);
    await page.getByTestId('window-preset').selectOption('Lung');
    await expect(page.getByTestId('wl-readout')).toContainText('W 1500 · L -600 · Lung');
    await page.getByTestId('window-preset').selectOption('Default');
    await page.getByTestId('invert-toggle').click();
    await expect(page.getByTestId('invert-toggle')).toHaveAttribute('aria-pressed', 'true');
    await page.getByTestId('invert-toggle').click();

    // Arm the finding, dwell on the blob a moment, click it: a mark with plane, slice and voxel.
    await page.getByTestId('arm-pancreatic_tumour').click();
    const v2 = await view(page);
    const [mx, my] = v2.toScreen(24.5, 36.5);
    await page.mouse.move(mx, my);
    await page.waitForTimeout(900);
    await page.mouse.click(mx, my);
    const pop = page.getByTestId('mark-popover');
    await expect(pop).toBeVisible();
    await expect(pop).toHaveAttribute('data-mode', 'confidence');
    await pop.getByRole('radio', { name: 'Confidence 4 of 5' }).click();
    await expect(pop).toBeHidden();
    await expect(page.getByTestId('mark-place-M1')).toHaveText('· axial 9');
    const mark = page.locator('[data-mark-id="M1"]');
    await expect(mark).toHaveAttribute('data-vis', 'full');
    // One slice away the mark is ghosted; two away it is gone; back on its slice it is full.
    await page.keyboard.press('ArrowDown');
    await expect(mark).toHaveAttribute('data-vis', 'ghost');
    await page.keyboard.press('ArrowDown');
    await expect(mark).toHaveCount(0);
    await page.getByTestId('mark-row-M1').getByRole('button', { name: /Pancreatic tumour/ }).click(); // jumps back to its slice
    await expect(page.getByTestId('stage')).toHaveAttribute('data-slice', '8');
    await page.keyboard.press('Escape');
    await shot(page, '02-axial-mark');

    // The size step: Submit waits for it; Measure arms the caliper on the axial view; a drag draws the line in mm.
    await expect(page.getByTestId('submit')).toBeDisabled();
    await expect(page.getByTestId('submit-help')).toContainText('M1 needs a size');
    await expect(page.getByTestId('size-M1')).toContainText('How big is it?');
    expect(maskRequests, 'no mask before submit').toEqual([]);
    await page.getByTestId('measure-M1').click();
    await expect(page.getByTestId('caliper-prompt')).toContainText('drag from edge to edge');
    await expect(page.getByTestId('stage')).toHaveAttribute('data-plane', 'axial');
    const v3 = await view(page);
    const [ax, ay] = v3.toScreen(20, 36.5);
    const [bx, by] = v3.toScreen(29, 36.5);
    await page.mouse.move(ax, ay);
    await page.mouse.down();
    await page.mouse.move((ax + bx) / 2, ay, { steps: 4 });
    await page.mouse.move(bx, by, { steps: 4 });
    await page.mouse.up();
    await expect(page.getByTestId('caliper-line')).toBeVisible();
    await expect(page.getByTestId('caliper-readout')).toHaveText('13.5 mm'); // 9 voxels × 1.5 mm
    await expect(page.getByTestId('size-readout-M1')).toHaveText('13.5 mm');
    // The line survives a plane change and comes back with the axial view.
    await page.getByTestId('plane-coronal').click();
    await expect(page.getByTestId('caliper-line')).toHaveCount(0);
    await page.getByTestId('plane-axial').click();
    await expect(page.getByTestId('caliper-line')).toBeVisible();
    await shot(page, '03-caliper');
    await page.getByTestId('record-M1').click();
    await expect(page.getByTestId('size-M1')).toContainText('Size: 13.5 mm');
    await expect(page.getByTestId('submit')).toBeEnabled();

    // Submit: the request carries the 3-D mark and the measurement; the mask is fetched only now.
    const submitReq = page.waitForRequest((r) => r.method() === 'POST' && /\/submit$/.test(r.url())).catch(() => null);
    expect(maskRequests).toEqual([]);
    await page.getByTestId('submit').click();
    if (REAL) {
      const req = await submitReq;
      const body = req?.postDataJSON() as { marks: { plane: string; slice: number; voxel: number[] }[]; measurements: { mark_id: string; long_mm: number }[] };
      expect(body.marks[0]).toMatchObject({ plane: 'axial', slice: 8 });
      expect(body.marks[0].voxel).toHaveLength(3);
      expect(body.measurements[0]).toMatchObject({ mark_id: 'M1' });
    }
    await expect(page.getByTestId('outcomes')).toBeVisible({ timeout: 15_000 });
    expect(maskRequests.length, 'the mask is requested after submit').toBeGreaterThanOrEqual(1);
    // The reveal: single axial view, auto-fit, the colour key, the search toggle and legend, the dwell bar by the slider.
    await expect(page.getByTestId('stage')).toHaveAttribute('data-plane', 'axial');
    await expect(page.getByTestId('reveal-key')).toContainText('Expert outline');
    await expect(page.getByTestId('search-toggle')).toBeVisible();
    await expect(page.getByTestId('search-legend')).toBeVisible();
    await expect(page.getByTestId('zoom-readout')).toHaveText('1.0×'); // auto-fit on reveal
    await expect(page.getByTestId('dwell-bar')).toBeVisible();
    // The real API picks the case (it may serve the normal fixture volume); the mock always serves the tumour case.
    const hasF1 = (await page.getByTestId('outcome-F1').count()) > 0;
    expect(REAL || hasF1).toBe(true);
    if (hasF1) {
      // At the finding's measured slice: the cyan outline from the label volume, the finding's slices on the bar,
      // the size verdict under the finding.
      await expect(page.getByTestId('stage')).toHaveAttribute('data-slice', '8');
      await expect(page.locator('[data-testid=outline-F1] path').first()).toBeVisible({ timeout: 15_000 });
      await expect(page.locator('[data-testid^=dwell-][data-finding="1"]').first()).toBeVisible();
      await expect(page.getByTestId('size-verdict-F1')).toContainText(/You measured 13\.5 mm; reference 13\.5 mm/);
      await expect(page.getByTestId('size-verdict-F1')).toContainText('within tolerance');
      await expect(page.getByTestId('outcome-F1')).toContainText('Found it');
    } else {
      // A normal volume: the mark is "Not in the reference" — a dotted grey ring, a neutral chip, never a penalty.
      await expect(page.getByTestId('outcome-M1')).toContainText('Not in the reference');
      await expect(page.getByTestId('unmatched-M1')).toBeVisible();
    }
    await page.waitForTimeout(1500); // let the reveal animation settle for the picture
    await shot(page, '04-reveal-dwell');
    // "Show anatomy" tints the organ zones from the mask; a grid pane after the reveal shows the outline too.
    await page.keyboard.press('a');
    await expect(page.getByTestId('anatomy-toggle')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('[data-testid=anatomy-layer] path').first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId('anatomy-legend')).toContainText('Organ');
    await shot(page, '05-anatomy');
    await page.getByTestId('plane-all').click();
    if (hasF1) await expect(page.locator('[data-testid=pane-outline-axial-F1]')).toBeVisible();
    await expect(page.getByTestId('grid-colour-key')).toBeVisible();
    await shot(page, '06-grid-reveal');
    // The debrief's per-finding "See examples" still opens the reference drawer.
    if (hasF1) {
      const see = page.getByRole('button', { name: 'See examples' }).first();
      await expect(see).toBeVisible({ timeout: 15_000 });
      await see.click();
      await expect(page.getByTestId('reference-drawer')).toBeVisible();
    }
  });

  test('MR brain: components in three cyan tints with a legend; a mark the reference does not label is "Not in the reference"', async ({ page }) => {
    await startVolume(page, 'mr');
    await gridReady(page);
    await page.getByTestId('plane-axial').click();
    await page.getByTestId('slice-slider').fill('7');
    const v = await view(page);
    await page.getByTestId('arm-brain_tumour').click();
    const [mx, my] = v.toScreen(40, 28);
    await page.mouse.click(mx, my);
    await page.getByTestId('mark-popover').getByRole('radio', { name: 'Confidence 3 of 5' }).click();
    await page.getByTestId('arm-not_sure').click();
    const [ux, uy] = v.toScreen(12, 50);
    await page.mouse.click(ux, uy);
    await page.getByTestId('mark-popover').getByRole('radio', { name: 'Confidence 2 of 5' }).click();
    // Skip the size step for the tumour (C would start it; Skip is enough).
    await page.getByTestId('skip-M1').click();
    await expect(page.getByTestId('submit')).toBeEnabled();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('outcomes')).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('[data-testid^=component-F1-]')).toHaveCount(3, { timeout: 15_000 });
    await expect(page.getByTestId('component-key')).toContainText('oedema');
    await expect(page.getByTestId('component-key')).toContainText('enhancing');
    await expect(page.getByTestId('unmatched-M2')).toBeVisible();
    await expect(page.getByTestId('outcome-M2')).toContainText('Not in the reference');
    await expect(page.getByTestId('outcome-M2').locator('[data-result=unmatched]')).toBeVisible();
    await page.waitForTimeout(1500);
    await shot(page, '07-brain-components');
  });

  test('keyboard: planes, slider, caliper (C), record (Enter), the key sheet lists the volume keys', async ({ page }) => {
    await startVolume(page, 'ct');
    await gridReady(page);
    // Plane buttons are focusable and work from the keyboard.
    await page.getByTestId('plane-axial').focus();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('stage')).toHaveAttribute('data-plane', 'axial');
    await page.getByTestId('slice-slider').focus();
    await page.keyboard.press('ArrowRight');
    await expect(page.getByTestId('stage')).toHaveAttribute('data-slice', '9');
    // Mark from the keyboard (crosshair ← →, Space), then C → the size step, Enter records nothing until a line is drawn.
    await page.getByTestId('arm-pancreatic_tumour').click();
    await page.getByTestId('stage').focus();
    await page.keyboard.press('ArrowLeft');
    await page.keyboard.press(' ');
    await expect(page.getByTestId('mark-popover')).toBeVisible();
    await page.keyboard.press('4');
    await expect(page.getByTestId('mark-popover')).toBeHidden();
    await page.keyboard.press('c');
    await expect(page.getByTestId('caliper-toggle')).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('size-M1')).toHaveAttribute('data-state', 'measuring');
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('size-M1')).toHaveAttribute('data-state', 'measuring'); // nothing drawn: nothing recorded
    const v = await view(page);
    const [ax, ay] = v.toScreen(10, 10);
    const [bx, by] = v.toScreen(20, 10);
    await page.mouse.move(ax, ay);
    await page.mouse.down();
    await page.mouse.move(bx, by, { steps: 5 });
    await page.mouse.up();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('size-M1')).toHaveAttribute('data-state', 'recorded');
    await expect(page.getByTestId('size-M1')).toContainText('15 mm');
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('caliper-toggle')).toHaveAttribute('aria-pressed', 'false');
    // The key sheet lists the slice and caliper keys on a volume.
    await page.keyboard.press('?');
    await expect(page.getByTestId('keys-help')).toBeVisible();
    await expect(page.getByTestId('keys-help')).toContainText('Previous or next slice');
    await expect(page.getByTestId('keys-help')).toContainText('Caliper');
    await page.keyboard.press('Escape');
  });

  test('X-ray cases keep their controls: brightness and contrast, no plane buttons, the caliper from the strip in px', async ({ page }) => {
    await page.goto(REAL ? '/start?mock=0' : '/start?mock=1');
    await page.getByTestId('start').click();
    await expect(page.getByTestId('film')).toBeVisible();
    await expect(page.getByLabel('Brightness')).toBeVisible();
    await expect(page.getByTestId('plane-axial')).toHaveCount(0);
    await expect(page.getByTestId('slice-slider')).toHaveCount(0);
    // Round 5: the caliper is a strip tool on every modality (it left the View menu).
    await page.getByTestId('caliper-toggle').click();
    await expect(page.getByTestId('caliper-prompt')).toBeVisible();
    const v = await view(page);
    const [ax, ay] = v.toScreen(100, 100);
    const [bx, by] = v.toScreen(200, 100);
    await page.mouse.move(ax, ay);
    await page.mouse.down();
    await page.mouse.move(bx, by, { steps: 5 });
    await page.mouse.up();
    await expect(page.getByTestId('caliper-readout')).toHaveText('100 px');
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('caliper-prompt')).toHaveCount(0);
  });
});
