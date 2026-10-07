// One slice of a volume on a canvas: w×h voxels painted through the window LUT, shown at its display size (square
// px of `unit` mm, so the physical aspect holds). The canvas sits inside the viewer's transformed layer like the film.
import { useLayoutEffect, useMemo, useRef, type CSSProperties, type RefObject } from 'react';
import { planeGeom, type Plane } from './planes';
import { extractSlice, type Volume } from './volume';
import { paintSlice } from './window';

export function SliceCanvas({ volume, plane, slice, lut, className, style, canvasRef, testid, alt }: {
  volume: Volume; plane: Plane; slice: number; lut: Uint8Array;
  className?: string; style?: CSSProperties; canvasRef?: RefObject<HTMLCanvasElement | null>; testid?: string; alt?: string;
}) {
  const own = useRef<HTMLCanvasElement>(null);
  const g = useMemo(() => planeGeom(volume, plane), [volume, plane]);
  useLayoutEffect(() => {
    const el = (canvasRef ?? own).current;
    const ctx = el?.getContext('2d');
    if (!el || !ctx) return;
    const img = ctx.createImageData(g.w, g.h);
    paintSlice(extractSlice(volume.data, volume.shape, plane, slice), lut, img.data);
    ctx.putImageData(img, 0, 0);
  }, [volume, plane, slice, lut, g, canvasRef]);
  return (
    <canvas
      ref={canvasRef ?? own}
      width={g.w}
      height={g.h}
      className={className}
      style={{ width: g.W, height: g.H, ...style }}
      data-testid={testid}
      data-plane={plane}
      data-slice={slice}
      role={alt ? 'img' : undefined}
      aria-label={alt}
    />
  );
}
