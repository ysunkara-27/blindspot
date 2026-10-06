import { useEffect } from 'react';

/** Sets the tab title: "Reading log · Blindspot". Pass null for the bare product title. */
export function useTitle(title: string | null) {
  useEffect(() => {
    document.title = title ? `${title} · Blindspot` : 'Blindspot · chest X-ray perception trainer';
  }, [title]);
}
