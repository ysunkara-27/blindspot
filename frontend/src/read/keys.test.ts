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
