// Which finding type the reference drawer shows (null = closed). A tiny store so any "i" on any page can open it.
// Round 5: a debrief row may pass the schematic ids of the signs drawn on the film, listed first in "Signs to know".
import { create } from 'zustand';

export type OpenOptions = { signIds?: string[] };
type Store = { label: string | null; signIds: string[]; open: (label: string, opts?: OpenOptions) => void; close: () => void };

export const useReference = create<Store>()((set) => ({
  label: null,
  signIds: [],
  open: (label, opts) => set({ label, signIds: opts?.signIds ?? [] }),
  close: () => set({ label: null, signIds: [] }),
}));

/** Open the "What does this look like?" drawer for a finding type (label id, e.g. "nodule"). Mount <ReferenceDrawer/> once on the page. */
export const openReference = (label: string, opts?: OpenOptions) => useReference.getState().open(label, opts);
export const closeReference = () => useReference.getState().close();
