import { useSyncExternalStore } from 'react';

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(query);
      mq.addEventListener('change', cb);
      return () => mq.removeEventListener('change', cb);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/** Below 900 px the film is too small to read; the app shows a note instead of the viewer (SPEC §14.2 targets). */
export const NARROW_QUERY = '(max-width: 899.98px)';
export const useNarrow = () => useMediaQuery(NARROW_QUERY);
