import { describe, expect, it } from 'vitest';
import { apiRoot, normalizeBase, resolveUrl, routerBasename } from './base';

describe('normalizeBase', () => {
  it.each([
    [undefined, '/'], ['', '/'], ['/', '/'], ['./', '/'],
    ['/blindspot/', '/blindspot/'], ['/blindspot', '/blindspot/'], ['blindspot', '/blindspot/'], ['//blindspot//', '/blindspot/'],
    ['/a/b', '/a/b/'],
  ])('%s → %s', (raw, want) => expect(normalizeBase(raw)).toBe(want));
});

describe('routerBasename', () => {
  it('drops the trailing slash except at the root', () => {
    expect(routerBasename('/')).toBe('/');
    expect(routerBasename('/blindspot/')).toBe('/blindspot');
    expect(routerBasename('blindspot')).toBe('/blindspot');
  });
});

describe('apiRoot', () => {
  it('derives the API from the base path', () => {
    expect(apiRoot('/')).toBe('/api');
    expect(apiRoot('/blindspot/')).toBe('/blindspot/api');
  });
  it('an explicit override wins and loses its trailing slash', () => {
    expect(apiRoot('/blindspot/', 'https://api.example.org/api/')).toBe('https://api.example.org/api');
    expect(apiRoot('/blindspot/', '  ')).toBe('/blindspot/api');
  });
});

describe('resolveUrl', () => {
  it('re-roots server image URLs under the API root', () => {
    expect(resolveUrl('/api/cases/cxd_1/image', '/', '/api')).toBe('/api/cases/cxd_1/image');
    expect(resolveUrl('/api/cases/cxd_1/image', '/blindspot/', '/blindspot/api')).toBe('/blindspot/api/cases/cxd_1/image');
    expect(resolveUrl('/api/cases/cxd_1/image', '/blindspot/', 'https://x.org/api')).toBe('https://x.org/api/cases/cxd_1/image');
  });
  it('re-roots other root-relative assets under the base, once', () => {
    expect(resolveUrl('/mock/syn_001.png', '/blindspot/', '/blindspot/api')).toBe('/blindspot/mock/syn_001.png');
    expect(resolveUrl('/blindspot/mock/syn_001.png', '/blindspot/', '/blindspot/api')).toBe('/blindspot/mock/syn_001.png');
    expect(resolveUrl('/mock/syn_001.png', '/', '/api')).toBe('/mock/syn_001.png');
  });
  it('leaves absolute, data and relative URLs alone', () => {
    expect(resolveUrl('https://cdn.example.org/a.png', '/blindspot/', '/blindspot/api')).toBe('https://cdn.example.org/a.png');
    expect(resolveUrl('data:image/png;base64,AAAA', '/blindspot/', '/blindspot/api')).toBe('data:image/png;base64,AAAA');
    expect(resolveUrl('img/a.png', '/blindspot/', '/blindspot/api')).toBe('img/a.png');
    expect(resolveUrl('', '/blindspot/', '/blindspot/api')).toBe('');
  });
  it('does not mistake /apiary for the API', () => {
    expect(resolveUrl('/apiary/x', '/blindspot/', '/blindspot/api')).toBe('/blindspot/apiary/x');
  });
});
