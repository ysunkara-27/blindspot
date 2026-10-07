// Privacy-light usage counts, feeding the site stats at ysunkara.com/stats. What leaves the browser: the site name,
// the page path, an anonymous random id this browser keeps (the same `ys-analytics-id` key the site tracker uses),
// and for clicks the event name plus an optional number. Never marks, telemetry, names, codes or answers.
// Off on localhost / 127.0.0.1, under automation (navigator.webdriver) and when VITE_ANALYTICS_URL is empty.

export const SITE = 'blindspot';
export const ID_KEY = 'ys-analytics-id';
export const DEFAULT_URL = 'https://hooraas-rides-api.sunkarayashaswi.workers.dev';
const ID_RE = /^[a-zA-Z0-9_-]{8,160}$/;
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]', '::1', '']);

export type AnalyticsEvent =
  | 'session_start' | 'film_submitted' | 'debrief_live' | 'debrief_template' | 'hint' | 'ask' | 'reference_open'
  | 'tutorial_done' | 'set_complete' | 'feedback_sent';

type Store = { getItem(k: string): string | null; setItem(k: string, v: string): void };

/** Everything the module touches from the browser, so tests pass a fake and the app passes the real globals. */
export type AnalyticsEnv = {
  /** API root; '' disables everything. */
  url: string;
  hostname: string;
  webdriver: boolean;
  storage: Store | null;
  sendBeacon: ((url: string, data: Blob) => boolean) | null;
  fetch: ((url: string, init: RequestInit) => Promise<unknown>) | null;
  randomId: () => string;
};

export type Analytics = {
  enabled: boolean;
  visitor: string;
  pageView: (path: string) => void;
  track: (event: AnalyticsEvent, value?: number) => void;
};

/** Should nothing be sent? Local development, automated browsers and an empty URL all count out. */
export function disabledReason(env: Pick<AnalyticsEnv, 'url' | 'hostname' | 'webdriver'>): string | null {
  if (!env.url.trim()) return 'no url';
  if (LOCAL_HOSTS.has(env.hostname.toLowerCase())) return 'localhost';
  if (env.webdriver) return 'webdriver';
  return null;
}

/** The anonymous id: reuse a valid stored one, else mint one and keep it (when storage allows). */
export function visitorId(storage: Store | null, randomId: () => string): string {
  try {
    const v = storage?.getItem(ID_KEY);
    if (v && ID_RE.test(v)) return v;
  } catch { /* storage blocked */ }
  const id = randomId();
  try { storage?.setItem(ID_KEY, id); } catch { /* storage blocked: the id lasts this visit */ }
  return id;
}

export function createAnalytics(env: AnalyticsEnv): Analytics {
  const why = disabledReason(env);
  const base = env.url.trim().replace(/\/+$/, '');
  const visitor = why ? '' : visitorId(env.storage, env.randomId);
  let lastPath: string | null = null;

  const send = (endpoint: string, payload: Record<string, unknown>) => {
    const body = JSON.stringify(payload);
    const url = `${base}${endpoint}`;
    try {
      // Blob of text/plain: no CORS preflight, and sendBeacon survives the page going away.
      if (env.sendBeacon && typeof Blob !== 'undefined' && env.sendBeacon(url, new Blob([body], { type: 'text/plain' }))) return;
    } catch { /* fall through to fetch */ }
    try {
      env.fetch?.(url, { method: 'POST', keepalive: true, headers: { 'Content-Type': 'text/plain' }, body })?.catch(() => { /* best effort */ });
    } catch { /* best effort */ }
  };

  if (why) return { enabled: false, visitor: '', pageView: () => {}, track: () => {} };
  return {
    enabled: true,
    visitor,
    pageView: (path: string) => {
      if (path === lastPath) return; // the same page re-rendered or its query changed: one view
      lastPath = path;
      // The contract: starts with "/", no query or hash, at most 180 characters.
      const clean = (path.split(/[?#]/)[0] || '/').slice(0, 180);
      send('/analytics/event', { site: SITE, path: clean.startsWith('/') ? clean : `/${clean}`, visitor });
    },
    track: (event: AnalyticsEvent, value?: number) => {
      const payload: Record<string, unknown> = { site: SITE, event, visitor };
      if (typeof value === 'number' && Number.isFinite(value) && value >= 0) payload.value = value; // contract: finite, ≥ 0
      send('/analytics/track', payload);
    },
  };
}

/** The real browser, read lazily so importing this module in tests or on the server is harmless. */
function browserEnv(): AnalyticsEnv {
  const w = typeof window !== 'undefined' ? window : null;
  const n = typeof navigator !== 'undefined' ? navigator : null;
  const raw = import.meta.env.VITE_ANALYTICS_URL as string | undefined;
  let storage: Store | null = null;
  try { storage = w?.localStorage ?? null; } catch { storage = null; }
  return {
    url: raw === undefined ? DEFAULT_URL : raw,
    hostname: w?.location?.hostname ?? '',
    webdriver: !!n?.webdriver,
    storage,
    sendBeacon: n && typeof n.sendBeacon === 'function' ? (u, d) => n.sendBeacon(u, d) : null,
    fetch: typeof fetch === 'function' ? (u, i) => fetch(u, i) : null,
    randomId: () => (typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `v-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`),
  };
}

let current: Analytics | null = null;

/**
 * Start counting: one page view now, then one on every route change (React Router drives history.pushState /
 * replaceState; the back button fires popstate). Safe to call more than once.
 */
export function initAnalytics(env?: AnalyticsEnv): Analytics {
  if (current) return current;
  const a = createAnalytics(env ?? browserEnv());
  current = a;
  if (!a.enabled || typeof window === 'undefined') return a;
  const view = () => a.pageView(window.location.pathname);
  view();
  const h = window.history;
  for (const m of ['pushState', 'replaceState'] as const) {
    const orig = h[m];
    h[m] = function (this: History, ...args: Parameters<History['pushState']>) {
      const r = orig.apply(this, args);
      queueMicrotask(view);
      return r;
    };
  }
  window.addEventListener('popstate', view);
  return a;
}

/** Count a click or a milestone. A no-op until initAnalytics() ran, and wherever counting is off. */
export function track(event: AnalyticsEvent, value?: number): void {
  current?.track(event, value);
}

/** Tests only. */
export function _resetAnalytics(): void {
  current = null;
}
