// Access gating (private preview). The server sets an httpOnly cookie on success; nothing is stored client-side.
// Any API call that answers 401 {"error":"access_code_required"} raises the app-wide gate; reviewer-only routes
// (/review, /cohort) answer 401/403 with a reviewer error and get their own prompt on the page.
import { create } from 'zustand';

export type GateKind = 'access' | 'reviewer';

type GateStore = { need: GateKind | null; raise: (k: GateKind) => void; clear: () => void };

export const useGate = create<GateStore>()((set) => ({
  need: null,
  raise: (k) => set((st) => (st.need === 'access' ? st : { need: k })),
  clear: () => set({ need: null }),
}));

/** Reads the gate kind from an error body: {"error": "..."} or FastAPI's {"detail": "..." | {"error": "..."}}. */
export function gateKindFromBody(status: number, body: unknown): GateKind | null {
  if (status !== 401 && status !== 403) return null;
  const o = (typeof body === 'object' && body !== null ? body : {}) as Record<string, unknown>;
  const detail = o.detail;
  const raw = [o.error, typeof detail === 'string' ? detail : (detail as Record<string, unknown> | undefined)?.error]
    .filter((v): v is string => typeof v === 'string')
    .join(' ')
    .toLowerCase();
  if (raw.includes('review')) return 'reviewer'; // review_code_required
  if (raw.includes('access_code') || raw.includes('access code')) return 'access';
  return null;
}
