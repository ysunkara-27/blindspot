# Blindspot frontend

Vite + React 19 + TypeScript (strict). Reading room per SPEC §5 and §14.

- `npm run dev` — web on :5173, proxies `/api` to :8000.
- Mock API: `VITE_MOCK=1 npm run dev`, or open `/?mock=1` (sticky per tab; `/?mock=0` clears). The app also falls back to
  the mock when `/api/health` is unreachable or reports 0 cases. The mock serves 10 SYNTHETIC drawn-shape cases
  (`public/mock/`, regenerate with `node scripts/gen-mock.mjs`); a "Synthetic demo cases" badge shows in the header.
- `npm run gen:types` — regenerate `src/types/contracts.ts` from `shared/schemas` (never hand-edit).
- `npm run test -- --run` (vitest) · `npm run lint` (oxlint) · `npx tsc --noEmit -p tsconfig.app.json` · `npm run build`.
- e2e (from `frontend/`): `NODE_PATH=$PWD/node_modules npx playwright test --config ../tests/e2e/playwright.config.ts`
  (mock by default; `E2E_REAL=1` runs against the API). Screenshots: `tests/e2e/__screenshots__/`.

Layout: `viewer/` (coords, telemetry, heatmap, Viewer, loupe, popover, reveal), `read/` (marks reducer),
`rail/` (your read, outcomes, facts card, debrief, ask), `pages/`, `state/` (zustand session), `api/` (client, labels, mock).
