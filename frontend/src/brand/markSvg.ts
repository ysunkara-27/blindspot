// The Blindspot mark: an almond eye whose iris is a pair of lungs cut out of the fill, with one small dot (the
// finding) sitting in the upper third of the image-right lung — patient LEFT, a nod to the apical blind spot. The
// image-left lung (patient RIGHT) is drawn slightly larger, as on a film. Hand-drawn paths in a 64 × 40 box; no
// gradients, two colours at most. `brandMarkSvg` is pure (used for the favicon, icons and the OG image);
// `BrandMark` wraps it for React. Below ~14 px tall the lungs blur, so the mark collapses to eye + one dot.

export const MARK_W = 64;
export const MARK_H = 40;
/** Rendered height under which the lung cut-outs would blur: draw the simple mark instead. */
export const SIMPLE_BELOW = 14;

export const OFF_WHITE = '#F3F5F6';
export const INK = '#1D2329';
export const CYAN = '#35C9DD';
export const PACS_DARK = '#1C1F22';

/** Eye outline: two symmetric cubic arcs meeting at pointed corners on the midline. */
export const EYE_PATH = 'M2 20C14 -3.5 50 -3.5 62 20C50 43.5 14 43.5 2 20Z';
/** Image-left lung (patient RIGHT): a little taller and wider, medial border nearly straight, rounded base. */
export const LUNG_R_PATH = 'M26 5C28.5 5 29 8 29 11L29 28C29 31 26.5 32.5 23 32.5C19 32.5 15 31 14.5 26C14 20 18 9 23 5.5C24 5 25 5 26 5Z';
/** Image-right lung (patient LEFT): mirrored and a touch smaller, rounded base. */
export const LUNG_L_PATH = 'M38 5.5C35.5 5.5 35 8.5 35 11.5L35 27.5C35 30.5 37.5 31.8 40.5 31.8C44 31.8 48.5 30.5 49 26C49.5 20 46 9.5 41 6C40 5.5 39 5.5 38 5.5Z';
/** The finding: inside the image-right lung at roughly its upper third. */
export const DOT = { cx: 42, cy: 15, r: 3.5 } as const;
/** The simple mark's dot: bigger, a little further in, so it still reads at 16 px. */
export const DOT_SIMPLE = { cx: 40, cy: 18, r: 5.5 } as const;

export type MarkSvgOptions = {
  /** Eye colour. Off-white on dark grounds, ink on paper. */
  fill?: string;
  /** Dot colour; defaults to cyan. Pass the fill colour for the monochrome variant. */
  dot?: string;
  /** When set, a square 64 × 64 tile of this colour with 12-unit corners sits behind a centred mark (favicon, icons). */
  ground?: string;
  /** Rendered height in CSS px (width is height × 1.6; with `ground` the tile is a `size` square). */
  size?: number;
  /** Eye + one dot, no lungs. Defaults to on when the eye would render under 14 px tall. */
  simple?: boolean;
  /** Extra attributes for the root element, e.g. `class="x"` or `xmlns`. */
  attrs?: string;
};

/** Pure SVG for the mark, as a string. Element count: eye path (+ 2 lung paths when not simple) + 1 dot (+ 1 rect with ground). */
export function brandMarkSvg({ fill = OFF_WHITE, dot = CYAN, ground, size = MARK_H, simple, attrs = '' }: MarkSvgOptions = {}): string {
  const eyeHeight = ground ? size * (MARK_H / 64) : size;
  const isSimple = simple ?? eyeHeight < SIMPLE_BELOW;
  const d = isSimple ? DOT_SIMPLE : DOT;
  // Lungs are subpaths of the eye with the even-odd rule, so the ground shows through them.
  const eye = isSimple ? EYE_PATH : `${EYE_PATH}${LUNG_R_PATH}${LUNG_L_PATH}`;
  const body = `<path d="${eye}" fill="${fill}" fill-rule="evenodd"/><circle cx="${d.cx}" cy="${d.cy}" r="${d.r}" fill="${dot}"/>`;
  const a = attrs ? ` ${attrs}` : '';
  if (ground) {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 64 64"${a}><rect width="64" height="64" rx="12" fill="${ground}"/><g transform="translate(0 12)">${body}</g></svg>`;
  }
  const w = Math.round((size * MARK_W) / MARK_H * 100) / 100;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${size}" viewBox="0 0 ${MARK_W} ${MARK_H}"${a}>${body}</svg>`;
}
