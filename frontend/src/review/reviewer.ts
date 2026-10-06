// Reviewer identity, remembered per browser (a convenience only; every rating also carries it).
import { useState } from 'react';

const KEY = 'blindspot.reviewer';
export type Reviewer = { name: string; role: string };

function load(): Reviewer {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? 'null') as Reviewer | null;
    if (v && typeof v.name === 'string' && typeof v.role === 'string') return v;
  } catch { /* storage blocked or malformed */ }
  return { name: '', role: 'Medical student' };
}

export function useReviewer(): [Reviewer, (r: Reviewer) => void] {
  const [r, setR] = useState<Reviewer>(load);
  const set = (next: Reviewer) => {
    setR(next);
    try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* ignore */ }
  };
  return [r, set];
}
