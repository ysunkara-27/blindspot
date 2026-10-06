// Chart colours on report paper (#F3F5F6). One colour logic, the same as the reading room (SPEC §14.1):
//   cyan  = expert truth, and what you found of it
//   amber = you: your marks, your misses, your false alarms
// Validated with the dataviz palette validator (2026-10-06, --pairs all, surface #F3F5F6): learner #A86A00 and truth
// #0086A0 pass the lightness band, chroma floor (the old #0F8496 sat just under it), CVD ΔE 17.5 (protan), normal ΔE 21.9
// and 3:1 contrast. No red/green anywhere.
// Miss types are NOT told apart by colour: every miss bar is the learner's amber, and identity comes from position and a
// direct label (a labelled row per type). Four teal shades could not be told apart; a legend should not be a puzzle.
import type { MissBucket } from './types';

export const C = {
  paper: '#F3F5F6',
  ink: '#1D2329',
  muted: '#5B6672',
  grid: '#DDE2E6',
  axis: '#B9C2CA',
  track: '#E2E7EB',
  learner: '#A86A00',
  truth: '#0086A0',
  // On the dark film panel (blind-spot map) the full-strength SPEC tokens read best; found and missed also differ in
  // shape (filled dot vs hollow ring), so the pair never rests on hue alone.
  filmCyan: '#35C9DD',
  filmAmber: '#F0A92E',
  graticule: '#8C99A6',
} as const;

/** Plain-language name first (SPEC §14.3 chip copy), one line of explanation, the Kundel term last (tooltip, table). */
export const MISS_NAME: Record<MissBucket, { plain: string; explain: string; term: string }> = {
  search: { plain: 'Never looked there', explain: 'Your cursor, magnifier and zoom never reached the finding.', term: 'search' },
  recognition: { plain: 'Looked past it', explain: 'You passed over the finding without stopping.', term: 'recognition' },
  decision: { plain: 'Looked, judged it normal', explain: 'You stopped on the finding, then left it unmarked.', term: 'decision' },
  interpretation: { plain: 'Found it, named it wrong', explain: 'Your mark was on the finding, under a different name.', term: 'interpretation' },
  overcall: { plain: "Called something that isn't there", explain: 'A mark or a call with no finding behind it.', term: 'overcall' },
};

export const AXIS_TICK = { fill: C.muted, fontSize: 13, fontFamily: 'var(--font)' } as const;
