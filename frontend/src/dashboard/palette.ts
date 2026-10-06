// Chart colours on report paper (#F3F5F6). Validated with the dataviz validator (2026-10-05):
// - learner ink #A86A00 (4.06:1) and truth ink #0F8496 (4.03:1): the cyan/amber logic of SPEC §14.1, stepped dark for paper.
// - miss types: Kundel's stages are ordered (search → recognition → decision → interpretation), so they take a one-hue
//   cyan ordinal ramp (--ordinal: monotone L, light end 2.37:1, PASS); overcalls are the learner's own call → amber
//   (adjacent to the ramp's light end: CVD ΔE 19.5, normal ΔE 23.2, PASS). No red/green anywhere.
import type { MissBucket } from './types';

export const C = {
  paper: '#F3F5F6',
  ink: '#1D2329',
  muted: '#5B6672',
  grid: '#DDE2E6',
  axis: '#B9C2CA',
  learner: '#A86A00',
  truth: '#0F8496',
  // On the dark film panel (blind-spot map) the full-strength tokens read best.
  filmCyan: '#35C9DD',
  filmAmber: '#F0A92E',
  graticule: '#8C99A6',
} as const;

export const MISS_COLOR: Record<MissBucket, string> = {
  search: '#093A42',
  recognition: '#0F6170',
  decision: '#18899B',
  interpretation: '#3BAFC1',
  overcall: '#C27D0A',
};

/** Plain-language names first (SPEC §14.3 chip copy), the Kundel term second. */
export const MISS_NAME: Record<MissBucket, { plain: string; term: string }> = {
  search: { plain: 'Never looked there', term: 'search' },
  recognition: { plain: 'Looked past it', term: 'recognition' },
  decision: { plain: 'Looked, judged it normal', term: 'decision' },
  interpretation: { plain: 'Found it, named it wrong', term: 'interpretation' },
  overcall: { plain: "Called something that isn't there", term: 'overcall' },
};

export const AXIS_TICK = { fill: C.muted, fontSize: 13, fontFamily: 'var(--font)' } as const;
