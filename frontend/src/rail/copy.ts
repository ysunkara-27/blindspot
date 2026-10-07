// Rail copy built from computed facts (never from the image): time in words, one-line reasons, the score sentence.
// Mirrors backend/app/facts_card.py: "no time spent there" below 100 ms, never "dwell 0 ms".
import { labelDisplay, zoneDisplay } from '../api/labels';
import type { Outcome, OutcomeResult, SubmitResult } from '../types/contracts';

export const PROXY_NOTE = 'Based on your cursor, magnifier and zoom — a proxy for where you looked, not a measurement.';
const NO_TIME_MS = 100;

/** How long the cursor stayed on a finding, in words. */
export function dwellText(ms: number | null | undefined): string {
  const v = typeof ms === 'number' && Number.isFinite(ms) ? ms : 0;
  if (v < NO_TIME_MS) return 'no time spent there';
  const secs = v / 1000;
  if (secs < 9.95) return `about ${(Math.floor(secs * 10 + 0.5) / 10).toFixed(1)} s there`;
  return `about ${Math.floor(secs + 0.5)} s there`;
}

/** Server text written before round 3 may still say "dwell 0 ms" or "loupe": say it the way the UI does. */
export function plainText(text: string): string {
  return text
    .replace(/\bdwell(?: time)?(?: of)? (\d+(?:\.\d+)?) ?ms\b/gi, (_, n: string) => dwellText(Number(n)))
    .replace(/\bdwell(?: time)?(?: of)? (\d+(?:\.\d+)?) ?s\b/gi, (_, n: string) => dwellText(Number(n) * 1000))
    .replace(/\bloupe\b/g, 'magnifier')
    .replace(/\bLoupe\b/g, 'Magnifier');
}

const cap = (t: string) => (t ? t.charAt(0).toUpperCase() + t.slice(1) : t);

/** One line of "why" for an outcome, from the outcome alone. */
export function whyLine(result: OutcomeResult, o?: Pick<Outcome, 'dwell_ms' | 'learner_label' | 'matched'> | null): string {
  switch (result) {
    case 'found':
    case 'true_positive':
      return 'You marked it and named it.';
    case 'pattern_found':
      return 'You ticked it.';
    case 'mislabeled':
      return o?.learner_label === 'not_sure' ? 'Right place; you were not sure what it was.'
        : o?.learner_label ? `Right place; you called it ${labelDisplay(o.learner_label).toLowerCase()}.` : 'Right place, different name.';
    case 'missed_search':
      return `${cap(dwellText(o?.dwell_ms))}.`;
    case 'missed_recognition':
      return `Your cursor passed through: ${dwellText(o?.dwell_ms)}.`;
    case 'missed_decision':
      return `You stayed ${dwellText(o?.dwell_ms).replace(/ there$/, '')} there and left it unmarked.`;
    case 'pattern_missed':
      return 'Not ticked.';
    case 'false_positive':
      return o?.learner_label && o.learner_label !== 'not_sure'
        ? `Radiologists marked nothing here; you called it ${labelDisplay(o.learner_label).toLowerCase()}.`
        : 'Radiologists marked nothing here.';
    case 'pattern_false':
      return 'Ticked, but radiologists did not report it.';
    case 'duplicate':
      return o?.matched ? `A second mark on ${o.matched}.` : 'A second mark on a finding you had already marked.';
    case 'true_negative':
      return 'No findings, and you called it normal.';
    case 'unmatched':
      return 'The reference does not label this spot; it is neither counted for nor against you.';
  }
}

/** The "i" next to the score, in one sentence. Hints do not change it. */
export function scoreSentence(isNormal: boolean | undefined): string {
  return isNormal
    ? 'Out of 100: a normal film starts at 100 and loses points for each mark or whole-film finding you called.'
    : 'Out of 100: 70 for marking each finding in the right place, 20 for naming it, 10 for whole-film findings, minus points for each extra mark.';
}

/** Search summary lines from the computed search facts. Volumes add the slices line and say "scan", not "lungs". */
export function searchLines(search: SubmitResult['reveal']['search'], volumetric = false): { coverage: string; areas: string } {
  const pct = Math.max(0, Math.min(100, Math.round(search.lung_coverage_pct)));
  const un = search.unvisited_review_areas.map(zoneDisplay);
  const out: { coverage: string; areas: string } = {
    coverage: volumetric ? `Your cursor covered about ${pct}% of the scan.` : `Your cursor covered about ${pct}% of the lungs.`,
    areas: un.length ? `Review areas you did not visit: ${un.join(', ')}.` : 'You visited every review area.',
  };
  if (volumetric) {
    // Review areas are an X-ray idea; on a scan the second line is about slices.
    const sp = search.slices_viewed_pct;
    const seen = search.finding_slices_viewed ?? {};
    const missed = Object.entries(seen).filter(([, v]) => !v).map(([k]) => k);
    const parts: string[] = [];
    if (typeof sp === 'number' && Number.isFinite(sp)) parts.push(`You scrolled through about ${Math.max(0, Math.min(100, Math.round(sp)))}% of the slices.`);
    if (Object.keys(seen).length) parts.push(missed.length ? `The slices holding ${missed.join(', ')} were never on screen long enough to see.` : 'Every finding\'s slices were on screen.');
    out.areas = parts.join(' ') || (un.length ? out.areas : 'No slice times were recorded.');
  }
  return out;
}
