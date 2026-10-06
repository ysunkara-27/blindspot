# PLAN — Blindspot build plan

## M0 — Contracts and scaffold (orchestrator, ~45 min)
**Files:** `shared/schemas/*.json`, `pyproject.toml`, `Makefile`, `.gitignore`, `.env.example`, `backend/app/main.py`, `backend/app/settings.py`, `frontend/` scaffold
**Checks:** `make setup` succeeds; `uv run pytest -q` runs; `make dev` serves `/api/health` and frontend shell
**Deps:** none

## M1 — Data ingest (data-engineer, ~2 h)
**Files:** `pipeline/ingest_chestxdet.py`, `pipeline/splits.py`, `pipeline/qa_contact_sheet.py`, `pipeline/tests/`
**Checks:** `cases.jsonl` validates, ≥3000 cases, ≥90% polygon masks, normals counted, splits disjoint, contact sheets written
**Deps:** M0 (schemas)

## M2 — Anatomy, zones, features (vision-ml-engineer, ~3 h + background compute)
**Files:** `pipeline/anatomy/segment.py`, `pipeline/anatomy/orientation.py`, `pipeline/anatomy/zones.py`, `pipeline/features/lesion.py`, `pipeline/features/difficulty.py`, `pipeline/features/ctr.py`
**Checks:** anatomy npz ≥95% cases, zone unit tests pass, every focal finding has side/zones/primary_zone/relative_location, overlay PNGs in qa/
**Deps:** M1 (cases.jsonl + images)

## M3 — Engines, API, DB (backend-engineer, ~4 h)
**Files:** `backend/app/scoring/`, `backend/app/search/`, `backend/app/adaptive/`, `backend/app/analytics/`, `backend/app/routes/`, `backend/app/db.py`, `backend/app/models.py`, `backend/app/cases.py`
**Checks:** scoring/search/misstype/elo tests pass on synthetic fixtures; all API endpoints; GT-leak invariant tested; `make db-reset` idempotent
**Deps:** M0 (schemas); engines can start on synthetic fixtures before M1/M2

## M4 — Reading room UI (frontend-engineer, ~5 h)
**Files:** `frontend/src/` (viewer, marks, telemetry, rail, reveal, pages)
**Checks:** Playwright e2e: onboarding→case→zoom/pan→loupe→marks→hint→submit→reveal→facts card→debrief(template)→next case; telemetry ≥30 events/10s; coord mapping ≤2px
**Deps:** M0 (types); can start against mock API

## M5 — Claude tutor (tutor-prompt-engineer, ~4 h)
**Files:** `backend/app/tutor/`, `backend/app/prompts/`, `content/teaching_cards/`
**Checks:** 13 cards schema-valid, validator catches seeded errors, templates pass validator, offline mode works; live smoke after human checkpoint
**Deps:** M0 (schemas); mocked client until live checkpoint

## M6 — Adaptive engine and dashboards (backend + frontend, ~3 h)
**Files:** `backend/app/adaptive/`, `backend/app/analytics/`, `frontend/src/dashboard/`
**Checks:** Elo simulation tests pass, dashboard renders learning curve/miss-type/calibration/blind-spot/FROC
**Deps:** M3, M4

## M7 — Evaluation and review (eval-scientist, ~4 h + run time)
**Files:** `eval/`, `frontend/src/review/`
**Checks:** dry-run passes, /review works, pilot flow works, SUS form works
**Deps:** M5 (tutor pipeline), M3 (scoring)

## M8 — Demo hardening (orchestrator + qa-reviewer, ~3 h)
**Files:** `config/demo_playlist.yaml`, `tests/e2e/`
**Checks:** `make demo` works, full e2e passes 3× online+offline, /about complete
**Deps:** all previous

## Parallel waves
| Wave | When | Agents |
|------|------|--------|
| W0 | Mon 21:30–22:15 | orchestrator: M0 |
| W1 | Mon 22:15→overnight | data-engineer M1, backend M3 (engines on fixtures), frontend M4 (mock API), tutor M5 (cards+validator on mocks) |
| W2 | overnight→Tue AM | vision-ml M2, backend M3 (API+DB), frontend M4 (reveal+facts), eval M7 (dry-run) |
| W3 | Tue | integrate real data, M5 live debrief, M6, qa e2e |
| W4 | Wed | M7 live, /review, pilot, M8, 18:00 feature freeze |
| W5 | Thu | fixes only, 14:00 code freeze |
