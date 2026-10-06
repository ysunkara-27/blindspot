// Tutor status (GET /api/health → tutor.mode) and the per-debrief error codes, turned into plain sentences. Pure
// functions; the hook and banner live in TutorNotice.tsx. Raw codes never reach the screen.
import type { DebriefResponse, Health } from '../types/contracts';

export type TutorMode = NonNullable<Health['tutor']>['mode'];
export type TutorStatus = NonNullable<Health['tutor']>;

const CONTINUES = 'Built-in explanations continue.';

/** The mode, with a fallback for servers that only say `offline`. */
export function tutorStatus(h: Health | null | undefined): TutorStatus | null {
  if (!h) return null;
  if (h.tutor) return h.tutor;
  return { mode: h.offline ? 'offline' : 'live' };
}

/** "3:45 PM" today, "Tue 3:45 PM" on another day; null when the time is missing or unreadable. */
export function resumeText(iso: string | null | undefined, now: Date = new Date()): string | null {
  if (!iso) return null;
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return null;
  const sameDay = t.toDateString() === now.toDateString();
  const time = t.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  return sameDay ? time : `${t.toLocaleDateString([], { weekday: 'short' })} ${time}`;
}

/** The banner sentence for a mode other than live; null when the tutor is live. */
export function bannerText(t: TutorStatus | null, now: Date = new Date()): string | null {
  if (!t) return null;
  switch (t.mode) {
    case 'live': return null;
    case 'offline': return 'The AI tutor is off. You still get the built-in explanation after every film.';
    case 'paused_credits': return `The AI tutor is paused (account credits ran out). ${CONTINUES}`;
    case 'paused_budget': {
      const back = resumeText(t.resume_at, now);
      return `The AI tutor has reached its spending limit for now. ${CONTINUES}${back ? ` Back around ${back}.` : ''}`;
    }
    case 'paused_rate': return 'The AI tutor is busy; trying again shortly.';
    case 'paused_error': return `The AI tutor is unavailable right now. ${CONTINUES}`;
    default: return `The AI tutor is unavailable right now. ${CONTINUES}`;
  }
}

/** "Spend today $1.23" for reviewers; null when the server did not say. */
export function spendText(t: TutorStatus | null): string | null {
  const day = t?.spend_usd?.day;
  if (typeof day !== 'number' || !Number.isFinite(day)) return null;
  return `Spend today $${day.toFixed(2)}`;
}

const SHOWING = 'Showing the built-in explanation instead.';
const DEBRIEF_ERRORS: Record<string, string> = {
  offline: `The AI tutor is off. ${SHOWING}`,
  credits_depleted: `The AI tutor is paused (account credits ran out). ${SHOWING}`,
  rate_limited: `The AI tutor is busy. ${SHOWING}`,
  budget_exceeded: `The AI tutor has reached its spending limit for now. ${SHOWING}`,
  unavailable: `The AI tutor is unavailable right now. ${SHOWING}`,
  auth: `The AI tutor could not sign in to its service. ${SHOWING}`,
  validator_failed: `The AI tutor's draft did not pass our checks. ${SHOWING}`,
  timeout: `The AI tutor took too long. ${SHOWING}`,
  internal_error: `Something went wrong while writing the AI debrief. ${SHOWING}`,
};
const DEBRIEF_FAILED = 'The AI tutor is unavailable right now. The facts above are complete.';

/**
 * The one line above a debrief that did not come from the live tutor. `failed` = the request itself failed or the
 * server said status "failed" (then there may be no explanation to show at all). Unknown codes get the generic line.
 */
export function debriefErrorText(d: Pick<DebriefResponse, 'status' | 'error' | 'debrief'> | null | undefined, failed: boolean): string | null {
  const code = (d?.error ?? '').trim().toLowerCase();
  if (code && DEBRIEF_ERRORS[code]) return d?.debrief || !failed ? DEBRIEF_ERRORS[code] : DEBRIEF_ERRORS[code].replace(SHOWING, 'The facts above are complete.');
  if (code || failed) return d?.debrief ? DEBRIEF_ERRORS.unavailable : DEBRIEF_FAILED;
  return null;
}

/** Did this debrief resolve with a tutor problem worth re-checking the tutor status for? */
export const debriefHadError = (d: Pick<DebriefResponse, 'status' | 'error'> | null | undefined, failed: boolean): boolean =>
  failed || !!d?.error || d?.status === 'failed';
