import { useEffect } from 'react';

/** Sets the tab title: "Reading log · Blindspot". Pass null for the bare product title.
 *  With `restore`, the previous title comes back on unmount (for overlays such as the small-screen note). */
export function useTitle(title: string | null, restore = false) {
  useEffect(() => {
    const prev = document.title;
    document.title = title ? `${title} · Blindspot` : 'Blindspot · chest X-ray perception trainer';
    return restore ? () => { document.title = prev; } : undefined;
  }, [title, restore]);
}
