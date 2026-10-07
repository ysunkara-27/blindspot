// GET /api/reference (round 3): generic teaching material for the reference drawer — definitions, key signs and
// example films from a separate reference set. It is never about the case being read, so it may load before submit.
// The payload is guarded in src/reference/guard.ts; in mock mode it comes from the synthetic mock layer.
import { request } from './client';
import { guardReference, guardReferenceLabel, type Reference, type ReferenceLabel } from '../reference/guard';

export type { Reference, ReferenceExample, ReferenceFilm, ReferenceLabel } from '../reference/guard';

export const fetchReference = async (): Promise<Reference> => guardReference(await request<unknown>('/reference'));

/** GET /api/reference/{label} (round 5): one finding type's card, its example films and its sign schematic ids. The
 *  debrief rows use it (two example films per finding) instead of the whole library. 404 → null. */
export const fetchReferenceLabel = async (label: string): Promise<ReferenceLabel | null> =>
  guardReferenceLabel(await request<unknown>(`/reference/${encodeURIComponent(label)}`));
