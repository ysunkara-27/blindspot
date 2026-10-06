// Keyboard and mouse help: opens with "?" and with the "Keys" button.
// While open it owns the keyboard (capture phase), so reading-room shortcuts cannot fire behind it.
import { useEffect, useLayoutEffect, useRef } from 'react';
import { markKeysSeen, SHORTCUTS } from './keys';
import s from './KeysHelp.module.css';

export function KeysHelp({ onClose }: { onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const close = useRef(onClose);
  useLayoutEffect(() => { close.current = onClose; });
  useEffect(() => {
    markKeysSeen();
    const prev = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' || e.key === '?' || e.key === 'Enter') {
        e.preventDefault();
        close.current();
      }
      if (e.key !== 'Tab') e.stopPropagation();
    };
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      prev?.focus?.();
    };
  }, []);
  return (
    <div className={s.backdrop} onPointerDown={(e) => { if (e.target === e.currentTarget) onClose(); }} data-testid="keys-help">
      <div className={s.sheet} role="dialog" aria-modal="true" aria-labelledby="keys-h">
        <div className={s.head}>
          <h2 id="keys-h" className={s.title}>Keys and mouse</h2>
          <button ref={closeRef} type="button" className={s.close} onClick={onClose} data-testid="keys-close">Close</button>
        </div>
        <p className={s.lede}>
          Pick what you see and click where it is, tick whole-film findings, or call the film normal; then submit.{' '}
          <span className={s.cyan}>Cyan</span> is the expert outline; <span className={s.amber}>amber</span> is you.
        </p>
        <table className={s.table}>
          <tbody>
            {SHORTCUTS.map(([k, what, isKey]) => (
              <tr key={k}>
                <th scope="row">{isKey ? <kbd className={s.kbd}>{k}</kbd> : k}</th>
                <td>{what}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
