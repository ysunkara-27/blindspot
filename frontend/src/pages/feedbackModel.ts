// /feedback — the form's pure parts: what the learner picked, the check before sending, the payload the worker
// expects (POST {base}/feedback/submit, JSON ≤ 4 KB), and the message for each way a send can fail. The page
// (FeedbackPage.tsx) only renders and fetches; this file is what the unit tests cover.
import { DEFAULT_URL } from '../analytics';

export const ROLES = ['radiologist', 'resident', 'medical_student', 'other_clinician', 'other'] as const;
export type Role = (typeof ROLES)[number];
export const YEARS = ['<5', '5-15', '>15'] as const;
export type Years = (typeof YEARS)[number];
export const VERDICTS = ['yes', 'maybe', 'no'] as const;
export type Verdict = (typeof VERDICTS)[number];
export const RATINGS = ['ease', 'teaching', 'accuracy', 'recommend'] as const;
export type RatingKey = (typeof RATINGS)[number];
export type Rating = 1 | 2 | 3 | 4 | 5;

export const MAX_MISSING = 600;
export const MAX_CONTACT = 200;

export const ROLE_LABELS: Record<Role, string> = {
  radiologist: 'Radiologist', resident: 'Resident', medical_student: 'Medical student', other_clinician: 'Other clinician', other: 'Other',
};
export const YEARS_LABELS: Record<Years, string> = { '<5': 'Under 5', '5-15': '5 to 15', '>15': 'Over 15' };
export const VERDICT_LABELS: Record<Verdict, string> = { yes: 'Yes', maybe: 'Maybe', no: 'No' };

/** The four ratings in order, each with its question and the two end captions (1 … 5). */
export const RATING_QUESTIONS: { key: RatingKey; question: string; low: string; high: string }[] = [
  { key: 'ease', question: 'How easy was it to use?', low: 'hard', high: 'easy' },
  { key: 'teaching', question: 'How useful would it be for teaching?', low: 'not useful', high: 'very' },
  { key: 'accuracy', question: 'How accurate were the outlines and explanations?', low: 'often wrong', high: 'reliable' },
  { key: 'recommend', question: 'Would you recommend it to trainees?', low: 'no', high: 'definitely' },
];

/** What the form holds while it is being filled. Nothing is preselected. */
export type FeedbackForm = {
  role: Role | null;
  years: Years | null;
  ratings: Partial<Record<RatingKey, Rating>>;
  verdict: Verdict | null;
  missing: string;
  contact: string;
};

export const EMPTY_FORM: FeedbackForm = { role: null, years: null, ratings: {}, verdict: null, missing: '', contact: '' };

/** The worker's row: role, years ('' when not given), four integer ratings, the verdict and two trimmed texts. */
export type FeedbackPayload = {
  role: Role; years: Years | ''; ease: Rating; teaching: Rating; accuracy: Rating; recommend: Rating;
  real_product: Verdict; missing: string; contact: string;
};

export const RATINGS_MESSAGE = 'Rate all four questions first.';
export const VERDICT_MESSAGE = 'Say whether this could become a real tool.';
export const LIMIT_MESSAGE = "You've sent a few already — try again in an hour.";
export const OFFLINE_MESSAGE = 'No connection. Check your network and try again.';
export const FAILED_MESSAGE = 'Could not send feedback. Please try again.';

/** The first thing still missing, or null when the form can be sent. Only the ratings and the verdict are required. */
export function missingAnswer(f: FeedbackForm): { message: string; field: RatingKey | 'verdict' } | null {
  for (const r of RATINGS) if (f.ratings[r] == null) return { message: RATINGS_MESSAGE, field: r };
  if (!f.verdict) return { message: VERDICT_MESSAGE, field: 'verdict' };
  return null;
}

/** The JSON body, or null while something required is missing. A reader who gave no role is sent as "other" (the
 *  worker needs one), no years becomes '', and the free text is trimmed and cut to the worker's limits. */
export function toPayload(f: FeedbackForm): FeedbackPayload | null {
  if (missingAnswer(f)) return null;
  return {
    role: f.role ?? 'other',
    years: f.years ?? '',
    ease: f.ratings.ease!, teaching: f.ratings.teaching!, accuracy: f.ratings.accuracy!, recommend: f.ratings.recommend!,
    real_product: f.verdict!,
    missing: f.missing.trim().slice(0, MAX_MISSING),
    contact: f.contact.trim().slice(0, MAX_CONTACT),
  };
}

/** Where to POST: the tracker's base (VITE_ANALYTICS_URL) plus /feedback/submit. An empty or unset variable keeps
 *  analytics off but still lets feedback through to the default worker: sending it is the learner's own choice. */
export function feedbackEndpoint(raw: string | undefined | null): string {
  const base = (raw ?? '').trim().replace(/\/+$/, '') || DEFAULT_URL;
  return `${base}/feedback/submit`;
}

/** The line under the button after a failed send. 429 is the hourly limit; other replies show the worker's own
 *  words when it sent any, else a plain failure line; a fetch that never reached the worker is "no connection". */
export function failureMessage(status: number | null, body: unknown): string {
  if (status === null) return OFFLINE_MESSAGE;
  if (status === 429) return LIMIT_MESSAGE;
  const err = typeof body === 'object' && body !== null && 'error' in body ? (body as { error?: unknown }).error : undefined;
  return typeof err === 'string' && err.trim() ? err.trim() : FAILED_MESSAGE;
}
