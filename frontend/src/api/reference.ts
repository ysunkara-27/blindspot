// GET /api/reference (round 3): generic teaching material for the reference drawer — definitions, key signs and
// example films from a separate reference set. It is never about the case being read, so it may load before submit.
// The payload is guarded in src/reference/guard.ts; in mock mode it comes from the synthetic mock layer.
import { request } from './client';
import { guardReference, type Reference } from '../reference/guard';

export type { Reference, ReferenceExample, ReferenceFilm, ReferenceLabel } from '../reference/guard';

export const fetchReference = async (): Promise<Reference> => guardReference(await request<unknown>('/reference'));
