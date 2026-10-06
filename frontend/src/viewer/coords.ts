/** Screen ↔ image coordinate mapping. The ONE tested function for conversion (SPEC §5.4).
 *  View transform: image px → screen px is  screen = origin + img * scale, where scale = fitScale * zoom.
 *  "Screen" here means px relative to the viewer stage's top-left corner (use stageRect to convert clientX/Y). */
export type View = { originX: number; originY: number; scale: number };

export function screenToImage(sx: number, sy: number, v: View): { x: number; y: number } {
  return { x: (sx - v.originX) / v.scale, y: (sy - v.originY) / v.scale };
}
export function imageToScreen(ix: number, iy: number, v: View): { x: number; y: number } {
  return { x: v.originX + ix * v.scale, y: v.originY + iy * v.scale };
}
/** clientX/clientY → image px, given the stage element's bounding rect. Used by marks AND telemetry. */
export function clientToImage(
  clientX: number, clientY: number, stage: { left: number; top: number }, v: View,
): { x: number; y: number } {
  return screenToImage(clientX - stage.left, clientY - stage.top, v);
}
export function insideImage(p: { x: number; y: number }, imgW: number, imgH: number): boolean {
  return p.x >= 0 && p.y >= 0 && p.x <= imgW && p.y <= imgH;
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
/** Fit-to-height (and never wider than the stage), centred. `pad` = screen px of surround kept around the film. */
export function fitView(stageW: number, stageH: number, imgW: number, imgH: number, pad = 0): View {
  const scale = Math.max(1e-6, Math.min((stageH - 2 * pad) / imgH, (stageW - 2 * pad) / imgW));
  return { scale, originX: (stageW - imgW * scale) / 2, originY: (stageH - imgH * scale) / 2 };
}
/** Keep at least `keep` screen px of the image inside the stage while panning. */
export function clampView(v: View, stageW: number, stageH: number, imgW: number, imgH: number, keep = 80): View {
  const w = imgW * v.scale;
  const h = imgH * v.scale;
  const originX = Math.min(stageW - keep, Math.max(keep - w, v.originX));
  const originY = Math.min(stageH - keep, Math.max(keep - h, v.originY));
  return { ...v, originX, originY };
}
