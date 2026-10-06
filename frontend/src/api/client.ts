// Thin typed fetch wrapper. All API types come from the generated contracts (shared/schemas).
// Mock mode (synthetic cases, in-browser): VITE_MOCK=1, ?mock=1 (sticky per tab), or the API is unreachable / has no cases.
import type {
  AskRequest, AskResponse, AssessmentRecorded, AssessmentSummary, AttemptSubmit, DebriefResponse, Health,
  Case, HintRequest, HintResponse, NextCase, ReviewRating, SessionCreate, SessionCreated, SubmitResult, SusResult, SusSubmit,
} from '../types/contracts';

export const API_BASE = '/api';

export type ApiMode = 'real' | 'mock';
let mode: ApiMode = import.meta.env.VITE_MOCK === '1' ? 'mock' : 'real';
let modeReason = import.meta.env.VITE_MOCK === '1' ? 'VITE_MOCK=1' : '';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function apiMode(): { mode: ApiMode; reason: string } {
  return { mode, reason: modeReason };
}

const MOCK_KEY = 'blindspot.mock';

/** Decide real vs mock once at startup. Never throws. */
export async function initApiMode(): Promise<ApiMode> {
  if (import.meta.env.VITE_MOCK === '1') return mode;
  try {
    const q = new URLSearchParams(location.search).get('mock');
    if (q === '1') sessionStorage.setItem(MOCK_KEY, '1');
    if (q === '0') sessionStorage.removeItem(MOCK_KEY);
    if (sessionStorage.getItem(MOCK_KEY) === '1') {
      mode = 'mock';
      modeReason = '?mock=1';
      return mode;
    }
  } catch {
    /* storage blocked: fall through to the health probe */
  }
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 1500);
    const res = await fetch(`${API_BASE}/health`, { signal: ctrl.signal });
    clearTimeout(timer);
    const h = res.ok ? ((await res.json()) as Health) : null;
    if (!h?.ok) { mode = 'mock'; modeReason = 'API unreachable'; }
    else if (!h.cases) { mode = 'mock'; modeReason = 'API has no cases loaded'; }
  } catch {
    mode = 'mock';
    modeReason = 'API unreachable';
  }
  return mode;
}

async function request<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const method = init?.method ?? 'GET';
  if (mode === 'mock') {
    const { mockRequest } = await import('./mock');
    try {
      return (await mockRequest(method, path, init?.body)) as T;
    } catch (e) {
      const status = (e as { status?: number }).status ?? 500;
      throw new ApiError(status, (e as Error).message);
    }
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: init?.body === undefined ? undefined : JSON.stringify(init.body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new ApiError(res.status, `${res.status} ${res.statusText}: ${text}`);
  }
  return (await res.json()) as T;
}

const post = <T,>(path: string, body: unknown) => request<T>(path, { method: 'POST', body });

export function isSubmitResult(r: SubmitResult | AssessmentRecorded): r is SubmitResult {
  return (r as AssessmentRecorded).recorded !== true;
}

export const api = {
  health: () => request<Health>('/health'),
  createSession: (body: SessionCreate) => post<SessionCreated>('/sessions', body),
  next: (sid: string) => request<NextCase>(`/sessions/${sid}/next`),
  hint: (aid: string, body: HintRequest) => post<HintResponse>(`/attempts/${aid}/hint`, body),
  submit: (aid: string, body: AttemptSubmit) => post<SubmitResult | AssessmentRecorded>(`/attempts/${aid}/submit`, body),
  debrief: (aid: string) => request<DebriefResponse>(`/attempts/${aid}/debrief`),
  ask: (aid: string, body: AskRequest) => post<AskResponse>(`/attempts/${aid}/ask`, body),
  /** Learner "This seems wrong" flag. Not yet in §13 — see CONTRACT CHANGE REQUEST in docs/PROGRESS.md. */
  flagDebrief: (aid: string, comment: string) => post<{ ok: boolean }>(`/attempts/${aid}/flag`, { comment }),
  rate: (body: ReviewRating) => post<{ ok: boolean }>('/review/ratings', body),
  summary: (sid: string) => request<AssessmentSummary>(`/sessions/${sid}/summary`),
  /** Dashboard payloads are loosely typed by the API; pages pass them through src/dashboard/types.ts guards. */
  learnerDashboard: (lid: string) => request<unknown>(`/learners/${encodeURIComponent(lid)}/dashboard`),
  cohortDashboard: (qs = '') => request<unknown>(`/cohort/dashboard${qs}`),
  /** Review queue (SPEC §11.1); shapes guarded in src/review/types.ts. */
  reviewItems: (type: 'debrief' | 'card', limit = 50) => request<unknown>(`/review/items?type=${type}&limit=${limit}`),
  reviewExportUrl: `${API_BASE}/review/export.csv`,
  sus: (body: SusSubmit) => post<SusResult>('/sus', body),
  /** Full case with ground truth. Reviewer-only (the attempt is long submitted); never used by the reading room. */
  devCase: (caseId: string) => request<Case>(`/dev/cases/${encodeURIComponent(caseId)}`),
  about: () => request<unknown>('/about'),
  imageUrl: (caseId: string) => `${API_BASE}/cases/${caseId}/image`,
  devOverlayUrl: (caseId: string, layers: string) => `${API_BASE}/dev/cases/${caseId}/overlay?layers=${layers}`,
};
