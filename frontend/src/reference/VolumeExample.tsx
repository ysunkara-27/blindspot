// One CT / MR example in the finding library: an axial slice drawn from the gzipped voxels (decoded in the browser),
// the reference outline from the label mask in cyan, and a slice scrubber that starts on the finding's measured slice.
// Decoding reuses the reading room's helpers (viewer/volume: gunzip, int16/uint8 decode, window LUT, marching
// squares); nothing here duplicates them. Nothing about the learner's own cases is shown.
import { useEffect, useMemo, useRef, useState } from 'react';
import { assetUrl } from '../api/client';
import { ProvenanceBadge } from '../app/ProvenanceBadge';
import { marchingSquares } from '../viewer/volume/marching';
import { planeGeom } from '../viewer/volume/planes';
import { cachedGunzip, decodeMask, decodeVolume, extractSlice, type MaskVolume, type Volume } from '../viewer/volume/volume';
import { paintSlice, windowLut } from '../viewer/volume/window';
import type { ReferenceExample } from './guard';
import s from './Reference.module.css';

type Loaded = { vol: Volume; mask: MaskVolume };

/** Fetch and decode both arrays once per URL pair (the viewer's cache keeps the gunzipped bytes). */
async function loadVolumeExample(v: NonNullable<ReferenceExample['volume']>): Promise<Loaded> {
  const meta = { shape: v.shape, spacing: v.spacing };
  const [vb, mb] = await Promise.all([cachedGunzip(assetUrl(v.volume_url)), cachedGunzip(assetUrl(v.mask_url))]);
  return { vol: decodeVolume(vb, meta), mask: decodeMask(mb, meta) };
}

/** Which mask values are the finding: the example's own, else every non-zero value. */
const insideFn = (values: number[]) => (values.length ? (x: number) => values.includes(x) : (x: number) => x > 0);

export function VolumeExample({ ex, outline, alt, small = false }: { ex: ReferenceExample; outline: boolean; alt: string; small?: boolean }) {
  const v = ex.volume!;
  const [z, setZ] = useState(v.slice);
  const [data, setData] = useState<Loaded | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const g = useMemo(() => planeGeom({ shape: v.shape, spacing: v.spacing }, 'axial'), [v.shape, v.spacing]);
  const lut = useMemo(() => windowLut(v.window.wc, v.window.ww), [v.window.wc, v.window.ww]);

  useEffect(() => {
    let live = true;
    loadVolumeExample(v).then((d) => { if (live) setData(d); }, (e: unknown) => { if (live) setFailed(e instanceof Error ? e.message : 'decode failed'); });
    return () => { live = false; };
  }, [v]);

  // Paint the current slice (w×h voxels; CSS scales it to the display aspect).
  useEffect(() => {
    const c = canvas.current;
    if (!c || !data) return;
    const ctx = c.getContext('2d');
    if (!ctx) return;
    const img = ctx.createImageData(g.w, g.h);
    paintSlice(extractSlice(data.vol.data, data.vol.shape, 'axial', z), lut, img.data);
    ctx.putImageData(img, 0, 0);
  }, [data, z, g.w, g.h, lut]);

  const rings = useMemo(() => {
    if (!data || !outline) return [];
    return marchingSquares(extractSlice(data.mask.data, data.mask.shape, 'axial', z), g.w, g.h, insideFn(v.label_values));
  }, [data, outline, z, g.w, g.h, v.label_values]);
  const range = ex.finding?.slice_range;
  const onFinding = range ? z >= range[0] && z <= range[1] : rings.length > 0;

  return (
    <figure className={`${s.figure} ${small ? s.figureSmall : ''}`} data-testid="reference-example" data-modality={ex.modality} data-slice={z}>
      <div className={s.film} style={{ aspectRatio: `${g.W} / ${g.H}` }}>
        {failed ? <p className={s.filmNote}>This example scan could not be decoded. {failed}</p> : (
          <>
            <canvas ref={canvas} width={g.w} height={g.h} className={s.sliceCanvas} role="img" aria-label={`${alt}, axial slice ${z + 1} of ${g.n}`} data-testid="reference-slice" />
            {!data && <p className={s.filmNote}>Decoding the scan…</p>}
            {outline && rings.length > 0 && (
              <svg viewBox={`0 0 ${g.w} ${g.h}`} preserveAspectRatio="none" aria-hidden="true" data-testid="reference-outline">
                {rings.map((r, i) => <polygon key={i} points={r.map(([x, y]) => `${x},${y}`).join(' ')} className={s.outline} vectorEffect="non-scaling-stroke" />)}
              </svg>
            )}
          </>
        )}
      </div>
      <div className={s.scrub}>
        <label>
          <span className="sr-only">Axial slice</span>
          <input type="range" min={0} max={Math.max(0, g.n - 1)} value={z} onChange={(e) => setZ(Number(e.target.value))} disabled={!data} data-testid="reference-slice-scrub" />
        </label>
        <span className={s.scrubText} data-testid="reference-slice-text">
          Slice {z + 1} of {g.n}{range ? (onFinding ? ' · on the finding' : ` · finding on ${range[0] + 1}–${range[1] + 1}`) : ''}
        </span>
      </div>
      <figcaption className={s.caption}>
        {ex.finding?.relative_location ? `${ex.finding.relative_location.charAt(0).toUpperCase()}${ex.finding.relative_location.slice(1)}. ` : ''}
        <ProvenanceBadge provenance={ex.provenance} modality={ex.modality} short />
      </figcaption>
    </figure>
  );
}
