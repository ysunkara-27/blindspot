// Base-path helpers for hosting under a sub-path (e.g. https://ysunkara.com/blindspot/). Pure functions: used by
// vite.config.ts (Vite `base`), the router (`basename`), the API client and server-provided image URLs.

/** "/blindspot" | "blindspot/" | "" → "/blindspot/" | "/". Always a leading and a trailing slash. */
export function normalizeBase(raw: string | undefined | null): string {
  const t = (raw ?? '').trim();
  if (!t || t === '/' || t === '.' || t === './') return '/';
  const inner = t.replace(/^\/+|\/+$/g, '');
  return inner ? `/${inner}/` : '/';
}

/** React Router basename: "/blindspot/" → "/blindspot"; "/" → "/". */
export function routerBasename(base: string): string {
  const b = normalizeBase(base);
  return b === '/' ? '/' : b.slice(0, -1);
}

/** API root without a trailing slash: an explicit override (VITE_API_BASE) wins, else `${base}api`. */
export function apiRoot(base: string, override?: string | null): string {
  const o = (override ?? '').trim();
  if (o) return o.replace(/\/+$/, '');
  return `${normalizeBase(base)}api`;
}

/**
 * Server-provided URLs (e.g. NextCase.case.image_url = "/api/cases/x/image") are written for a root deployment.
 * Re-root them: "/api/…" → `${api}/…`, other root-relative paths → `${base}…`. Absolute and data URLs pass through.
 */
export function resolveUrl(url: string, base: string, api: string): string {
  if (!url) return url;
  if (/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(url)) return url; // http:, https:, data:, blob:, protocol-relative
  const b = normalizeBase(base);
  if (url === '/api' || url.startsWith('/api/')) return `${api}${url.slice(4)}`;
  if (url.startsWith(b)) return url; // already under the base
  if (url.startsWith('/')) return `${b}${url.slice(1)}`;
  return url;
}
