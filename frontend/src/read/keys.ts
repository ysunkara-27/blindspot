// Shortcut list for the reading-room key help. (The first-run tutorial, not this list, now opens on a first visit.)
const SEEN_KEY = 'blindspot.keysSeen';

/** [what you press, what happens, is it a key]. Gestures are written out; keys render as <kbd>. */
export const SHORTCUTS: [string, string, boolean][] = [
  ['Pick a finding, then click the film', 'Place a mark with that name, then say how sure you are', false],
  ['Click the film', 'Place a mark, then pick a label and how sure you are', false],
  ['Drag a mark', 'Move it', false],
  ['Mouse wheel', 'Zoom at the cursor (up to 6×)', false],
  ['Drag the film', 'Pan', false],
  ['Double-click', 'Reset the view', false],
  ['M', 'Magnifier on or off (L works too)', true],
  ['1 – 5', 'How sure you are: the selected mark, or the normal call', true],
  ['Backspace', 'Delete the selected mark', true],
  ['N', 'Call it normal', true],
  ['H', 'Get a hint', true],
  ['Enter', 'Submit read; after the reveal, next case', true],
  ['A', 'Show anatomy (after you submit)', true],
  ['→', 'Next case', true],
  ['Tab to the film, then arrow keys', 'Move a crosshair (Shift = larger steps); Space places a mark there', false],
  ['+  −', 'Zoom in or out while the film has focus', true],
  ['Ctrl + Enter', 'Submit read from anywhere', true],
  ['Esc', 'Put down the picked finding, deselect, or close this list', true],
  ['?', 'Show this list', true],
];

export function markKeysSeen() {
  try { localStorage.setItem(SEEN_KEY, '1'); } catch { /* storage blocked: it will show again next visit */ }
}


/** Header text: "Case 3 of 10" when the set has a length, else "Case 3". */
export function caseLabel(index: number, total?: number | null): string {
  return total ? `Case ${index} of ${total}` : `Case ${index}`;
}
