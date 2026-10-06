// Where the mark popover goes (round 3 audit fix): beside the mark, never on top of it or of the magnifier lens
// around it, joined to the mark by a short connector. Pure geometry in stage (screen) px.
export type Placement = {
  left: number;
  top: number;
  side: 'right' | 'left' | 'below' | 'above';
  /** Connector end points: from the edge of the mark's clear zone to the nearest edge of the popover. */
  from: { x: number; y: number };
  to: { x: number; y: number };
};

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(lo, v), Math.max(lo, hi));

/** `clear` = radius around the mark that must stay uncovered (the mark ring, or the magnifier lens when it is on). */
export function placePopover(
  mark: { x: number; y: number }, size: { w: number; h: number }, stage: { w: number; h: number }, clear: number, margin = 8, markR = 12,
): Placement {
  const { w, h } = size;
  const gap = clear + 14;
  const topSide = clamp(mark.y - h / 2, margin, stage.h - h - margin);
  const leftCentered = clamp(mark.x - w / 2, margin, stage.w - w - margin);
  const inset = Math.min(18, h / 2, w / 2);
  const sideY = (top: number) => clamp(mark.y, top + inset, top + h - inset);
  const colX = (left: number) => clamp(mark.x, left + inset, left + w - inset);
  const right = (): Placement => ({ side: 'right', left: mark.x + gap, top: topSide, from: { x: mark.x + markR, y: mark.y }, to: { x: mark.x + gap, y: sideY(topSide) } });
  const left = (): Placement => ({ side: 'left', left: mark.x - gap - w, top: topSide, from: { x: mark.x - markR, y: mark.y }, to: { x: mark.x - gap, y: sideY(topSide) } });
  const below = (): Placement => ({ side: 'below', left: leftCentered, top: mark.y + gap, from: { x: mark.x, y: mark.y + markR }, to: { x: colX(leftCentered), y: mark.y + gap } });
  const above = (): Placement => ({ side: 'above', left: leftCentered, top: mark.y - gap - h, from: { x: mark.x, y: mark.y - markR }, to: { x: colX(leftCentered), y: mark.y - gap } });
  if (mark.x + gap + w <= stage.w - margin) return right();
  if (mark.x - gap - w >= margin) return left();
  if (mark.y + gap + h <= stage.h - margin) return below();
  if (mark.y - gap - h >= margin) return above();
  // No side has the full width or height. Push the popover against the roomier edge, then slide it down (or up) just
  // far enough that its nearest corner clears the circle: a diagonal placement.
  const sides: ('right' | 'left')[] = stage.w - mark.x >= mark.x ? ['right', 'left'] : ['left', 'right'];
  for (const side of sides) {
    const l = side === 'right' ? Math.max(mark.x + markR, stage.w - w - margin) : Math.min(mark.x - markR - w, margin);
    if (l < margin || l + w > stage.w - margin) continue;
    const dx = side === 'right' ? l - mark.x : mark.x - (l + w);
    const dy = dx >= clear ? 0 : Math.sqrt(clear * clear - dx * dx) + 2;
    const edgeX = side === 'right' ? l : l + w;
    if (mark.y + dy + h <= stage.h - margin) {
      const t = Math.max(margin, mark.y + dy);
      return { side, left: l, top: t, from: { x: mark.x + (side === 'right' ? markR : -markR), y: mark.y }, to: { x: edgeX, y: t + inset } };
    }
    if (mark.y - dy - h >= margin) {
      const t = Math.min(stage.h - h - margin, mark.y - dy - h);
      return { side, left: l, top: t, from: { x: mark.x + (side === 'right' ? markR : -markR), y: mark.y }, to: { x: edgeX, y: t + h - inset } };
    }
  }
  // A large popover in the middle of the stage cannot clear the whole lens: clear the mark itself instead.
  if (clear > markR + 8) return placePopover(mark, size, stage, markR + 8, margin, markR);
  // Last resort (a very small stage): keep the popover on the stage.
  const p = sides[0] === 'right' ? right() : left();
  const l = clamp(p.left, margin, stage.w - w - margin);
  return { ...p, left: l, to: { x: p.side === 'right' ? l : l + w, y: p.to.y } };
}

/** True when the popover rectangle keeps out of the clear circle around the mark. */
export function clearsMark(p: Placement, size: { w: number; h: number }, mark: { x: number; y: number }, clear: number): boolean {
  const nx = clamp(mark.x, p.left, p.left + size.w);
  const ny = clamp(mark.y, p.top, p.top + size.h);
  return Math.hypot(nx - mark.x, ny - mark.y) >= clear;
}
