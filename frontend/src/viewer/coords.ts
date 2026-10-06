/** Screen ↔ image coordinate mapping. The ONE tested function for conversion (SPEC §5.4).
 *  View transform: image px → screen px is  screen = origin + img * scale, where scale = fitScale * zoom. */
export type View = { originX: number; originY: number; scale: number };

export function screenToImage(sx: number, sy: number, v: View): { x: number; y: number } {
  return { x: (sx - v.originX) / v.scale, y: (sy - v.originY) / v.scale };
}
export function imageToScreen(ix: number, iy: number, v: View): { x: number; y: number } {
  return { x: v.originX + ix * v.scale, y: v.originY + iy * v.scale };
}
/** Visible image rect [x0, y0, x1, y1] in image px for a viewport of (w, h) screen px. */
export function visibleRect(w: number, h: number, v: View, imgW: number, imgH: number): [number, number, number, number] {
  const a = screenToImage(0, 0, v);
  const b = screenToImage(w, h, v);
  return [Math.max(0, a.x), Math.max(0, a.y), Math.min(imgW, b.x), Math.min(imgH, b.y)];
}
/** Zoom about a screen anchor point, keeping the image point under the cursor fixed. */
export function zoomAt(v: View, factor: number, sx: number, sy: number, minScale: number, maxScale: number): View {
  const ns = Math.min(maxScale, Math.max(minScale, v.scale * factor));
  const k = ns / v.scale;
  return { scale: ns, originX: sx - (sx - v.originX) * k, originY: sy - (sy - v.originY) * k };
}
