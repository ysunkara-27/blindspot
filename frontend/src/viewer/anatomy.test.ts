import { describe, expect, it } from 'vitest';
import { guardAnatomy, ringPath } from './anatomy';

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
