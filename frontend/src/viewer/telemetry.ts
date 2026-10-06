// Telemetry buffer (SPEC §5.4). Pointer moves (and pan) throttled to 33 ms; every other event is kept.
// x/y are image px and only present while the pointer is over the image. Sent whole with the submit.
import type { TelemetryEvent } from '../types/contracts';

export const THROTTLE_MS = 33;
/** Pointer events arrive on display frames (8.3 / 16.7 ms); a strict 33 ms gate would skip to every 40–50 ms.
 *  Accept a sample up to 4 ms early so a 60 Hz or 120 Hz pointer yields ~30 Hz. */
const JITTER_MS = 4;
export const MAX_EVENTS = 20_000;

type Kind = TelemetryEvent['kind'];
export type Sample = { x?: number; y?: number; zoom: number; vp: [number, number, number, number]; loupe: boolean };

const r1 = (n: number) => Math.round(n * 10) / 10;

/** Uniformly downsample to at most `cap` items, always keeping the first and last. */
export function downsample<T>(arr: T[], cap: number): T[] {
  if (arr.length <= cap) return arr.slice();
  if (cap <= 1) return arr.slice(0, cap);
  const out: T[] = [];
  const step = (arr.length - 1) / (cap - 1);
  for (let i = 0; i < cap; i++) out.push(arr[Math.round(i * step)]);
  return out;
}

export class TelemetryBuffer {
  private events: TelemetryEvent[] = [];
  private t0 = 0;
  private lastThrottled = -Infinity;
  private readonly now: () => number;
  private readonly cap: number;

  constructor(now: () => number = () => performance.now(), cap = MAX_EVENTS) {
    this.now = now;
    this.cap = cap;
    this.t0 = now();
  }

  /** Reset the clock: t is "ms since case shown". */
  start(): void {
    this.events = [];
    this.t0 = this.now();
    this.lastThrottled = -Infinity;
  }

  get length(): number {
    return this.events.length;
  }

  /** Returns true if the event was recorded. */
  push(kind: Kind, s: Sample): boolean {
    const t = this.now() - this.t0;
    if (kind === 'move' || kind === 'pan') {
      if (t - this.lastThrottled < THROTTLE_MS - JITTER_MS) return false;
      this.lastThrottled = t;
    }
    const e: TelemetryEvent = { t: r1(t), kind, zoom: Math.round(s.zoom * 1000) / 1000, vp: s.vp.map(r1) as TelemetryEvent['vp'], loupe: s.loupe };
    if (s.x !== undefined && s.y !== undefined) {
      e.x = r1(s.x);
      e.y = r1(s.y);
    }
    this.events.push(e);
    // Keep memory bounded on very long reads; the final snapshot is downsampled to the cap anyway.
    if (this.events.length > 2 * this.cap) this.events = downsample(this.events, this.cap);
    return true;
  }

  snapshot(): TelemetryEvent[] {
    return downsample(this.events, this.cap);
  }
}
