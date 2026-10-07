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

/** Extra rows for a CT / MR case (the slice, plane and caliper keys), shown above the shared list. */
export const VOLUME_SHORTCUTS: [string, string, boolean][] = [
  ['Mouse wheel', 'Move through the slices (over a grid pane: that pane only); Ctrl + wheel zooms', false],
  ['Double-click a pane', 'Open that plane on its own; marking happens there', false],
  ['↑  ↓', 'Previous or next slice', true],
  ['PageUp  PageDown', 'Five slices back or forward', true],
  ['C', 'Caliper: drag from edge to edge to measure (for a mass-like mark, this starts its size step)', true],
  ['Enter (measuring)', 'Record the drawn measurement for the mark being measured', true],
  ['Drag with W/L on', 'Window: sideways changes the width, up and down the level', false],
];

/** The list for the key sheet: the volume rows first on a CT / MR case. ← / → move the crosshair on a volume. */
export function shortcutsFor(volume: boolean): [string, string, boolean][] {
  if (!volume) return SHORTCUTS;
  const base = SHORTCUTS.map(([k, what, isKey]): [string, string, boolean] =>
    k === 'Mouse wheel' ? ['Ctrl + wheel', 'Zoom at the cursor (up to 6×)', false]
    : k === 'Tab to the film, then arrow keys' ? ['Tab to the scan, then ← →', 'Move a crosshair (Alt + ↑ ↓ for up and down); Space places a mark there', false]
    : [k.replace(/\bfilm\b/g, 'scan'), what.replace(/\bfilm\b/g, 'scan'), isKey]);
  return [...VOLUME_SHORTCUTS, ...base];
}

export function markKeysSeen() {
  try { localStorage.setItem(SEEN_KEY, '1'); } catch { /* storage blocked: it will show again next visit */ }
}


/** Header text: "Case 3 of 10" when the set has a length, else "Case 3". */
export function caseLabel(index: number, total?: number | null): string {
  return total ? `Case ${index} of ${total}` : `Case ${index}`;
}
