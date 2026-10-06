# PROGRESS — Blindspot build log (newest first)

Format for entries:
`YYYY-MM-DD HH:MM — <agent> — <milestone> — <status: started|green|BLOCKED|note>`
then 1–5 lines: what changed, how verified (command + result), next step.

Special entries:
- `CONTRACT CHANGE REQUEST: <what / why>` — orchestrator decides.
- `BLOCKED: <problem> — options: …` — take the SPEC §19 fallback and continue.
- `DECISION: <ambiguity> → <choice>` — when the spec was silent.

---

2026-10-05 21:47 — orchestrator — M0 — green
- Added shared/schemas (10 files), shared/contracts.py (Pydantic mirrors + GROUND_TRUTH_KEYS), shared/tests/test_contracts.py (24 tests), Makefile, backend scaffold (settings.py, main.py w/ /api/health + router autoload), frontend Vite+React+TS shell (router, API client, tokens.css, coords.ts + vitest, generated types via `npm run gen:types`: 33 types), tests/e2e/playwright.config.ts + smoke spec.
- Verified: `uv run pytest -q` → 24 passed; `ruff check` clean; `tsc --noEmit` clean; vitest 3 passed; `npm run build` ok; `curl /api/health` → {"ok":true,"offline":true,"cases":0}.
- DECISION: project pinned to Python 3.12 (system 3.14 has no torch wheels). DECISION: API ids for findings/marks are short (`F1`/`M1`); `source: synthetic` + `syn_` ids allowed for fixtures.
- Next: launch W1 (data-engineer M1, backend M3 engines, frontend M4 viewer, tutor M5).

