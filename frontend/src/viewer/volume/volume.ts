// Decoded volumes (voxels: int16; label mask: uint8), slice extraction for the three planes, and a per-URL cache.
// Both files are gzip streams of the raw z,y,x-contiguous array (little-endian for the int16 voxels).
import { planeGeom, type Plane, type VolumeMeta } from './planes';

export type Volume = { shape: [number, number, number]; spacing: [number, number, number]; data: Int16Array };
export type MaskVolume = { shape: [number, number, number]; data: Uint8Array };

export const DECOMPRESS_SUPPORTED = typeof DecompressionStream === 'function';

/** Raw bytes of a gzipped asset, decoded in the browser. Throws when the browser cannot gunzip. */
export async function fetchGunzip(url: string, fetchFn: typeof fetch = fetch): Promise<ArrayBuffer> {
  if (!DECOMPRESS_SUPPORTED) throw new Error('This browser cannot decompress the scan (no DecompressionStream).');
  const res = await fetchFn(url, { credentials: 'same-origin' });
  if (!res.ok || !res.body) throw new Error(`${res.status} fetching ${url}`);
  // A server that applies Content-Encoding: gzip hands us raw bytes already; otherwise the gzip magic is there and
  // we gunzip ourselves.
  const buf0 = await res.arrayBuffer();
  const u = new Uint8Array(buf0);
  const gz = u.length >= 2 && u[0] === 0x1f && u[1] === 0x8b;
  if (!gz) return buf0;
  const ds = new DecompressionStream('gzip');
  const stream = new Blob([buf0]).stream().pipeThrough(ds);
  return new Response(stream).arrayBuffer();
}

const shape3 = (meta: VolumeMeta): [number, number, number] => [meta.shape[0] | 0, meta.shape[1] | 0, meta.shape[2] | 0];
const voxels = (meta: VolumeMeta) => shape3(meta).reduce((a, b) => a * b, 1);

/** int16 little-endian voxels. */
export function decodeVolume(buf: ArrayBuffer, meta: VolumeMeta): Volume {
  const n = voxels(meta);
  if (buf.byteLength < n * 2) throw new Error(`Scan data is ${buf.byteLength} bytes; expected ${n * 2}.`);
  const dv = new DataView(buf);
  const data = new Int16Array(n);
  // Int16Array over the buffer would assume the platform's endianness; read explicitly.
  for (let i = 0; i < n; i++) data[i] = dv.getInt16(i * 2, true);
  const spacing = meta.spacing as [number, number, number];
  return { shape: shape3(meta), spacing: [spacing[0], spacing[1], spacing[2]], data };
}

export function decodeMask(buf: ArrayBuffer, meta: VolumeMeta): MaskVolume {
  const n = voxels(meta);
  if (buf.byteLength < n) throw new Error(`Mask data is ${buf.byteLength} bytes; expected ${n}.`);
  return { shape: shape3(meta), data: new Uint8Array(buf.slice(0, n)) };
}

/** The in-plane image of one slice: w×h values, row-major (v then u), in the plane's across/down order. */
export function extractSlice<T extends Int16Array | Uint8Array>(data: T, shape: [number, number, number], plane: Plane, slice: number): T {
  const [nz, ny, nx] = shape;
  const g = planeGeom({ shape, spacing: [1, 1, 1] }, plane);
  const s = Math.min(g.n - 1, Math.max(0, Math.round(slice)));
  const Ctor = data.constructor as { new (n: number): T };
  if (plane === 'axial') return data.subarray(s * ny * nx, (s + 1) * ny * nx) as T;
  const out = new Ctor(g.w * g.h);
  if (plane === 'coronal') {
    for (let z = 0; z < nz; z++) out.set(data.subarray((z * ny + s) * nx, (z * ny + s) * nx + nx), z * nx);
  } else {
    for (let z = 0; z < nz; z++) for (let y = 0; y < ny; y++) out[z * ny + y] = data[(z * ny + y) * nx + s];
  }
  return out;
}

/** Decoded arrays are cached per URL, so a case re-read or a review of it never decodes twice. */
const cache = new Map<string, Promise<ArrayBuffer>>();
export function cachedGunzip(url: string): Promise<ArrayBuffer> {
  let p = cache.get(url);
  if (!p) {
    p = fetchGunzip(url).catch((e) => { cache.delete(url); throw e; });
    cache.set(url, p);
  }
  return p;
}
export const clearVolumeCache = () => cache.clear();
