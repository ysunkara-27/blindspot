// Session + display preferences. Session persists in sessionStorage (per tab), so a reload keeps your place.
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';
import type { Level, Modality, Mode } from '../types/contracts';

export type SessionInfo = {
  sessionId: string;
  learnerId: string;
  displayName: string;
  level: Level;
  mode: Mode;
  drillLabel?: string;
  /** The scan type the set was started with (volumetric round); absent = Chest X-ray. */
  modality?: Modality;
};

type Store = {
  session: SessionInfo | null;
  projector: boolean;
  setSession: (s: SessionInfo | null) => void;
  setProjector: (on: boolean) => void;
};

function applyProjector(on: boolean) {
  if (on) document.documentElement.dataset.projector = '1';
  else delete document.documentElement.dataset.projector;
}

export const useSession = create<Store>()(
  persist(
    (set) => ({
      session: null,
      projector: false,
      setSession: (session) => set({ session }),
      setProjector: (projector) => {
        applyProjector(projector);
        set({ projector });
      },
    }),
    {
      name: 'blindspot.session',
      storage: createJSONStorage(() => sessionStorage),
      onRehydrateStorage: () => (state) => {
        // ?projector=1 wins over the stored value.
        const q = new URLSearchParams(location.search).get('projector');
        const on = q === '1' ? true : q === '0' ? false : (state?.projector ?? false);
        if (state) state.projector = on;
        applyProjector(on);
      },
    },
  ),
);

export const isAssessment = (mode: Mode | undefined) => mode === 'assess_A' || mode === 'assess_B';
