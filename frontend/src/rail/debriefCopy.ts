// Debrief tag and notice copy (SPEC §14.4), shared by the rail and the About page.
export const PROVENANCE: Record<string, string> = {
  ai_draft: 'AI draft — not yet reviewed',
  student_reviewed: 'Student reviewed',
  radiologist_reviewed: 'Radiologist reviewed',
};
export const SOURCE: Record<string, string> = { live: 'Claude debrief', cache: 'Claude (cached)', template: 'Built-in' };
export const SOURCE_TITLE: Record<string, string> = {
  live: 'Written by Claude for this read from the computed facts, and passed the validator.',
  cache: 'Written by Claude earlier for the same facts; the saved text is shown.',
  template: 'A fixed explanation filled from the computed facts.',
};
