// React wrapper for the Blindspot mark (see markSvg.ts for the geometry and the pure string builder).
import { CYAN, DOT, DOT_SIMPLE, EYE_PATH, INK, LUNG_L_PATH, LUNG_R_PATH, MARK_H, MARK_W, OFF_WHITE, SIMPLE_BELOW } from './markSvg';

// The pure string builder lives in markSvg.ts (plain TS, so scripts/gen-brand.mjs can import it under Node); it is
// re-exported here so app code has one import. Fast refresh of this file is not worth a second import path.
// eslint-disable-next-line react/only-export-components
export { brandMarkSvg, type MarkSvgOptions } from './markSvg';

export type BrandMarkProps = {
  /** Height in CSS px. Width follows (× 1.6). */
  size?: number;
  /** `dark`: off-white eye with a cyan dot, for the PACS surround. `light`: ink eye and ink dot, for report paper. */
  tone?: 'dark' | 'light';
  /** Dot in the eye colour (no cyan). */
  mono?: boolean;
  /** Force or suppress the eye-plus-dot simplification (defaults by size). */
  simple?: boolean;
  className?: string;
  /** Accessible name; by default the mark is decorative (the wordmark beside it carries the name). */
  title?: string;
};

export function BrandMark({ size = 20, tone = 'dark', mono = false, simple, className, title }: BrandMarkProps) {
  const fill = tone === 'dark' ? OFF_WHITE : INK;
  const dotColor = mono || tone === 'light' ? fill : CYAN;
  const isSimple = simple ?? size < SIMPLE_BELOW;
  const d = isSimple ? DOT_SIMPLE : DOT;
  const eye = isSimple ? EYE_PATH : `${EYE_PATH}${LUNG_R_PATH}${LUNG_L_PATH}`;
  const width = (size * MARK_W) / MARK_H;
  return (
    <svg
      className={className}
      width={width}
      height={size}
      viewBox={`0 0 ${MARK_W} ${MARK_H}`}
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : 'true'}
      aria-label={title}
      focusable="false"
      data-testid="brand-mark"
      data-tone={tone}
    >
      <path d={eye} fill={fill} fillRule="evenodd" />
      <circle cx={d.cx} cy={d.cy} r={d.r} fill={dotColor} />
    </svg>
  );
}
