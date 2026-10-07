// Sign label helpers shared by SignsLayer (drawing) and RevealLayer (placement): text measurement, the "Look for"
// pill boxes and line wrapping for the hover sentence. Kept out of the component file so fast refresh stays clean.
import type { Box } from './arrows';
import { signBounds, type ViewSign } from './signs';

/** Text width in screen px at `px` font size, bold (shared with RevealLayer; measured when a canvas exists). */
const FONT = '"Atkinson Hyperlegible Next", "Atkinson Hyperlegible", system-ui, sans-serif';
let ctx: CanvasRenderingContext2D | null | undefined;
export function signTextWidth(text: string, px: number, weight = 700): number {
  if (ctx === undefined) ctx = typeof document === 'undefined' ? null : document.createElement('canvas').getContext('2d');
  if (!ctx) return text.length * 0.56 * px;
  ctx.font = `${weight} ${px}px ${FONT}`;
  return ctx.measureText(text).width * 1.03;
}

export const signLabel = (sg: ViewSign) => `Look for: ${sg.name}`;

/** The pill for each sign, before placement: under the shape (above it near the bottom edge). */
export function signLabelBoxes(signs: ViewSign[], k: number, fsPx: number, height: number): Box[] {
  const fs = fsPx * k;
  const lh = fs * 1.55;
  const padX = fs * 0.55;
  return signs.map((sg) => {
    const [x0, , x1, y1] = signBounds(sg);
    const w = padX * 2 + signTextWidth(signLabel(sg), fsPx) * k;
    const below = y1 + lh + 6 * k < height;
    const [, y0] = signBounds(sg);
    return { x: (x0 + x1) / 2 - w / 2, y: below ? y1 + 6 * k : y0 - lh - 6 * k, w, h: lh };
  });
}


/** Break a sentence into lines of at most `max` characters at spaces (SVG text does not wrap). */
export function wrapText(text: string, max = 56): string[] {
  const words = text.trim().split(/\s+/);
  const lines: string[] = [];
  let cur = '';
  for (const w of words) {
    if (cur && (cur + ' ' + w).length > max) { lines.push(cur); cur = w; }
    else cur = cur ? `${cur} ${w}` : w;
  }
  if (cur) lines.push(cur);
  return lines;
}

