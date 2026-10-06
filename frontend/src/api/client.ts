// Thin typed fetch wrapper. All API types come from the generated contracts (shared/schemas).
import type {
  AskRequest, AskResponse, AssessmentRecorded, AssessmentSummary, AttemptSubmit, DebriefResponse, Health,
  HintRequest, HintResponse, NextCase, SessionCreate, SessionCreated, SubmitResult,
} from '../types/contracts';

export const API_BASE = '/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return (await res.json()) as T;
}

const post = <T,>(path: string, body: unknown) => request<T>(path, { method: 'POST', body: JSON.stringify(body) });

export const api = {
  health: () => request<Health>('/health'),
  createSession: (body: SessionCreate) => post<SessionCreated>('/sessions', body),
  next: (sid: string) => request<NextCase>(`/sessions/${sid}/next`),
  hint: (aid: string, body: HintRequest) => post<HintResponse>(`/attempts/${aid}/hint`, body),
  submit: (aid: string, body: AttemptSubmit) => post<SubmitResult | AssessmentRecorded>(`/attempts/${aid}/submit`, body),
  debrief: (aid: string) => request<DebriefResponse>(`/attempts/${aid}/debrief`),
  ask: (aid: string, body: AskRequest) => post<AskResponse>(`/attempts/${aid}/ask`, body),
  summary: (sid: string) => request<AssessmentSummary>(`/sessions/${sid}/summary`),
  learnerDashboard: (lid: string) => request<unknown>(`/learners/${lid}/dashboard`),
  cohortDashboard: (qs = '') => request<unknown>(`/cohort/dashboard${qs}`),
  about: () => request<unknown>('/about'),
  imageUrl: (caseId: string) => `${API_BASE}/cases/${caseId}/image`,
};
