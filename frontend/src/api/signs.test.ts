// GET /api/signs guard (round 5): the schematic SVG is rendered inline, so only a plain drawing from our own API
// passes; everything executable, embedded or external is dropped. Also the per-label ordering.
import { describe, expect, it } from 'vitest';
import { guardSigns, safeSvg, signsForLabel } from './signs';
import { MOCK_SCHEMATICS } from './mock/signs';

const OK = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><path d="M10 10 L90 90" stroke="#35C9DD"/><circle cx="50" cy="50" r="4"/></svg>';

describe('safeSvg', () => {
  it('keeps a plain drawing', () => {
    expect(safeSvg(OK)).toBe(OK);
    expect(safeSvg(`  ${OK}\n`)).toBe(OK);
  });
  it('rejects anything that is not one <svg> element', () => {
    for (const v of ['', null, 3, '<div>x</div>', '<svg>', 'text<svg></svg>', '<svg></svg><svg></svg><script>1</script>']) expect(safeSvg(v)).toBeNull();
  });
  it('rejects scripts, handlers, embedded content and external references', () => {
    const bad = [
      '<svg><script>alert(1)</script></svg>',
      '<svg onload="alert(1)"><path d="M0 0"/></svg>',
      '<svg><path d="M0 0" onclick="x()"/></svg>',
      '<svg><foreignObject><body/></foreignObject></svg>',
      '<svg><image href="https://evil/x.png"/></svg>',
      '<svg><a href="https://evil"><path d="M0 0"/></a></svg>',
      '<svg><use xlink:href="#x"/></svg>',
      '<svg><style>path{fill:url(https://evil)}</style></svg>',
      '<svg><path d="M0 0" fill="url(#g)"/></svg>',
      '<svg><animate attributeName="x"/></svg>',
      '<svg><!-- c --><path d="M0 0"/></svg>',
      `<svg>${'x'.repeat(21_000)}</svg>`,
    ];
    for (const v of bad) expect(safeSvg(v), v.slice(0, 40)).toBeNull();
  });
});

describe('guardSigns', () => {
  it('keeps complete schematics, drops the rest and duplicates, and normalises the link', () => {
    const out = guardSigns([
      { id: 'a', name: 'A', description: 'd', labels: ['nodule', 3], svg: OK, radiopaedia_url: 'https://radiopaedia.org/articles/x' },
      { id: 'a', name: 'A again', svg: OK },
      { id: 'b', name: 'B', svg: '<svg onload="x"></svg>' },
      { id: '', name: 'C', svg: OK },
      { id: 'd', name: 'D', svg: OK, radiopaedia_url: 'http://insecure', review_status: 'student_reviewed', modality: 'cxr' },
      null, 'x',
    ]);
    expect(out.map((s) => s.id)).toEqual(['a', 'd']);
    expect(out[0]).toMatchObject({ labels: ['nodule'], radiopaedia_url: 'https://radiopaedia.org/articles/x', review_status: 'ai_draft', modality: null });
    expect(out[1]).toMatchObject({ labels: [], radiopaedia_url: null, review_status: 'student_reviewed', modality: 'cxr', description: '' });
  });
  it('accepts a {signs: [...]} envelope and nothing else', () => {
    expect(guardSigns({ signs: [{ id: 'a', name: 'A', svg: OK }] })).toHaveLength(1);
    expect(guardSigns({ nope: [] })).toEqual([]);
    expect(guardSigns(null)).toEqual([]);
  });
  it('every mock schematic passes the guard (what the drawer renders in mock mode)', () => {
    expect(guardSigns(MOCK_SCHEMATICS)).toHaveLength(MOCK_SCHEMATICS.length);
    expect(MOCK_SCHEMATICS.length).toBeGreaterThanOrEqual(10);
    expect(MOCK_SCHEMATICS.some((s) => s.labels.length === 0)).toBe(true); // bat-wing, Kerley B: not graded yet
  });
});

describe('signsForLabel', () => {
  const all = guardSigns([
    { id: 'meniscus', name: 'M', svg: OK, labels: ['effusion'] },
    { id: 'blunted', name: 'B', svg: OK, labels: ['effusion', 'pleural_thickening'] },
    { id: 'line', name: 'L', svg: OK, labels: ['pneumothorax'] },
    { id: 'batwing', name: 'W', svg: OK, labels: [] },
  ]);
  it('filters by label, keeping the API order', () => {
    expect(signsForLabel(all, 'effusion').map((s) => s.id)).toEqual(['meniscus', 'blunted']);
    expect(signsForLabel(all, 'fibrosis')).toEqual([]);
  });
  it('lists the signs drawn on the film first, and includes one the label list missed', () => {
    expect(signsForLabel(all, 'effusion', ['blunted']).map((s) => s.id)).toEqual(['blunted', 'meniscus']);
    expect(signsForLabel(all, 'effusion', ['line', 'blunted']).map((s) => s.id)).toEqual(['line', 'blunted', 'meniscus']);
  });
});
