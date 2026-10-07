// True once the element has been on screen (round 5: debrief rows fetch their example films only when scrolled to).
// Without IntersectionObserver (old browsers, server rendering) it is true at once.
import { useEffect, useState, type RefObject } from 'react';

export function useInView(ref: RefObject<Element | null>, margin = '120px'): boolean {
  const [seen, setSeen] = useState(() => typeof IntersectionObserver === 'undefined');
  useEffect(() => {
    if (seen) return;
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') { setSeen(true); return; }
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { setSeen(true); io.disconnect(); }
    }, { rootMargin: margin });
    io.observe(el);
    return () => io.disconnect();
  }, [ref, seen, margin]);
  return seen;
}
