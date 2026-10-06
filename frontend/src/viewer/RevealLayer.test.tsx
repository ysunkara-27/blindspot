// Structure of the reveal drawing (round 3 audit fixes), rendered to static markup: no browser needed.
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { Arrow, RevealFinding } from '../types/contracts';
import { RevealLayer, type RevealView } from './RevealLayer';

const finding = (id: string, result: RevealFinding['result'], x: number, y: number): RevealFinding => ({
  finding_id: id, label: 'nodule', display: 'Nodule', kind: 'focal', polygon: null, bbox: [x, y, x + 40, y + 40],
  centroid: [x + 20, y + 20], side: 'right', zones: [], primary_zone: 'right_mid_zone', relative_location: 'right mid zone', result,
});
const view = (over: Partial<RevealView>): RevealView => ({ findings: [], marks: [], arrows: [], heatmapUrl: null, showTrace: true, ...over });
const draw = (v: RevealView, marks: { mark_id: string; x: number; y: number }[] = []) =>
  renderToStaticMarkup(<RevealLayer reveal={v} width={1024} height={1024} k={1.6} strokePx={2} marks={marks} />);
const count = (html: string, re: RegExp) => (html.match(re) ?? []).length;

describe('RevealLayer', () => {
  it('a missed finding with no wrong mark gets a halo on its outline and no arrow', () => {
    const centre: Arrow = { from_mark: null, to_finding: 'F1', text: 'Here: right mid zone', from_xy: null, to_xy: [320, 420] };
    const html = draw(view({ findings: [finding('F1', 'missed_search', 300, 400)], arrows: [centre] }));
    expect(html).toContain('data-testid="halo-F1"');
    expect(html).not.toContain('data-testid="arrow-F1"');
    expect(html).not.toContain('data-testid="arrow-label"');
    expect(html).not.toContain('Here: right mid zone');
  });

  it('an arrow runs from the learner\'s wrong mark, and then the outline needs no halo', () => {
    const a: Arrow = { from_mark: 'M1', to_finding: 'F1', text: 'From M1: up and toward the patient\'s left', label: 'higher, other lung', from_xy: [100, 800], to_xy: [320, 420] };
    const html = draw(view({ findings: [finding('F1', 'missed_search', 300, 400)], arrows: [a], marks: [{ mark_id: 'M1', result: 'false_positive' }] }), [{ mark_id: 'M1', x: 100, y: 800 }]);
    expect(html).toContain('data-testid="arrow-F1"');
    expect(html).not.toContain('data-testid="halo-F1"');
    expect(html).toContain('data-label="higher, other lung"');
  });

  it('found findings get neither a halo nor a "missed" tag', () => {
    const html = draw(view({ findings: [finding('F1', 'found', 300, 400)] }));
    expect(html).not.toContain('halo-F1');
    expect(html).not.toContain('>missed<');
    expect(html).toContain('F1 · Nodule');
  });

  it('writes identical arrow labels from the same mark once', () => {
    const mk = (to: string): Arrow => ({ from_mark: 'M1', to_finding: to, text: `to ${to}`, label: 'other lung: left lower zone', from_xy: [100, 800] });
    const html = draw(
      view({ findings: [finding('F1', 'missed_search', 600, 600), finding('F2', 'missed_search', 760, 700)], arrows: [mk('F1'), mk('F2')] }),
      [{ mark_id: 'M1', x: 100, y: 800 }],
    );
    expect(count(html, /data-testid="arrow-F\d"/g)).toBe(2); // both arrows are drawn
    expect(count(html, /data-testid="arrow-label"/g)).toBe(1); // the words appear once
  });

  it('every label sits on a solid pill (no stroked halo text)', () => {
    const html = draw(view({ findings: [finding('F1', 'missed_decision', 300, 400), finding('F2', 'found', 600, 200)] }));
    expect(count(html, /data-testid="label-F\d"><rect/g)).toBe(2);
    expect(html).not.toMatch(/stroke-width:[^;"]*;?[^"]*"[^>]*>F1 · Nodule/);
  });

  it('draws "not visited" rings only with My search on', () => {
    const unvisited = [{ id: 'left_apex', name: 'Left apex', cx: 700, cy: 150, rx: 60, ry: 40 }];
    const on = draw(view({ unvisited }));
    expect(on).toContain('data-testid="unvisited-left_apex"');
    expect(on).toContain('>not visited<');
    expect(on).toContain('Left apex: not visited');
    const off = draw(view({ unvisited, showTrace: false }));
    expect(off).not.toContain('unvisited-left_apex');
    expect(off).not.toContain('not visited');
  });

  it('shows the trace image only with a heatmap and My search on', () => {
    expect(draw(view({ heatmapUrl: 'data:image/png;base64,AAAA' }))).toContain('data-testid="search-trace"');
    expect(draw(view({ heatmapUrl: 'data:image/png;base64,AAAA', showTrace: false }))).not.toContain('search-trace');
    expect(draw(view({ heatmapUrl: null }))).not.toContain('search-trace');
  });
});
