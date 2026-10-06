// Thin typed fetch wrapper. All API types come from the generated contracts (shared/schemas).
// Mock mode (synthetic cases, in-browser): VITE_MOCK=1, ?mock=1 (sticky per tab), or the API is unreachable / has no cases.
import type {
  AskRequest, AskResponse, AssessmentRecorded, AssessmentSummary, AttemptSubmit, DebriefResponse, Health,
  Case, HintRequest, HintResponse, NextCase, ReviewRating, SessionCreate, SessionCreated, SubmitResult, SusResult, SusSubmit,
} from '../types/contracts';

import { apiRoot, normalizeBase, resolveUrl } from './base';
import { gateKindFromBody, useGate, type GateKind } from './access';

/** Public path of the app ("/" or e.g. "/blindspot/"), from Vite's `base` (VITE_BASE_PATH). */
export const BASE = normalizeBase(import.meta.env.BASE_URL);
/** API root, no trailing slash: VITE_API_BASE if set, else `${BASE}api`. */
export const API_BASE = apiRoot(BASE, import.meta.env.VITE_API_BASE as string | undefined);
/** Re-roots a server-provided URL ("/api/cases/x/image", "/mock/x.png") for this deployment. */
export const assetUrl = (u: string) => resolveUrl(u, BASE, API_BASE);
// Cookies (the access-code session) must travel with cross-origin API calls when VITE_API_BASE points elsewhere.
const CREDENTIALS: RequestCredentials = /^https?:/i.test(API_BASE) ? 'include' : 'same-origin';

export type ApiMode = 'real' | 'mock';
let mode: ApiMode = import.meta.env.VITE_MOCK === '1' ? 'mock' : 'real';
let modeReason = import.meta.env.VITE_MOCK === '1' ? 'VITE_MOCK=1' : '';

export class ApiError extends Error {
  status: number;
  /** Set when the server asks for an access or reviewer code. */
  gate: GateKind | null;
  constructor(status: number, message: string, gate: GateKind | null = null) {
    super(message);
    this.status = status;
    this.gate = gate;
  }
}

export const isGateError = (e: unknown, kind?: GateKind): e is ApiError =>
  e instanceof ApiError && !!e.gate && (!kind || e.gate === kind);

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
    const res = await fetch(`${API_BASE}/health`, { signal: ctrl.signal, credentials: CREDENTIALS });
    clearTimeout(timer);
    // A private preview may gate even /health: the API is there, it just wants the access code first.
    if (res.status === 401 || res.status === 403) {
      const gate = gateKindFromBody(res.status, await res.json().catch(() => null));
      if (gate === 'access') { useGate.getState().raise('access'); return mode; }
    }
    const h = res.ok ? ((await res.json()) as Health) : null;
    if (!h?.ok) { mode = 'mock'; modeReason = 'API unreachable'; }
    else if (!h.cases) { mode = 'mock'; modeReason = 'API has no cases loaded'; }
    else await probeAccess();
  } catch {
    mode = 'mock';
    modeReason = 'API unreachable';
  }
  return mode;
}

/** Private preview: GET /access says whether a code is configured and passed; show the gate before any page asks. */
async function probeAccess(): Promise<void> {
  try {
    const res = await fetch(`${API_BASE}/access`, { credentials: CREDENTIALS });
    if (!res.ok) return; // older servers: the first gated call raises the gate instead
    const st = (await res.json()) as { access_required?: boolean; access_granted?: boolean };
    if (st.access_required && !st.access_granted) useGate.getState().raise('access');
  } catch {
    /* best effort */
  }
}

/** Exported for endpoints that live outside this file (src/api/sessionOptions.ts); prefer the typed `api` below. */
export async function request<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
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
    credentials: CREDENTIALS,
    headers: { 'Content-Type': 'application/json' },
    body: init?.body === undefined ? undefined : JSON.stringify(init.body),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let body: unknown = null;
    try { body = JSON.parse(text); } catch { /* not JSON */ }
    const gate = gateKindFromBody(res.status, body);
    // The app-wide gate covers every page; reviewer prompts are shown by the page that asked.
    if (gate === 'access') useGate.getState().raise('access');
    throw new ApiError(res.status, `${res.status} ${res.statusText}: ${text}`, gate);
  }
  return (await res.json()) as T;
}

const post = <T,>(path: string, body: unknown) => request<T>(path, { method: 'POST', body });

export function isSubmitResult(r: SubmitResult | AssessmentRecorded): r is SubmitResult {
  return (r as AssessmentRecorded).recorded !== true;
}

/** POST the access or reviewer code. The server sets the cookie; resolves false on a wrong code. */
export async function submitCode(kind: GateKind, code: string): Promise<{ ok: boolean; status: number }> {
  const res = await fetch(`${API_BASE}${kind === 'access' ? '/access' : '/review/access'}`, {
    method: 'POST',
    credentials: CREDENTIALS,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });
  return { ok: res.ok, status: res.status };
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
  /** Zone outlines for "Show anatomy" (after submit only). Loosely typed; guarded in src/viewer/anatomy.ts. */
  anatomy: (aid: string) => request<unknown>(`/attempts/${aid}/anatomy`),
  devOverlayUrl: (caseId: string, layers: string) => `${API_BASE}/dev/cases/${caseId}/overlay?layers=${layers}`,
};
