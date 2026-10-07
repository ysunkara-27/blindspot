// "My search" starts off; the choice is remembered once the learner has toggled it (round 5).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { searchDefault } from './searchPref';

const store = new Map<string, string>();
const fake = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => { store.set(k, v); }, removeItem: (k: string) => { store.delete(k); }, clear: () => store.clear() };

describe('searchDefault', () => {
  beforeEach(() => { store.clear(); vi.stubGlobal('localStorage', fake); });
  afterEach(() => vi.unstubAllGlobals());
  it('is off on the first-ever reveal', () => {
    expect(searchDefault()).toBe(false);
  });
  it('remembers a toggle', () => {
    localStorage.setItem('blindspot.showSearch', '1');
    expect(searchDefault()).toBe(true);
    localStorage.setItem('blindspot.showSearch', '0');
    expect(searchDefault()).toBe(false);
  });
  it('is off when storage is blocked', () => {
    vi.stubGlobal('localStorage', { getItem: () => { throw new Error('blocked'); } });
    expect(searchDefault()).toBe(false);
  });
});
