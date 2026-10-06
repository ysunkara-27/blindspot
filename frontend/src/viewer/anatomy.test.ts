import { describe, expect, it } from 'vitest';
import { guardAnatomy, ringPath, unvisitedRings, zoneBox } from './anatomy';

const sq: [number, number][] = [[0, 0], [10, 0], [10, 10], [0, 10]];

describe('guardAnatomy', () => {
  it('reads a list of zones with polygons', () => {
    const a = guardAnatomy({ zones: [{ zone_id: 'right_upper_zone', polygons: [sq] }], approximate: true });
    expect(a.approximate).toBe(true);
    expect(a.zones).toEqual([{ id: 'right_upper_zone', name: 'Right upper zone', rings: [sq], reviewArea: false, area: 100 }]);
  });
  it('reads a dict of zone id → ring and keeps a server display name', () => {
    const a = guardAnatomy({ zones: { left_apex: sq, retrocardiac: { polygon: sq, display: 'Retrocardiac region' } } });
    expect(a.zones.map((z) => z.name)).toEqual(['Left apex', 'Retrocardiac region']);
  });
  it('reads the backend shape (id, human, review_area) and sorts big zones first', () => {
    const small: [number, number][] = [[0, 0], [2, 0], [2, 2], [0, 2]];
    const a = guardAnatomy({ zones: [
      { id: 'right_apex', human: 'the right apex', review_area: true, polygons: [small] },
      { id: 'right_lung', human: 'right lung', review_area: false, polygons: [sq] },
    ], approximate: false, width: 1024, height: 1024 });
    expect(a.zones.map((z) => [z.id, z.name, z.reviewArea])).toEqual([['right_lung', 'Right lung', false], ['right_apex', 'The right apex', true]]);
  });
  it('drops degenerate or malformed zones', () => {
    const a = guardAnatomy({ zones: [{ zone_id: 'x', polygons: [[[0, 0], [1, 1]]] }, { polygons: [sq] }, 'junk'] });
    expect(a.zones).toEqual([]);
    expect(guardAnatomy(null).zones).toEqual([]);
  });
  it('builds an SVG path', () => {
    expect(ringPath(sq)).toBe('M0.0 0.0L10.0 0.0L10.0 10.0L0.0 10.0Z');
  });
});

describe('unvisitedRings', () => {
  const a = guardAnatomy({ zones: [
    { id: 'left_apex', human: 'left apex', review_area: true, polygons: [[[100, 20], [180, 20], [180, 60], [100, 60]]] },
    { id: 'retrocardiac', human: 'area behind the heart', review_area: true, polygons: [[[10, 10], [12, 10], [12, 12], [10, 12]]] },
  ] });
  it('places a ring on each unvisited review area that has an outline', () => {
    const { rings, missing } = unvisitedRings(a, ['left_apex', 'right_hilum']);
    expect(rings).toEqual([{ id: 'left_apex', name: 'Left apex', cx: 140, cy: 40, rx: 40, ry: 20 }]);
    expect(missing).toEqual(['right_hilum']); // no outline: the legend lists it by name instead
  });
  it('keeps tiny zones visible with a minimum radius', () => {
    const { rings } = unvisitedRings(a, ['retrocardiac'], 9);
    expect(rings[0]).toMatchObject({ cx: 11, cy: 11, rx: 9, ry: 9 });
  });
  it('caps big zones so many unvisited areas stay readable', () => {
    const { rings } = unvisitedRings(a, ['left_apex'], 9, 30);
    expect(rings[0]).toMatchObject({ cx: 140, cy: 40, rx: 30, ry: 20 });
  });
  it('lists everything as missing when the anatomy is unavailable', () => {
    expect(unvisitedRings(null, ['left_apex', 'right_apex'])).toEqual({ rings: [], missing: ['left_apex', 'right_apex'] });
    expect(unvisitedRings(a, [])).toEqual({ rings: [], missing: [] });
  });
  it('zoneBox spans every ring of a zone', () => {
    const z = guardAnatomy({ zones: [{ id: 'z', polygons: [[[0, 0], [4, 0], [4, 4]], [[10, 2], [20, 2], [20, 9]]] }] }).zones[0];
    expect(zoneBox(z)).toEqual([0, 0, 20, 9]);
  });
});
