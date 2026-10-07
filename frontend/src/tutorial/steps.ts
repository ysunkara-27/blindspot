// First-run tutorial (round 3): the steps, when it opens, and where each coach mark sits. Pure logic, unit-tested.

/** Set to '1' when the tutorial is finished or skipped. The start page reads it to decide on `/read?tutorial=1`. */
export const TUTORIAL_KEY = 'bs_tutorial_done';

export function markTutorialDone() {
  try { localStorage.setItem(TUTORIAL_KEY, '1'); } catch { /* storage blocked: it may open again next visit */ }
}
export function tutorialDone(): boolean {
  try { return localStorage.getItem(TUTORIAL_KEY) != null; } catch { return true; }
}

export type Step = {
  id: string;
  /** CSS selector of the real control this step points at. */
  target: string;
  title: string;
  body: string;
  /** Used when the target is not on the page (e.g. hints are off in a test set). Omit to drop the step instead. */
  fallback?: { target: string; title: string; body: string };
  /** Round 4: a step that only makes sense on a CT / MR volume. Never shown on a chest film. */
  volumetric?: boolean;
};

export const STEPS: Step[] = [
  {
    id: 'film', target: '[data-tour="film"]',
    title: 'Look over the whole film first',
    body: 'Scroll the wheel to zoom and drag to pan; double-click resets the view. Brightness, contrast and invert are in the bar under the film.',
  },
  {
    // Volumes only (after the film step): the slice scroller. Target: the viewer's slice control.
    id: 'slices', target: '[data-tour="slices"]', volumetric: true,
    title: 'Scroll through the slices',
    body: 'A study is a stack of slices. Scroll the wheel over the image, press ↑ ↓, or drag the slider to move through it. A finding is only on the slices that hold it, so look at all of them.',
  },
  {
    id: 'magnifier', target: '[data-tour="magnifier"]',
    title: 'Turn the magnifier on for fine detail',
    body: 'A 2.5× lens that follows your cursor. It starts off: press M, or this button, whenever you want it.',
  },
  {
    id: 'pick', target: '[data-tour="pick"]',
    title: 'Pick what you see, then click where it is',
    body: 'Choose a finding here and your next click on the film places a mark with that name. You can also click the film first and name the mark there.',
  },
  {
    id: 'confidence', target: '[data-tour="confidence"]',
    title: 'Say how sure you are',
    body: 'Each mark asks “How sure are you?”, from 1 (guessing) to 5 (certain). Nothing is chosen for you, and the read cannot be submitted until you answer.',
  },
  {
    // Volumes only: the measure tool, asked after a mass-like mark.
    id: 'measure', target: '[data-tour="measure"]', volumetric: true,
    title: 'Measure what you mark',
    body: 'For a mass-like finding you are asked for its longest diameter on the slice where it looks biggest. Press the measure button, then click both ends. The reference is compared after you submit.',
  },
  {
    id: 'whole', target: '[data-tour="whole-normal"]',
    title: 'Whole-film findings, and normal films',
    body: 'Some findings have no single spot to click, such as an enlarged heart: tick those here. If you see nothing abnormal at all, use “Call it normal”.',
  },
  {
    id: 'hints', target: '[data-tour="hints"]',
    title: 'Stuck?',
    body: 'Hints are free, three per film. And the small “i” next to any finding opens examples of what it looks like.',
    fallback: { target: '[data-tour="pick"]', title: 'Not sure what a finding looks like?', body: 'The small “i” next to any finding opens examples of what it looks like.' },
  },
  {
    id: 'submit', target: '[data-tour="submit"]',
    title: 'Submit to see the expert read',
    body: 'You then see the radiologists’ outlines in cyan, your marks in amber, and your own search: where your cursor spent time.',
  },
];

/** The steps whose control is on the page right now (with the fallback where one is given). Volumetric steps are
 *  kept only on a CT / MR case (`volumetric`), and then only when their control is on the page too. */
export function availableSteps(has: (selector: string) => boolean, steps: Step[] = STEPS, volumetric = false): Step[] {
  return steps.flatMap((st) => {
    if (st.volumetric && !volumetric) return [];
    if (has(st.target)) return [st];
    if (st.fallback && has(st.fallback.target)) return [{ ...st, ...st.fallback, fallback: undefined }];
    return [];
  });
}

export const hasTutorialFlag = (search: string): boolean => {
  try { return new URLSearchParams(search).get('tutorial') === '1'; } catch { return false; }
};

/** Should the tutorial open by itself on this case?
 *  - Under automation (navigator.webdriver) only when the page was LOADED with ?tutorial=1 (`bootFlag`): the app adds
 *    ?tutorial=1 by itself on a first session, and scripted runs on a fresh profile must not start with coach marks.
 *  - In a real browser: when it has not been finished or skipped yet, and either the URL asks (?tutorial=1) or this
 *    is the first case of the session. */
export function shouldOpenTutorial(o: { webdriver: boolean; bootFlag: boolean; urlFlag: boolean; done: boolean; firstCase: boolean }): boolean {
  if (o.webdriver) return o.bootFlag;
  if (o.done) return false;
  return o.urlFlag || o.firstCase;
}

export type TourState = { i: number; n: number };
export type TourAction = 'next' | 'back';
/** Next past the last step ends the tour (returns null). Back stops at the first. */
export function tourStep(s: TourState, a: TourAction): TourState | null {
  if (a === 'back') return { ...s, i: Math.max(0, s.i - 1) };
  return s.i + 1 >= s.n ? null : { ...s, i: s.i + 1 };
}

export type Rect = { left: number; top: number; width: number; height: number };
export type CardPlace = { left: number; top: number; side: 'right' | 'below' | 'above' | 'left' | 'inside' };

const hit = (a: Rect, b: Rect) => a.left < b.left + b.width && b.left < a.left + a.width && a.top < b.top + b.height && b.top < a.top + a.height;
const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(lo, v), Math.max(lo, hi));

/** Where the coach-mark card goes: beside its target, inside the viewport, and off `avoid` (the film) whenever some
 *  side allows it — so the tour never sits on the film while the learner is looking at it. */
export function placeCard(target: Rect, card: { w: number; h: number }, vp: { w: number; h: number }, avoid: Rect | null, gap = 12, margin = 8): CardPlace {
  const x = (v: number) => clamp(v, margin, vp.w - card.w - margin);
  const y = (v: number) => clamp(v, margin, vp.h - card.h - margin);
  const cands: CardPlace[] = [
    { side: 'right', left: target.left + target.width + gap, top: y(target.top) },
    { side: 'below', left: x(target.left), top: target.top + target.height + gap },
    { side: 'above', left: x(target.left), top: target.top - gap - card.h },
    { side: 'left', left: target.left - gap - card.w, top: y(target.top) },
  ];
  const rect = (c: CardPlace): Rect => ({ left: c.left, top: c.top, width: card.w, height: card.h });
  const inView = (c: CardPlace) => c.left >= margin && c.top >= margin && c.left + card.w <= vp.w - margin && c.top + card.h <= vp.h - margin;
  const free = cands.filter((c) => inView(c) && !hit(rect(c), target));
  const best = free.find((c) => !avoid || !hit(rect(c), avoid)) ?? free[0];
  if (best) return best;
  // Nothing fits beside it (the target fills the view): sit inside, along its bottom edge.
  return { side: 'inside', left: x(target.left + (target.width - card.w) / 2), top: y(target.top + target.height - card.h - gap) };
}
