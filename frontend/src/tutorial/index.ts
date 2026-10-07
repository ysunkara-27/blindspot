// Public surface of the first-run tutorial (round 3).
export { Tutorial } from './Tutorial';
export { STEPS, SEARCH_TIP_STEPS, SEARCH_TIP_KEY, TUTORIAL_KEY, hasTutorialFlag, markSearchTipDone, markTutorialDone, searchTipDone, shouldOpenSearchTip, shouldOpenTutorial, tutorialDone } from './steps';

/** True when the page itself was loaded with ?tutorial=1 (captured once, at startup, before any in-app navigation). */
export const BOOT_TUTORIAL_FLAG: boolean = (() => {
  try { return new URLSearchParams(window.location.search).get('tutorial') === '1'; } catch { return false; }
})();
