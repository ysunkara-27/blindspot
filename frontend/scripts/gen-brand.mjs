// Generate the brand files from src/brand/markSvg.ts (the one source of the geometry):
//   public/favicon.svg                 eye + dot on the PACS-dark tile (the simple mark: it must read at 16 px)
//   public/icons/apple-touch-icon.png  180 px full mark on the tile (iOS squares the corners itself)
//   public/icons/icon-512.png          512 px full mark on the tile (PWA / Android)
//   public/og.png                      1200 × 630 Open Graph card from scripts/og.html
// Run from frontend/: node scripts/gen-brand.mjs   (Node ≥ 22.6 strips the .ts types; Playwright renders the PNGs.)
import { mkdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { brandMarkSvg, PACS_DARK } from '../src/brand/markSvg.ts';

const here = dirname(fileURLToPath(import.meta.url));
const pub = resolve(here, '../public');
mkdirSync(resolve(pub, 'icons'), { recursive: true });

writeFileSync(resolve(pub, 'favicon.svg'), `${brandMarkSvg({ ground: PACS_DARK, size: 64, simple: true })}\n`);

const browser = await chromium.launch();
const page = await browser.newPage({ deviceScaleFactor: 1 });

async function tile(px, out) {
  await page.setViewportSize({ width: px, height: px });
  await page.setContent(`<html><body style="margin:0;background:transparent">${brandMarkSvg({ ground: PACS_DARK, size: px, simple: false })}</body></html>`);
  await page.screenshot({ path: out, omitBackground: true, clip: { x: 0, y: 0, width: px, height: px } });
}
await tile(180, resolve(pub, 'icons/apple-touch-icon.png'));
await tile(512, resolve(pub, 'icons/icon-512.png'));

await page.setViewportSize({ width: 1200, height: 630 });
const html = readFileSync(resolve(here, 'og.html'), 'utf8').replaceAll('{{MARK}}', brandMarkSvg({ size: 220, simple: false }));
await page.setContent(html, { waitUntil: 'networkidle' });
await page.evaluate(() => document.fonts.ready);
await page.screenshot({ path: resolve(pub, 'og.png'), clip: { x: 0, y: 0, width: 1200, height: 630 } });
await browser.close();

for (const f of ['favicon.svg', 'icons/apple-touch-icon.png', 'icons/icon-512.png', 'og.png']) {
  console.log(`${f}: ${Math.round(statSync(resolve(pub, f)).size / 1024)} KB`);
}
