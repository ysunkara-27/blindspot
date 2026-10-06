// Shortcut list and first-visit flag for the reading-room key help.
const SEEN_KEY = 'blindspot.keysSeen';

/** [what you press, what happens, is it a key]. Gestures are written out; keys render as <kbd>. */
export const SHORTCUTS: [string, string, boolean][] = [
  ['Click the film', 'Place a mark, then pick a label and confidence', false],
  ['Drag a mark', 'Move it', false],
  ['Mouse wheel', 'Zoom at the cursor (up to 6×)', false],
  ['Drag the film', 'Pan', false],
  ['Double-click', 'Reset the view', false],
  ['L', 'Loupe on or off', true],
  ['1 – 5', 'Confidence for the selected mark', true],
  ['Backspace', 'Delete the selected mark', true],
  ['N', 'Call it normal', true],
  ['H', 'Ask for a hint', true],
  ['Enter', 'Submit read; after the reveal, next case', true],
  ['A', 'Show anatomy (after you submit)', true],
  ['→', 'Next case', true],
  ['Esc', 'Deselect, or close this list', true],
  ['?', 'Show this list', true],
];

/** First visit in this browser (and not under automation, so scripted runs are not blocked by the dialog). */
export function shouldShowKeysOnFirstVisit(): boolean {
  try {
    if (navigator.webdriver) return false;
    return localStorage.getItem(SEEN_KEY) !== '1';
  } catch {
    return false;
  }
}

export function markKeysSeen() {
  try { localStorage.setItem(SEEN_KEY, '1'); } catch { /* storage blocked: it will show again next visit */ }
}

