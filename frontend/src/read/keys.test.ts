import { describe, expect, it } from 'vitest';
import { caseLabel, SHORTCUTS } from './keys';

describe('caseLabel', () => {
  it('says "Case 3 of 10" when the set has a length, else "Case 3"', () => {
    expect(caseLabel(3, 10)).toBe('Case 3 of 10');
    expect(caseLabel(3, null)).toBe('Case 3');
    expect(caseLabel(3)).toBe('Case 3');
    expect(caseLabel(1, 0)).toBe('Case 1');
  });
});

describe('SHORTCUTS', () => {
  it('calls the lens the magnifier and never mentions a loupe', () => {
    const text = SHORTCUTS.map(([k, what]) => `${k} ${what}`).join(' | ');
    expect(text).toContain('Magnifier on or off');
    expect(text).not.toMatch(/loupe/i);
  });
});

describe('shortcutsFor', () => {
  it('adds the slice, plane and caliper keys on a volume and leaves the X-ray list alone', async () => {
    const { shortcutsFor, SHORTCUTS, VOLUME_SHORTCUTS } = await import('./keys');
    expect(shortcutsFor(false)).toBe(SHORTCUTS);
    const v = shortcutsFor(true);
    expect(v.slice(0, VOLUME_SHORTCUTS.length)).toEqual(VOLUME_SHORTCUTS);
    expect(v.map(([k]) => k)).toContain('Ctrl + wheel');
    expect(v.map(([k]) => k)).not.toContain('Mouse wheel'.repeat(2));
    expect(v.filter(([k]) => k === 'C')).toHaveLength(1);
  });
});
