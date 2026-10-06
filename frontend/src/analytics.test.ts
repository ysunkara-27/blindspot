import { describe, expect, it, vi } from 'vitest';
import { createAnalytics, disabledReason, ID_KEY, visitorId, type AnalyticsEnv } from './analytics';

function fakeStore(init: Record<string, string> = {}) {
  const m = new Map(Object.entries(init));
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => { m.set(k, v); }, map: m };
}

function env(over: Partial<AnalyticsEnv> = {}) {
  const beacon = vi.fn((_u: string, _d: Blob) => true);
  const fetch = vi.fn((_u: string, _i: RequestInit) => Promise.resolve({}));
  const e: AnalyticsEnv = {
    url: 'https://stats.example.test', hostname: 'www.ysunkara.com', webdriver: false,
    storage: fakeStore(), sendBeacon: beacon, fetch, randomId: () => 'abcdef12-0000-4000-8000-000000000001', ...over,
  };
  return { e, beacon, fetch };
}

const beaconJson = async (beacon: ReturnType<typeof vi.fn>, i = 0) => {
  const [url, blob] = beacon.mock.calls[i] as [string, Blob];
  expect(blob.type).toBe('text/plain');
  return { url, body: JSON.parse(await blob.text()) as Record<string, unknown> };
};

describe('visitorId', () => {
  it('reuses a valid stored id and never rewrites it', () => {
    const st = fakeStore({ [ID_KEY]: 'kept-id-12345' });
    expect(visitorId(st, () => 'new')).toBe('kept-id-12345');
    expect(st.map.get(ID_KEY)).toBe('kept-id-12345');
  });
  it('replaces a malformed id and stores the new one', () => {
    const st = fakeStore({ [ID_KEY]: 'bad id!' });
    expect(visitorId(st, () => 'fresh-uuid-1234')).toBe('fresh-uuid-1234');
    expect(st.map.get(ID_KEY)).toBe('fresh-uuid-1234');
  });
  it('works without storage', () => {
    expect(visitorId(null, () => 'memory-only-1')).toBe('memory-only-1');
  });
});

describe('disabledReason', () => {
  it.each([
    ['localhost', { url: 'https://x', hostname: 'localhost', webdriver: false }, 'localhost'],
    ['127.0.0.1', { url: 'https://x', hostname: '127.0.0.1', webdriver: false }, 'localhost'],
    ['webdriver', { url: 'https://x', hostname: 'www.ysunkara.com', webdriver: true }, 'webdriver'],
    ['empty url', { url: '', hostname: 'www.ysunkara.com', webdriver: false }, 'no url'],
    ['production', { url: 'https://x', hostname: 'www.ysunkara.com', webdriver: false }, null],
  ])('%s', (_n, e, want) => {
    expect(disabledReason(e)).toBe(want);
  });
});

describe('createAnalytics', () => {
  it('posts a page view with only site, path and the anonymous id', async () => {
    const { e, beacon } = env();
    const a = createAnalytics(e);
    expect(a.enabled).toBe(true);
    a.pageView('/blindspot/read');
    expect(beacon).toHaveBeenCalledTimes(1);
    const { url, body } = await beaconJson(beacon);
    expect(url).toBe('https://stats.example.test/analytics/event');
    expect(body).toEqual({ site: 'blindspot', path: '/blindspot/read', visitor: 'abcdef12-0000-4000-8000-000000000001' });
  });

  it('counts the same path once until the path changes', () => {
    const { e, beacon } = env();
    const a = createAnalytics(e);
    a.pageView('/read');
    a.pageView('/read');
    a.pageView('/about');
    a.pageView('/read');
    expect(beacon).toHaveBeenCalledTimes(3);
  });

  it('posts a tracked event, with a value only when one is given', async () => {
    const { e, beacon } = env();
    const a = createAnalytics(e);
    a.track('film_submitted');
    a.track('set_complete', 10);
    a.track('hint', Number.NaN);
    a.track('hint', -3);
    const first = await beaconJson(beacon, 0);
    expect(first.url).toBe('https://stats.example.test/analytics/track');
    expect(first.body).toEqual({ site: 'blindspot', event: 'film_submitted', visitor: 'abcdef12-0000-4000-8000-000000000001' });
    expect((await beaconJson(beacon, 1)).body).toEqual({ site: 'blindspot', event: 'set_complete', visitor: 'abcdef12-0000-4000-8000-000000000001', value: 10 });
    expect((await beaconJson(beacon, 2)).body).not.toHaveProperty('value');
    expect((await beaconJson(beacon, 3)).body).not.toHaveProperty('value');
  });

  it('falls back to fetch keepalive when sendBeacon is missing or refuses', () => {
    const { e, fetch } = env({ sendBeacon: () => false });
    createAnalytics(e).track('ask');
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('https://stats.example.test/analytics/track');
    expect(init.method).toBe('POST');
    expect(init.keepalive).toBe(true);
    expect(JSON.parse(init.body as string)).toEqual({ site: 'blindspot', event: 'ask', visitor: 'abcdef12-0000-4000-8000-000000000001' });
    const { e: e2, fetch: f2 } = env({ sendBeacon: null });
    createAnalytics(e2).pageView('/');
    expect(f2).toHaveBeenCalledTimes(1);
  });

  it('keeps the path to the contract: no query or hash, at most 180 characters', async () => {
    const { e, beacon } = env();
    const a = createAnalytics(e);
    a.pageView('/blindspot/read?tutorial=1#x');
    expect((await beaconJson(beacon, 0)).body.path).toBe('/blindspot/read');
    a.pageView(`/${'a'.repeat(300)}`);
    expect(((await beaconJson(beacon, 1)).body.path as string).length).toBe(180);
  });

  it('strips a trailing slash from the url', async () => {
    const { e, beacon } = env({ url: 'https://stats.example.test/' });
    createAnalytics(e).pageView('/');
    expect((await beaconJson(beacon)).url).toBe('https://stats.example.test/analytics/event');
  });

  it.each([
    ['localhost', { hostname: 'localhost' }],
    ['127.0.0.1', { hostname: '127.0.0.1' }],
    ['webdriver', { webdriver: true }],
    ['empty url', { url: '' }],
  ])('sends nothing and mints no id: %s', (_n, over) => {
    const st = fakeStore();
    const { e, beacon, fetch } = env({ ...over, storage: st });
    const a = createAnalytics(e);
    expect(a.enabled).toBe(false);
    a.pageView('/read');
    a.track('session_start');
    expect(beacon).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
    expect(st.map.has(ID_KEY)).toBe(false);
  });

  it('keeps going when storage throws', () => {
    const throwing = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
    const { e, beacon } = env({ storage: throwing });
    const a = createAnalytics(e);
    expect(a.enabled).toBe(true);
    a.track('hint');
    expect(beacon).toHaveBeenCalledTimes(1);
  });
});
