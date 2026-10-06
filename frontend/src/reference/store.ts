// Which finding type the reference drawer shows (null = closed). A tiny store so any "i" on any page can open it.
import { create } from 'zustand';

type Store = { label: string | null; open: (label: string) => void; close: () => void };

export const useReference = create<Store>()((set) => ({
  label: null,
  open: (label) => set({ label }),
  close: () => set({ label: null }),
}));

/** Open the "What does this look like?" drawer for a finding type (label id, e.g. "nodule"). Mount <ReferenceDrawer/> once on the page. */
export const openReference = (label: string) => useReference.getState().open(label);
export const closeReference = () => useReference.getState().close();
