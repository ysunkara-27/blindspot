import { beforeEach, describe, expect, it } from 'vitest';
import { toolForKey, TOOLS, useTools } from './tools';

describe('tool store (Point · Draw · Caliper)', () => {
  beforeEach(() => useTools.getState().reset());
  it('lists the three tools in strip order with their keys', () => {
    expect(TOOLS.map((t) => [t.id, t.key])).toEqual([['mark', 'P'], ['draw', 'D'], ['caliper', 'C']]);
    expect(toolForKey('d')).toBe('draw');
    expect(toolForKey('P')).toBe('mark');
    expect(toolForKey('x')).toBeNull();
  });
  it('starts on Point; a key toggles its tool and back to Point', () => {
    expect(useTools.getState().tool).toBe('mark');
    useTools.getState().toggleTool('draw');
    expect(useTools.getState().tool).toBe('draw');
    useTools.getState().toggleTool('draw');
    expect(useTools.getState().tool).toBe('mark');
    useTools.getState().toggleTool('caliper');
    useTools.getState().toggleTool('draw');
    expect(useTools.getState().tool).toBe('draw');
  });
  it('measure() arms the caliper for a mark; reset() returns to Point and clears the line', () => {
    useTools.getState().measure('M2');
    expect(useTools.getState()).toMatchObject({ tool: 'caliper', forMark: 'M2', caliper: null });
    useTools.getState().setCaliper({ plane: 'axial', slice: 3, p0: [0, 0], p1: [10, 0] });
    useTools.getState().reset();
    expect(useTools.getState()).toMatchObject({ tool: 'mark', forMark: null, caliper: null });
  });
});
