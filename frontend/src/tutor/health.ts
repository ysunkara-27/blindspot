// Shared health and access queries. Health is polled every 60 s while any page shows it (ServerLine, TutorNotice);
// DebriefPanel invalidates it after a debrief ends in a tutor problem.
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

export const HEALTH_POLL_MS = 60_000;

export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: api.health, retry: false, refetchInterval: HEALTH_POLL_MS, refetchOnWindowFocus: true });
}

/** Is this browser a reviewer (review code configured and its cookie accepted)? False in mock mode and on error. */
export function useIsReviewer(): boolean {
  const q = useQuery({
    queryKey: ['access-status'],
    queryFn: api.access,
    retry: false,
    staleTime: 5 * 60_000,
    select: (a) => !!a.review_required && !!a.review_granted,
  });
  return q.data === true;
}
