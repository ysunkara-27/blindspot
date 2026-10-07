// The pure mark builder: valid SVG with the expected elements, patient-side convention, and the small-size collapse.
import { describe, expect, it } from 'vitest';
import { brandMarkSvg, CYAN, DOT, INK, LUNG_L_PATH, LUNG_R_PATH, OFF_WHITE, PACS_DARK } from './markSvg';

const count = (s: string, tag: string) => (s.match(new RegExp(`<${tag}\\b`, 'g')) ?? []).length;

describe('brandMarkSvg', () => {
  it('is one well-formed SVG root with the eye (lungs cut out) and the dot', () => {
    const svg = brandMarkSvg();
    expect(svg.startsWith('<svg xmlns="http://www.w3.org/2000/svg"')).toBe(true);
    expect(svg.endsWith('</svg>')).toBe(true);
    expect(count(svg, 'svg')).toBe(1);
    expect(count(svg, 'path')).toBe(1);
    expect(count(svg, 'circle')).toBe(1);
    expect(count(svg, 'rect')).toBe(0);
    expect(svg).toContain('fill-rule="evenodd"');
    // Eye + two lung subpaths: three closed subpaths in the one path.
    expect((svg.match(/Z/g) ?? []).length).toBe(3);
    expect(svg).toContain(LUNG_R_PATH);
    expect(svg).toContain(LUNG_L_PATH);
    expect(svg).toContain(`fill="${OFF_WHITE}"`);
    expect(svg).toContain(`fill="${CYAN}"`);
    expect(svg).not.toMatch(/gradient/i);
  });

  it('sizes by height with a 64:40 box, and keeps the dot inside the image-right (patient LEFT) lung', () => {
    const svg = brandMarkSvg({ size: 20 });
    expect(svg).toContain('width="32" height="20" viewBox="0 0 64 40"');
    // Patient RIGHT lung is on the image LEFT and larger; the dot sits in the image-right lung, upper third.
    const xs = (p: string) => p.match(/-?\d+(\.\d+)?/g)!.map(Number).filter((_, i) => i % 2 === 0);
    expect(Math.max(...xs(LUNG_R_PATH))).toBeLessThan(Math.min(...xs(LUNG_L_PATH)));
    expect(DOT.cx).toBeGreaterThan(Math.min(...xs(LUNG_L_PATH)) + DOT.r);
    expect(DOT.cx).toBeLessThan(Math.max(...xs(LUNG_L_PATH)) - DOT.r);
    expect(DOT.cy).toBeLessThan(5.5 + (31.8 - 5.5) / 2.5);
  });

  it('puts a rounded tile behind a centred mark when a ground is given', () => {
    const svg = brandMarkSvg({ ground: PACS_DARK, size: 180, simple: false });
    expect(svg).toContain('width="180" height="180" viewBox="0 0 64 64"');
    expect(count(svg, 'rect')).toBe(1);
    expect(svg).toContain(`rx="12" fill="${PACS_DARK}"`);
    expect(count(svg, 'path')).toBe(1);
    expect(count(svg, 'circle')).toBe(1);
  });

  it('collapses to eye + one dot under 14 px tall (favicon at 16 px), and can be forced either way', () => {
    const auto = brandMarkSvg({ ground: PACS_DARK, size: 16 });
    expect((auto.match(/Z/g) ?? []).length).toBe(1);
    expect(auto).not.toContain(LUNG_R_PATH);
    expect(count(auto, 'circle')).toBe(1);
    expect((brandMarkSvg({ size: 13 }).match(/Z/g) ?? []).length).toBe(1);
    expect((brandMarkSvg({ size: 14 }).match(/Z/g) ?? []).length).toBe(3);
    expect((brandMarkSvg({ size: 13, simple: false }).match(/Z/g) ?? []).length).toBe(3);
    expect((brandMarkSvg({ size: 200, simple: true }).match(/Z/g) ?? []).length).toBe(1);
  });

  it('takes the light and monochrome colours', () => {
    const svg = brandMarkSvg({ fill: INK, dot: INK });
    expect(svg).toContain(`fill="${INK}"`);
    expect(svg).not.toContain(CYAN);
    expect(brandMarkSvg({ attrs: 'class="m"' })).toContain('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="40" viewBox="0 0 64 40" class="m">');
  });
});
