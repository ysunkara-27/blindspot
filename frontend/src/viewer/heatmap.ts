// Search-trace heatmap (SPEC §7.4, §14.3 step 1). Amber density ramp; drawn at 45% opacity by the viewer.
// Either colourise the server PNG (any greyscale or alpha density works) or splat the telemetry client-side.
import type { TelemetryEvent } from '../types/contracts';

export const GRID = 256;

/** Dwell-weighted samples binned to a GRID×GRID array, then separable gaussian blur (σ = ρ = 0.035·W). */
export function densityFromTelemetry(events: TelemetryEvent[], imgW: number, imgH: number): Float32Array {
  const g = new Float32Array(GRID * GRID);
  for (let i = 0; i + 1 < events.length; i++) {
    const e = events[i];
    if (e.x === undefined || e.y === undefined) continue;
    const dt = Math.min(events[i + 1].t - e.t, 250);
    if (dt <= 0) continue;
    const gx = Math.min(GRID - 1, Math.max(0, Math.floor((e.x / imgW) * GRID)));
    const gy = Math.min(GRID - 1, Math.max(0, Math.floor((e.y / imgH) * GRID)));
    g[gy * GRID + gx] += dt;
  }
  const sigma = 0.035 * GRID;
  return blur(g, sigma);
}

function blur(src: Float32Array, sigma: number): Float32Array {
  const r = Math.ceil(sigma * 4); // 4σ: no visible square edge from kernel truncation
  const k: number[] = [];
  let sum = 0;
  for (let i = -r; i <= r; i++) { const v = Math.exp(-(i * i) / (2 * sigma * sigma)); k.push(v); sum += v; }
  for (let i = 0; i < k.length; i++) k[i] /= sum;
  const tmp = new Float32Array(src.length);
  const out = new Float32Array(src.length);
  for (let y = 0; y < GRID; y++) {
    for (let x = 0; x < GRID; x++) {
      let a = 0;
      for (let i = -r; i <= r; i++) { const xx = x + i; if (xx >= 0 && xx < GRID) a += src[y * GRID + xx] * k[i + r]; }
      tmp[y * GRID + x] = a;
    }
  }
  for (let y = 0; y < GRID; y++) {
    for (let x = 0; x < GRID; x++) {
      let a = 0;
      for (let i = -r; i <= r; i++) { const yy = y + i; if (yy >= 0 && yy < GRID) a += tmp[yy * GRID + x] * k[i + r]; }
      out[y * GRID + x] = a;
    }
  }
  return out;
}

/** Map density 0..max → amber ramp RGBA (transparent → grease-pencil amber → pale amber at the peak). */
export function rampPixel(v: number): [number, number, number, number] {
  const t = Math.min(1, Math.max(0, v));
  const e = Math.min(1, Math.max(0, (t - 0.1) / 0.45));
  const a = Math.round(255 * e * e * (3 - 2 * e)); // smoothstep: soft edges, no threshold ring
  if (a === 0) return [0, 0, 0, 0];
  const r = 240 + Math.round(15 * t);
  const g = 169 + Math.round(60 * t * t);
  const b = 46 + Math.round(120 * t * t);
  return [r, g, b, a];
}

export function densityToDataUrl(d: Float32Array, w = GRID, h = GRID): string | null {
  let max = 0;
  for (const v of d) if (v > max) max = v;
  if (max <= 0) return null;
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  const img = ctx.createImageData(w, h);
  for (let i = 0; i < d.length; i++) {
    // sqrt lifts short glances so a quick pass still shows as a faint trace
    const [r, g, b, a] = rampPixel(Math.sqrt(d[i] / max));
    img.data[i * 4] = r; img.data[i * 4 + 1] = g; img.data[i * 4 + 2] = b; img.data[i * 4 + 3] = a;
  }
  ctx.putImageData(img, 0, 0);
  return canvas.toDataURL('image/png');
}

/** Colourise a server heatmap PNG (greyscale density, or an alpha-coded density) with the same ramp. */
export async function colorizeServerHeatmap(b64: string): Promise<string | null> {
  const img = new Image();
  img.src = b64.startsWith('data:') ? b64 : `data:image/png;base64,${b64}`;
  await img.decode();
  const canvas = document.createElement('canvas');
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  ctx.drawImage(img, 0, 0);
  const px = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const d = new Float32Array(canvas.width * canvas.height);
  for (let i = 0; i < d.length; i++) {
    const r = px.data[i * 4], g = px.data[i * 4 + 1], b = px.data[i * 4 + 2], a = px.data[i * 4 + 3];
    d[i] = (a / 255) * (Math.max(r, g, b) / 255);
  }
  return densityToDataUrl(d, canvas.width, canvas.height);
}
