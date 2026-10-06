// "What is this?" for the amber search trace: why where you look matters, and what the trace is (and is not).
// A small modal on report paper; it owns the keyboard while open, like the key list.
import { useEffect, useLayoutEffect, useRef } from 'react';
import s from '../read/KeysHelp.module.css';

export const SEARCH_LEGEND = 'Where your cursor spent time — a stand-in for where you looked';

export function SearchExplainer({ onClose }: { onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const close = useRef(onClose);
  useLayoutEffect(() => { close.current = onClose; });
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' || e.key === 'Enter') { e.preventDefault(); close.current(); }
      if (e.key !== 'Tab') e.stopPropagation();
    };
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      prev?.focus?.();
    };
  }, []);
  return (
    <div className={s.backdrop} onPointerDown={(e) => { if (e.target === e.currentTarget) onClose(); }} data-testid="search-explainer">
      <div className={s.sheet} role="dialog" aria-modal="true" aria-labelledby="search-explainer-h">
        <div className={s.head}>
          <h2 id="search-explainer-h" className={s.title}>Your search, in amber</h2>
          <button ref={closeRef} type="button" className={s.close} onClick={onClose} data-testid="search-explainer-close">Close</button>
        </div>
        <p className={s.prose}>
          People miss what they never look at, and sometimes what they look straight past. In a classic study,
          radiologists searching chest CT scans for nodules were shown a scan with a gorilla drawn into it, and most of
          them did not notice it (Drew, Võ &amp; Wolfe, 2013).
        </p>
        <p className={s.prose}>
          Researchers study this with eye tracking. Blindspot has no eye tracker, so it uses your cursor, the magnifier
          and your zoom as a rough stand-in: the brighter the <span className={s.amber}>amber</span>, the longer your
          cursor stayed there. A thin dashed ring marks a review area (a place findings like to hide) that your cursor
          did not visit.
        </p>
        <p className={s.prose}>
          <strong>It is a proxy, not a measurement.</strong> You can look at a spot without moving the cursor to it, so
          read “not visited” as a prompt to check that area next time, not as proof that you did not look.
        </p>
      </div>
    </div>
  );
}
